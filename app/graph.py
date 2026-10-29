# Imports
import operator
from langgraph.checkpoint.memory import MemorySaver # -> Substitui a função que tínhamos criado para histórico com sessões, porque faz isso automaticamente
from langchain_core.messages import RemoveMessage
from langchain_core.runnables import RunnableConfig
from typing import Annotated
from langgraph.graph import StateGraph, MessagesState, END
from app.guardrail import guardrail_entrada, guardrail_saida, anonimizar_entrada
from app.memory import salvar_mensagem
from app.observabilidade import abrir_turno, fechar_turno, status_do_estado
from app.config.agents import router_app, financeiro_app, agenda_app, faq_app, orquestrador_app
from app.juiz import no_juiz, FRASE_SEGURA
from app.tools.db import iniciar_transacao, concluir_transacao
from app.tools.calendario_google import add_google_event
from app.prompts.persona_prompt import contexto_temporal



# ==============================================================================
# ESTADO
# ==============================================================================
class Estado(MessagesState):
    agentes_chamados: Annotated[list[str], operator.add]
    rota: str
    mapa_pii: dict
    session_id: str
    veredito_juiz: str
    erro_escrita: bool


# ==============================================================================
# NÓS
# ==============================================================================

def no_guardrail_entrada(estado: Estado) -> dict:
    human_message = list(estado["messages"])[-1]

    texto_anonimizado, mapa = anonimizar_entrada(human_message.text)

    resultado = guardrail_entrada(texto_anonimizado)

    if resultado["bloqueado"]:
        # Mesmo quando a mensagem é bloqueada, não deixe a versão original
        # (com possível PII) salva no histórico do MemorySaver.
        return {
            "messages": [
                RemoveMessage(id=human_message.id),
                {"role": "human", "content": texto_anonimizado},
                {"role": "assistant", "content": resultado["mensagem"]},
            ],
            "rota": "fim",
            "mapa_pii": {},
            "agentes_chamados": [f"guardrail_entrada: {resultado['motivo']}"],
        }
    
    return {
        "messages": [
            RemoveMessage(id=human_message.id),  # Remove a mensagem original do usuário
            {"role": "human", "content": texto_anonimizado}
        ],
        "mapa_pii": mapa,
        "agentes_chamados": ["guardrail_entrada"],
        "rota": "roteador",
    }

def no_roteador(estado: Estado, config: RunnableConfig) -> dict:
    saida = router_app.invoke({"messages": list(estado["messages"])}, config=config)
    texto = saida["messages"][-1].text

    if "ROUTE=" not in texto:

        return {
            "agentes_chamados": ["roteador"],
            "rota":             "fim",
            "messages":         [{"role": "assistant", "content": texto}],
        }

    rota = "fim"
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith("ROUTE="):
            rota = linha.split("=", 1)[1].strip().lower()
            break

    if rota not in ("financeiro", "agenda", "faq"):
        return {
            "agentes_chamados": ["roteador"],
            "rota": "fim",
            "messages": [{
                "role": "assistant",
                "content": "Você quer ajuda com finanças, compromissos ou uma dúvida sobre o Lumi?",
            }],
        }

    return {
        "agentes_chamados": ["roteador", rota],
        "rota":             rota,
        # Preserva a memória consultada neste turno para o especialista e o juiz.
        "messages": saida["messages"][len(estado["messages"]):-1],
    }

def no_orquestrador(estado: Estado, config: RunnableConfig) -> dict:
    # Pega a última resposta do especialista (última AIMessage com conteúdo)
    ultima_especialista = ""
    for mensagem in reversed(estado["messages"]):
        if mensagem.type == "ai" and mensagem.content:
            ultima_especialista = mensagem.content
            break
    # config segue o mesmo motivo do roteador: sem ele, o modelo deste nó
    # não herda o metadata do grafo (e o registro de observabilidade perde o nó).
    saida = orquestrador_app.invoke({
        "messages": [{"role": "human", "content": ultima_especialista}]
    }, config=config)

    return {
        "agentes_chamados": ["orquestrador"],
        "messages":        [{"role": "assistant", "content": saida["messages"][-1].text}]
    }

def no_guardrail_saida(estado: Estado) -> dict:
    ultima_resposta = list(estado["messages"])[-1] 

    resposta_final = guardrail_saida(ultima_resposta.text, estado["mapa_pii"])

    return {
        "agentes_chamados": ["guardrail_saida"],
        "messages": [
            RemoveMessage(id=ultima_resposta.id),
            {"role": "assistant", "content": resposta_final["conteudo"]}
        ],
    }


def no_confirmar_escritas(estado: Estado, config: RunnableConfig) -> dict:
    """Só confirma o Postgres após o juiz; não chama outro modelo."""
    turno_id = config["metadata"]["assessor_turno_id"]
    # Argumentos inválidos podem falhar no LangChain antes de entrar na tool.
    erro_tool = False
    for mensagem in reversed(estado["messages"]):
        if mensagem.type == "human":
            break
        if mensagem.type == "tool" and getattr(mensagem, "status", "") == "error":
            erro_tool = True
    aprovado = estado.get("veredito_juiz") == "aprovado" and not erro_tool
    resultado = concluir_transacao(turno_id, aprovado)
    if resultado["falhou"] or erro_tool:
        return {
            "erro_escrita": True,
            "messages": [{"role": "assistant", "content":
                "Não consegui confirmar a operação. Confira os registros antes de tentar novamente."}],
        }
    if resultado["escritas"] and not resultado["confirmado"]:
        return {"messages": [{"role": "assistant", "content":
            FRASE_SEGURA + " Nenhuma alteração deste turno foi salva."}]}

    # O Google não participa da transação SQL. Só é chamado após o commit.
    if resultado["google"]:
        sucesso = True
        for argumentos in resultado["google"]:
            try:
                retorno = add_google_event.invoke(argumentos, config=config)
                sucesso = sucesso and retorno.get("status") == "ok" and bool(retorno.get("id"))
            except Exception:
                sucesso = False
        aviso = (
            " Google Calendar: envio confirmado."
            if sucesso else
            " O registro local foi salvo, mas não consegui confirmar todos os envios ao Google Calendar."
        )
        return {
            "erro_escrita": not sucesso,
            "messages": [{"role": "assistant", "content": estado["messages"][-1].text + aviso}],
        }
    return {}


def no_limpar_turno(estado: Estado) -> dict:
    """Remove mensagens internas de tools antes de salvar o turno no MemorySaver.

    O histórico da conversa precisa guardar a mensagem do usuário e a resposta
    final do assistente, não os AIMessage/ToolMessage usados internamente por um
    especialista. Se esses tool calls ficam no histórico, outro agente pode tentar
    continuá-los num turno futuro mesmo sem possuir aquela tool.
    """
    mensagens = list(estado["messages"])

    ultimo_humano = None
    for i, mensagem in enumerate(mensagens):
        if mensagem.type == "human":
            ultimo_humano = i

    if ultimo_humano is None:
        return {}

    ultima_resposta = None
    for i in range(len(mensagens) - 1, ultimo_humano, -1):
        mensagem = mensagens[i]
        if mensagem.type == "ai" and mensagem.content:
            ultima_resposta = i
            break

    if ultima_resposta is None:
        return {}

    remover = []
    for mensagem in mensagens[:ultimo_humano]:
        if mensagem.type == "system" and mensagem.id:
            remover.append(RemoveMessage(id=mensagem.id))
    for i in range(ultimo_humano + 1, len(mensagens)):
        if i == ultima_resposta:
            continue
        mensagem = mensagens[i]
        if mensagem.id:
            remover.append(RemoveMessage(id=mensagem.id))

    return {"messages": remover} if remover else {}


# ==============================================================================
# FUNÇÃO DE DECISÃO
# ==============================================================================
def decidir_especialista(estado: Estado) -> str:
    return estado["rota"] if estado["rota"] in ("financeiro", "agenda", "faq") else "fim"

def decidir_pos_guardrail_entrada(estado: Estado) -> str:
    return estado["rota"]

# ==============================================================================
# CONSTRUÇÃO DO GRAFO
# ==============================================================================
grafo = StateGraph(Estado)

grafo.add_node("guardrail_entrada", no_guardrail_entrada)
grafo.add_node("roteador",     no_roteador)
grafo.add_node("financeiro", financeiro_app)
grafo.add_node("agenda", agenda_app)
grafo.add_node("faq", faq_app)
grafo.add_node("orquestrador", no_orquestrador)
grafo.add_node("guardrail_saida", no_guardrail_saida)
grafo.add_node("juiz", no_juiz)
grafo.add_node("confirmar_escritas", no_confirmar_escritas)
grafo.add_node("limpar_turno", no_limpar_turno)

grafo.set_entry_point("guardrail_entrada")

grafo.add_conditional_edges(
    "guardrail_entrada",
    decidir_pos_guardrail_entrada,
    {
        "roteador": "roteador",
        "fim": "limpar_turno",
    }
)

grafo.add_conditional_edges(
    "roteador",
    decidir_especialista,
    {
        "financeiro": "financeiro",
        "agenda":     "agenda",
        "faq":        "faq",
        "fim":        "limpar_turno",  # resposta direta: encerra o turno com histórico limpo
    },
)

grafo.add_edge("financeiro",      "orquestrador")
grafo.add_edge("agenda",          "orquestrador")
grafo.add_edge("orquestrador",    "guardrail_saida")
grafo.add_edge("guardrail_saida", "juiz")
grafo.add_edge("faq",             "juiz")
grafo.add_edge("juiz",            "confirmar_escritas")
grafo.add_edge("confirmar_escritas", "limpar_turno")
grafo.add_edge("limpar_turno",     END)

# Memória centralizada no grafo — persiste o Estado inteiro entre turns
memory = MemorySaver()
fluxo_agentes = grafo.compile(checkpointer=memory)


# ==============================================================================
# FLUXO PRINCIPAL
# ==============================================================================
def executar_fluxo_assessor(
    pergunta_usuario: str, session_id: str, user_id: str = "usuario_teste"
) -> str:
    pergunta_usuario_anonimizado, _ = anonimizar_entrada(pergunta_usuario)
    estado_inicial = {
        "messages":         [
            {"role": "system", "content": contexto_temporal()},
            {"role": "human", "content": pergunta_usuario},
        ],
        "agentes_chamados": [],
        "rota":             "",
        "mapa_pii":         {},
        "session_id":       session_id,
        "veredito_juiz":    "",
        "erro_escrita":     False,

    }

    # O registro abre antes do invoke e fecha no finally, inclusive quando
    # o grafo levanta. A rota /monitor só lê o que ficou anotado.
    turno_id = abrir_turno()
    iniciar_transacao(turno_id)
    status = "erro"
    rota = ""
    try:
        estado_final = fluxo_agentes.invoke(
            estado_inicial,
            config={
                "configurable": {
                    "thread_id": session_id,
                    "user_id": user_id,
                },
                # Metadata acompanha os nós e modelos, inclusive em outras threads.
                "metadata": {"assessor_turno_id": turno_id},
                # Preserva a ordem das tools: uma consulta pode depender da escrita anterior.
                "max_concurrency": 1,
            },
        )

        resposta = estado_final["messages"][-1].text
        rota = estado_final.get("rota") or ""

        # Salva no MongoDB após cada interação
        salvar_mensagem(session_id, "human",     pergunta_usuario_anonimizado, user_id=user_id)
        salvar_mensagem(session_id, "assistant", resposta, user_id=user_id)

        status = status_do_estado(estado_final)
        return resposta
    finally:
        # Também desfaz se o grafo falhar antes de chegar ao juiz.
        concluir_transacao(turno_id, False)
        fechar_turno(turno_id, session_id=session_id, rota=rota, status=status)
    

# # PROCESSO DE PERGUNTAS E RESPOSTAS ATÉ QUE O USUÁRIO ENCERRE O CHAT
# session_id = "12345"
# iniciar_sessao(session_id=session_id)

# try:
#     while True:
#         user_input = input("👥 ")
#         if user_input.lower() in ('sair', 'end', 'fim', 'tchau', 'bye'):
#             print("Encerrando a conversa.")
#             raise SystemExit(0)
#         try:
#             resposta = executar_fluxo(
#                 pergunta_usuario=user_input,
#                 session_id=session_id
#             )

#             print(resposta)
#         except Exception as e:
#             print("Erro ao consumir a API:", e)

# except KeyboardInterrupt:
#     print("Sessão encerrada pelo usuário!")

# finally:
#     resumo = encerrar_sessao(session_id=session_id)
#     print("=== RESUMO DA SESSÃO ===\n")
#     print(resumo)
