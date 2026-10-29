r"""Gera figuras e relatório a partir de medições salvas; não acessa a rede.

Execute: .venv\Scripts\python.exe tests/gerar_graficos_desempenho.py
Usa Matplotlib, disponível no ambiente local, apenas para gerar as figuras.
"""

import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
PASTA = ROOT / "docs/desempenho"
NOMES = {"antes": "Antes · Etapa 7", "depois": "Depois · Etapa 8"}
CORES = {"antes": "#69788C", "depois": "#087F8C"}
CASOS = {f"{tipo}_r{r}": f"{nome} {r}" for r in range(1, 11)
         for tipo, nome in (("criar", "Criar"), ("saldo", "Saldo"))}


def p95(valores):
    return sorted(valores)[math.ceil(.95 * len(valores)) - 1]


def media(linhas, campo):
    return statistics.mean(l["monitor"][campo] for l in linhas)


def num(valor, casas=2):
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def salvar(fig, nome, nota):
    fig.text(.06, .025, nota, fontsize=9, color="#455366", va="bottom")
    fig.tight_layout(rect=(0, .10, 1, .93))
    fig.savefig(PASTA / nome, dpi=180, facecolor="white")
    plt.close(fig)


def barras(ax, valores, ylabel, casas=2):
    objetos = ax.bar([NOMES[v] for v in NOMES], valores, color=list(CORES.values()), width=.55)
    teto = max(valores) or 1
    ax.set_ylim(0, teto * 1.25)
    ax.set_ylabel(ylabel)
    ax.bar_label(objetos, labels=[num(v, casas) for v in valores], padding=6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=.18)
    ax.set_axisbelow(True)


def gerar():
    dados = json.loads((PASTA / "medicoes.json").read_text(encoding="utf-8"))
    base_commit = dados["versoes"]["antes"]
    depois_commit = dados["versoes"]["depois"]
    cenario = dados.get("cenario", "original")
    nome_cenario = "Fallback Groq real" if cenario == "fallback" else "Configuração original de modelos"
    descricao_modelos = (
        "O Gemini é tornado indisponível em memória, igualmente nos dois processos, para que o `with_fallbacks` existente use o Groq real."
        if cenario == "fallback" else
        "Gemini e fallback permanecem disponíveis conforme a configuração original; não há indisponibilidade simulada."
    )
    tentativas = dados["tentativas"]
    # Um par exige os dois resultados; falhas e tentativas incompletas continuam no JSON.
    completos = [c for c in CASOS if all(any(t["caso"] == c and t["versao"] == v and "monitor" in t for t in tentativas) for v in NOMES)]
    linhas = {v: [t for t in tentativas if t["versao"] == v and t["caso"] in completos] for v in NOMES}
    if not completos:
        raise RuntimeError("Ainda não existe nenhum par financeiro medido nas duas versões.")
    n = len(completos)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 12,
                         "axes.labelcolor": "#273445", "text.color": "#273445"})

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.3))
    fig.suptitle("Latência antes e depois da correção", fontsize=17, fontweight="bold")
    for v, itens in linhas.items():
        por_caso = {t["caso"]: t for t in itens}
        axes[0].plot(list(range(n)), [por_caso[c]["monitor"]["latencia_ms"] / 1000 for c in completos],
                     "o-", label=NOMES[v], color=CORES[v], linewidth=2)
        falhas = [i for i, c in enumerate(completos) if por_caso[c]["monitor"]["status"] == "erro"]
        axes[0].scatter(falhas, [por_caso[completos[i]]["monitor"]["latencia_ms"] / 1000 for i in falhas],
                        marker="x", color="#B34C37", s=65, zorder=4, label="Turno com erro" if v == "antes" else None)
    axes[0].set_xticks(list(range(n)), [CASOS[c] for c in completos], rotation=40, ha="right")
    axes[0].set_ylabel("Latência do turno (s)")
    axes[0].set_xlabel("Mesmo caso e repetição nas duas versões")
    axes[0].set_ylim(bottom=0)
    axes[0].legend()
    axes[0].grid(alpha=.18)
    for i, v in enumerate(NOMES):
        vals = [media(linhas[v], "latencia_ms") / 1000, p95([t["monitor"]["latencia_ms"] for t in linhas[v]]) / 1000]
        rect = axes[1].bar([x + (i-.5)*.32 for x in (0, 1)], vals, width=.32, color=CORES[v], label=NOMES[v])
        axes[1].bar_label(rect, labels=[num(x) for x in vals], padding=4)
    axes[1].set_xticks([0, 1], ["Média", "p95 da amostra"])
    axes[1].set_ylabel("Latência do turno (s)")
    axes[1].set_ylim(0, max(8, max(t["monitor"]["latencia_ms"] for v in linhas.values() for t in v) / 1000) * 1.3)
    axes[1].axhline(8, linestyle="--", color="#B34C37", label="SLO: 8 s")
    axes[1].legend(fontsize=9)
    axes[1].grid(axis="y", alpha=.18)
    salvar(fig, "latencia.png", f"{nome_cenario} · {n} tentativas financeiras por versão, incluindo falhas · p95 nearest-rank.\nAmostra exploratória; com menos de 20 turnos, esse p95 é o maior tempo observado.")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.3))
    fig.suptitle("Tokens e custo estimado por turno", fontsize=17, fontweight="bold")
    barras(axes[0], [media(linhas[v], "tokens_total") for v in NOMES], "Tokens médios por turno", 0)
    barras(axes[1], [media(linhas[v], "custo_usd") for v in NOMES], "Custo médio estimado (US$)", 6)
    salvar(fig, "tokens_custo.png", f"{nome_cenario} nas duas versões · mesmos {n} casos · tokens informados pelos provedores.\nEstimativa da tabela existente no projeto; não inclui JEV, Google Calendar ou infraestrutura.")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.3))
    fig.suptitle("Confiabilidade observada na mesma rodada", fontsize=17, fontweight="bold")
    todos = {v: [t for t in tentativas if t["versao"] == v] for v in NOMES}
    base = [0, 0]
    for status, cor, label in (("ok", "#087F8C", "ok"), ("erro", "#B34C37", "erro técnico"), ("bloqueado", "#D9A34A", "bloqueado")):
        vals = [sum(t.get("monitor", {}).get("status") == status for t in todos[v]) for v in NOMES]
        rect = axes[0].bar(list(NOMES.values()), vals, bottom=base, color=cor, label=label, width=.55)
        axes[0].bar_label(rect, labels=[str(x) if x else "" for x in vals], label_type="center", color="white", fontweight="bold")
        base = [a+b for a,b in zip(base, vals)]
    axes[0].set_ylabel("Tentativas, incluindo o bloqueio de entrada")
    axes[0].set_ylim(0, max(base) * 1.3)
    axes[0].legend(ncol=3, fontsize=9, loc="upper center")
    taxas = [100 * sum(t.get("monitor", {}).get("status") == "erro" for t in todos[v]) / len(todos[v]) for v in NOMES]
    barras(axes[1], taxas, "Taxa de erro técnico observada (%)", 1)
    axes[1].axhline(5, color="#B34C37", linestyle="--", label="SLO: até 5%")
    axes[1].legend(loc="upper right")
    salvar(fig, "status_erros.png", f"{nome_cenario}. Bloqueio esperado não conta como erro; falhas permanecem na amostra.\nAmostra pequena e sem carga concorrente: esses percentuais não estimam a confiabilidade de produção.")

    fig, ax = plt.subplots(figsize=(10, 5.3))
    fig.suptitle("Tempo de retenção da conexão SQL", fontsize=17, fontweight="bold")
    for i, v in enumerate(NOMES):
        por_caso = {t["caso"]: t for t in linhas[v]}
        vals = [por_caso[c]["conexao_retida_ms"] / 1000 for c in completos]
        rect = ax.bar([x + (i-.5)*.35 for x in range(n)], vals, width=.35, color=CORES[v], label=NOMES[v])
        ax.bar_label(rect, labels=[num(x) for x in vals], padding=4)
    ax.set_xticks(range(n), [CASOS[c] for c in completos], rotation=35, ha="right")
    ax.set_ylabel("Soma do tempo dos empréstimos da conexão (s)")
    ax.set_ylim(0, max(t["conexao_retida_ms"] / 1000 for v in linhas.values() for t in v) * 1.25)
    ax.legend()
    ax.grid(axis="y", alpha=.18)
    salvar(fig, "conexao.png", f"{nome_cenario} nas duas versões · sessão TEMP real; conexão física preparada fora do cronômetro.\nMede empréstimo até fechamento lógico. Não mede contenção nem abertura de conexões em produção.")

    controle = json.loads((ROOT / "tests/evidencias_etapa8.json").read_text(encoding="utf-8"))
    tools = ["add_transaction", "update_transaction", "add_event"]
    vals = {}
    for versao, modo in (("antes", "antes_recusado"), ("depois", "depois_recusado")):
        vals[versao] = [int(next(t for t in controle["casos"] if t["tool"] == tool and t["modo"] == modo)["antes"] !=
                           next(t for t in controle["casos"] if t["tool"] == tool and t["modo"] == modo)["depois"]) for tool in tools]
    fig, ax = plt.subplots(figsize=(10, 5.3))
    fig.suptitle("Escritas que permaneceram após a recusa", fontsize=17, fontweight="bold")
    for i, v in enumerate(NOMES):
        rect = ax.bar([x + (i-.5)*.35 for x in range(3)], vals[v], width=.35, color=CORES[v], label=NOMES[v])
        ax.bar_label(rect, labels=[str(x) for x in vals[v]], padding=5)
    ax.set_xticks(range(3), tools)
    ax.set_yticks([0, 1], ["Não permaneceu", "Permaneceu"])
    ax.set_ylim(0, 1.4)
    ax.set_ylabel("Resultado de uma recusa por ferramenta")
    ax.legend()
    salvar(fig, "escritas_recusadas.png", "Evidência funcional separada: Postgres real, modelos/JEV simulados.\nUma tentativa recusada por ferramenta e versão; não é uma medição de desempenho ou taxa de produção.")

    campos = ["versao", "caso", "latencia_ms", "http_ms", "status", "tokens_total", "custo_usd", "chamadas_modelo", "fallbacks", "juiz_ms", "conexao_retida_ms", "usos_conexao", "commits", "rollbacks"]
    with (PASTA / "turnos.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for t in tentativas:
            row = {k: t.get(k, "") for k in campos}
            row.update({k: t.get("monitor", {}).get(k, "") for k in ("latencia_ms", "status", "tokens_total", "custo_usd")})
            row["chamadas_modelo"] = len(t.get("chamadas", []))
            row["fallbacks"] = sum(c["fallback"] for c in t.get("chamadas", []))
            writer.writerow(row)

    resumo = {}
    for v, itens in linhas.items():
        todos = [t for t in tentativas if t["versao"] == v]
        resumo[v] = {
            "turnos_financeiros": len(itens), "latencia_media_ms": media(itens, "latencia_ms"),
            "p95_ms": p95([t["monitor"]["latencia_ms"] for t in itens]),
            "tokens_medios": media(itens, "tokens_total"), "custo_medio_usd": media(itens, "custo_usd"),
            "status_todas_tentativas": dict(Counter(t.get("monitor", {}).get("status", "sem_registro") for t in todos)),
            "taxa_erro_todas_tentativas": sum(t.get("monitor", {}).get("status") == "erro" for t in todos) / len(todos),
            "chamadas_modelos": len([c for t in itens for c in t["chamadas"]]),
            "fallbacks": sum(c["fallback"] for t in itens for c in t["chamadas"]),
            "conexao_retida_media_ms": statistics.mean(t["conexao_retida_ms"] for t in itens),
        }
    (PASTA / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    a, d = resumo["antes"], resumo["depois"]
    tabela = "\n".join(f"| {nome} | {num(a[campo], casas)} | {num(d[campo], casas)} |" for nome, campo, casas in [
        ("Latência média (ms)", "latencia_media_ms", 0), ("p95 da amostra (ms)", "p95_ms", 0),
        ("Tokens médios por turno", "tokens_medios", 0), ("Custo médio estimado por turno (US$)", "custo_medio_usd", 6),
        ("Chamadas de modelo no conjunto", "chamadas_modelos", 0), ("Chamadas de fallback no conjunto", "fallbacks", 0),
        ("Retenção média da conexão (ms)", "conexao_retida_media_ms", 0)])
    amostra_sucessos = "\n".join(
        f"- {NOMES[v]}: " + (
            f"{len(ok)} turnos `ok`; média de {num(media(ok, 'latencia_ms')/1000)} s e custo médio estimado de US$ {num(media(ok, 'custo_usd'),6)}."
            if (ok := [t for t in linhas[v] if t['monitor']['status'] == 'ok']) else "nenhum turno `ok`."
        ) for v in NOMES)
    detalhada = "\n".join(f"| {t['versao']} | {t['caso']} | {t.get('monitor',{}).get('latencia_ms','—')} | {t.get('monitor',{}).get('status','sem registro')} | {t.get('monitor',{}).get('tokens_total','—')} | {num(t.get('monitor',{}).get('custo_usd',0),6)} |" for t in tentativas)
    delta = (d["latencia_media_ms"] / a["latencia_media_ms"] - 1) * 100
    comparacao = f"A média observada depois ficou {num(abs(delta), 1)}% {'maior' if delta >= 0 else 'menor'} que antes."
    falhas = "\n".join(
        f"- {NOMES[v]}: {sum(t['monitor']['status'] == 'erro' for t in saldos)} erros em {len(saldos)} consultas de saldo."
        for v in NOMES if (saldos := [t for t in linhas[v] if t['caso'].startswith('saldo')]))
    bad_request = sum(e["tipo"] == "BadRequestError" for t in tentativas for e in t.get("erros_provedor", []))
    recusas = [t for t in tentativas if t['versao'] == 'depois' and t.get('veredito') == 'recusado']
    detalhe_recusas = "\n".join(f"- `{t['caso']}`: `{', '.join(t['rótulos_juiz'])}`; commits: {t['commits']}; estado preservado: {t['antes'] == t['depois']}." for t in recusas) or "Não houve recusa do juiz nesta rodada."
    repeticoes = max(int(c.rsplit('r', 1)[1]) for c in completos)
    doc = f"""# Comparação de desempenho — Etapa 7 × Etapa 8

Leia primeiro a comparação entre **interceptar, adiar, transacionar e compensar**
em [`decisao_tecnica.md`](../../decisao_tecnica.md). Ela explica os mecanismos,
os efeitos esperados nas métricas e a escolha de transacionar. Este relatório
vem depois dessa análise e mede somente **linha de base × solução implementada**.
Não há medições das três alternativas descartadas; os gráficos não as classificam
por velocidade, custo ou taxa de erro.

Medição: {dados['data']}. **Cenário: {nome_cenario} nas duas versões.**
{descricao_modelos} É uma rodada exploratória, com {n} turnos financeiros
por versão. Os números são medições salvas, não estimativas de tempos nem
simulações de respostas. Eles não demonstram que a correção causou uma
melhora ou piora de desempenho em produção.

## Versões e condições

- Antes: commit `{base_commit}`; código extraído do ZIP original, com SHA-256 verificado.
- Depois: código da aplicação entregue no commit `{depois_commit}`.
- Mesmos pedidos e mesmos dados iniciais: uma despesa de R$ 10 por tentativa.
- Casos planejados: {dados['metodo']['casos']}.
- Ordem alternada AB, BA, AB, BA; sessão e processo novos a cada tentativa. O bloqueio de injeção é verificado separadamente em cada versão.
- Parâmetros, guardrails e rubrica do juiz preservados. Os prompts próprios de cada versão permanecem como entregues. {descricao_modelos} Nenhuma configuração da aplicação foi alterada.
- Modelos, JEV, Postgres e histórico Mongo reais. Tabelas TEMP e usuário exclusivo de teste. Nenhum envio ao Google Calendar.
- Imports, montagem das tabelas, conexão física SQL e limpeza ficam fora do cronômetro. A latência apresentada é a do monitor da Etapa 6, incluindo a gravação do histórico Mongo.
- Ambas as versões usam uma sessão SQL TEMP previamente aberta. Os empréstimos nessa sessão são serializados para permitir inspecionar as mesmas tabelas com segurança. Portanto, não medimos o custo real de abrir conexões nem a diferença de paralelismo entre ferramentas. A própria correção também limita as ferramentas do turno a uma por vez.
- A conexão fica restrita ao `search_path=pg_temp`; as escritas não alcançam as tabelas pessoais. A limpeza remove apenas o histórico do usuário de teste.

## Resultados financeiros comparáveis

| Métrica | Antes | Depois |
| --- | ---: | ---: |
{tabela}

{comparacao} Essa diferença é descritiva desta amostra; não prova efeito causal
da correção. As respostas podem gerar quantidades diferentes de tokens e
chamadas, e o tempo do provedor oscila. Consulte também os status das tentativas.
As médias incluem turnos que terminaram em erro: uma falha pode ser rápida e
consumir menos tokens sem atender ao usuário. Por isso, custo por tentativa
não equivale a custo por operação concluída.

Apenas para leitura complementar, os turnos registrados como `ok` tiveram:

{amostra_sucessos}

Esses subconjuntos têm tamanhos e resultados diferentes; não constituem uma
nova comparação controlada e não substituem a tabela com todas as tentativas.

![Latência antes e depois](latencia.png)

O p95 usa o mesmo cálculo nearest-rank do monitor: ordenar e selecionar a
posição `ceil(0,95 × n)`. Com {n} amostras, ele coincide com o maior tempo
observado. Não é uma estimativa estável do p95 de produção. A linha de 8 s
é a meta do roteiro, não uma promessa de que ela foi atingida.

![Tokens e custo](tokens_custo.png)

O custo usa os tokens efetivamente reportados e a tabela já existente no
monitor. É uma estimativa pelo preço cheio; não é o valor cobrado da conta.
JEV, Google Calendar, embeddings não instrumentados e infraestrutura ficam
fora dessa conta. Nenhuma tabela de preços nova foi pesquisada ou adicionada.

![Retenção da conexão](conexao.png)

Antes, cada ferramenta libera sua conexão antes do juiz. Depois, a conexão
compartilhada aguarda a decisão e o commit/rollback. O gráfico mostra o tempo
dos empréstimos no teste; não mede espera por bloqueios entre usuários.
Essa espera mais longa pode afetar concorrência mesmo sem uma chamada extra
de modelo. Adiar o SQL seria uma alternativa para reduzir esse intervalo,
com os custos de plano, IDs e leituras pendentes descritos na decisão técnica.

## Erros e status

Status registrados em todas as tentativas, incluindo o bloqueio de entrada:

- Antes: `{json.dumps(a['status_todas_tentativas'], ensure_ascii=False)}`.
- Depois: `{json.dumps(d['status_todas_tentativas'], ensure_ascii=False)}`.

Taxa de erro registrada: **{num(a['taxa_erro_todas_tentativas'] * 100, 1)}% antes**
e **{num(d['taxa_erro_todas_tentativas'] * 100, 1)}% depois**. O denominador inclui
todas as tentativas da respectiva versão, inclusive o bloqueio esperado.

![Status e taxa de erro](status_erros.png)

Nesta rodada foram registrados {bad_request} retornos `BadRequestError`.
O detalhe das consultas de saldo foi:

{falhas}

Quando há falhas, isso impede considerar o fluxo estável com base nos resultados.
Não houve mudança da aplicação para esconder, repetir ou contornar essas falhas.

Uma consulta adicional de diagnóstico arquivada, fora da amostra, registrou
HTTP 400 do provedor, código `tool_use_failed`: o modelo tentou chamar uma
ferramenta chamada `JSON`, que não existe em `request.tools`. Esse resultado
está em `diagnostico_fallback.json`. Isso identifica o motivo daquela falha;
não prova que todas as falhas anteriores tiveram o mesmo conteúdo, pois
a coleta original guardou a classe do erro, sem a mensagem do provedor.

Recusas observadas na versão corrigida:

{detalhe_recusas}

Os campos `antes`, `depois` e `commits` de cada tentativa permitem conferir
também se uma falha técnica deixou alguma escrita confirmada.

O bloqueio esperado do guardrail de entrada não conta como erro técnico.
Uma taxa de erro baixa nessa amostra pequena não comprova o SLO de 5%.
Os status são os registrados por cada versão, sem reescrever o monitor da
linha de base para melhorar a comparação. A versão corrigida distingue
explicitamente recusa normal de falha técnica do juiz/SQL.

## Garantia de escrita — evidência separada

![Escritas recusadas](escritas_recusadas.png)

Este gráfico usa `tests/evidencias_etapa8.json`: Postgres real, com modelos e
JEV simulados para controlar o veredito. Antes, uma recusa deixou a alteração
nas três ferramentas; depois, nenhuma das três recusas deixou alteração.
As aprovações também foram verificadas naquele arquivo: um commit por caso.
Esses casos demonstram correção funcional; não foram usados nas médias de
latência, tokens ou custo da rodada real.

## Todas as tentativas

| Versão | Caso | Latência (ms) | Status | Tokens | Custo estimado (US$) |
| --- | --- | ---: | --- | ---: | ---: |
{detalhada}

## Limites e reprodução

A execução é sequencial e tem até {repeticoes} repetições de dois pedidos.
Rede, fila e variação das respostas dos provedores continuam presentes.
Não é um teste de carga nem um isolamento causal da mudança. Para avaliar
concorrência e um p95 mais confiável, seria necessária uma amostra maior,
com cota disponível e conexões físicas representativas do uso real.
Não podemos atribuir uma diferença de tempo inteira ao commit/rollback.

`medicoes.json` guarda todas as tentativas, hashes das duas cópias, respostas,
chamadas e o método. `turnos.csv` permite conferir os cálculos em planilha;
`resumo.json` contém as agregações. Falhas não são apagadas. Uma interrupção
é registrada no JSON; pares incompletos não entram na tabela comparável.

```powershell
.venv\\Scripts\\python.exe tests/comparar_desempenho.py --cenario {cenario} --repeticoes {repeticoes}
.venv\\Scripts\\python.exe tests/gerar_graficos_desempenho.py
```

O primeiro comando faz novas chamadas reais, consome cota e exige `.env`
local, bancos disponíveis e o ZIP original em `Downloads/Assessor.zip`
(ou `--zip-base CAMINHO`). O segundo apenas lê os dados salvos e gera as
figuras com Matplotlib, disponível no ambiente usado para esta análise.
Matplotlib não foi acrescentado às dependências da aplicação.

## Tentativa com a configuração original

O arquivo `medicoes_configuracao_original.json` preserva a primeira rodada.
A verificação curta inicial do Gemini funcionou; durante o primeiro par
financeiro, o provedor indicou limite de cota e o turno da versão corrigida
terminou com erro. A rodada foi interrompida para não continuar consumindo
chamadas nessa condição. Os tempos dela não foram misturados aos gráficos
do cenário com fallback, pois as condições dos dois lados eram diferentes.

O experimento com fallback permite comparar as duas versões nesse cenário
comum, mas não substitui uma rodada com Gemini disponível nos dois lados.
Para isso, use `--cenario original` com cota suficiente; preserve os resultados
anteriores antes de executar novamente, pois `medicoes.json` é o resultado atual.
"""
    if dados.get("interrupcao"):
        doc += "\n**Interrupção registrada:** " + dados["interrupcao"] + "\n"
    (PASTA / "comparacao_desempenho.md").write_text(doc, encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    gerar()
