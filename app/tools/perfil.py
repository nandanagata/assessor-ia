from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.perfil import buscar_perfil, buscar_restricoes


@tool
def consultar_perfil_financeiro(pergunta: str, config: RunnableConfig) -> str:
    """Consulta o perfil financeiro estável do usuário para apoiar um conselho.

    Use quando a resposta depender de renda, gastos fixos, horizonte, perfil de
    investidor ou restrições pessoais. O usuário é obtido automaticamente do
    contexto da requisição; informe somente a pergunta que precisa ser analisada.
    """
    configuravel = (config or {}).get("configurable", {})
    user_id = configuravel.get("user_id")

    if not user_id:
        return "Não foi possível identificar o usuário para consultar o perfil."

    perfil = buscar_perfil(user_id)
    if not perfil:
        return (
            "Nenhum perfil financeiro cadastrado. Oriente o usuário a preencher "
            "a tela Perfil e não invente renda, gastos, horizonte ou restrições."
        )

    restricoes = buscar_restricoes(user_id, pergunta)
    restricoes_texto = (
        "\n".join(f"- {restricao}" for restricao in restricoes)
        if restricoes
        else "Nenhuma restrição relevante encontrada."
    )

    return (
        f"Renda mensal: R$ {perfil['renda_mensal']:.2f}\n"
        f"Gasto fixo mensal: R$ {perfil['gasto_fixo_mensal']:.2f}\n"
        f"Horizonte: {perfil['horizonte_meses']} meses\n"
        f"Perfil de investidor: {perfil['perfil_investidor']}\n"
        f"Restrições relacionadas à pergunta:\n{restricoes_texto}"
    )


TOOLS_PERFIL = [consultar_perfil_financeiro]
