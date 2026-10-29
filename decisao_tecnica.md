# Etapa 8 — o juiz e a escrita

## 1. A decisão tomada e por quê

Escolhemos usar principalmente a família **transacionar**. As três ferramentas obrigatórias já usam o Postgres e o problema estava no momento de confirmar as alterações: a ferramenta gravava definitivamente antes de o juiz avaliar a resposta.

Nossa ideia foi manter as alterações pendentes durante o turno e só confirmar depois da aprovação do juiz. Isso vale para `add_transaction`, `update_transaction` e `add_event`.

Para `add_google_event`, usamos a ideia de **adiar**, porque o envio acontece fora do Postgres e não pode ser desfeito pelo mesmo rollback.

Nosso objetivo era aproveitar a estrutura que já tínhamos. Não criamos outro agente, dependência, tabela permanente, rota ou formato de API.

### Como era antes

`tool → SQL → commit/fechar → orquestrador → guardrail de saída → juiz → resposta`

A ferramenta já tinha confirmado a alteração quando o juiz recebia a resposta. Se ele recusasse, o chat mostrava uma frase segura, mas a alteração continuava no banco.

### Como ficou

`tool → SQL pendente → orquestrador → guardrail de saída → juiz → confirmar_escritas → resposta`

Agora, o nó `confirmar_escritas` decide se as alterações podem permanecer. Se o juiz aprovar e nenhuma operação tiver falhado, o programa faz o commit. Se houver recusa ou falha antes da confirmação, faz rollback.

Uma transação funciona como um rascunho: as alterações já foram executadas, mas ainda não são definitivas. O `commit()` confirma o conjunto e o `rollback()` desfaz as alterações pendentes.

### Como isso acontece no código

Cada turno recebe um identificador, que também é usado pelo monitor. Esse identificador acompanha as chamadas pelo `RunnableConfig` e permite encontrar a conexão daquele turno em `app/tools/db.py`.

A conexão só é aberta quando uma ferramenta SQL precisa dela. As ferramentas do mesmo turno compartilham essa conexão, inclusive as consultas, que conseguem enxergar as alterações ainda pendentes.

Dentro do chat, `confirmar_operacao()` apenas registra que houve uma escrita. O commit fica para `concluir_transacao()`, chamada depois do juiz.

O juiz devolve um resultado interno: `aprovado`, `recusado` ou `erro`. Usamos esse resultado para autorizar a confirmação, sem depender de comparar a frase mostrada no chat.

Também usamos um `Lock` por turno para proteger a conexão e `max_concurrency=1` para executar as ferramentas na ordem solicitada. Se uma consulta vier depois de uma escrita, ela consegue consultar essa alteração pendente.

Se o fluxo apresentar uma exceção antes da conclusão, o `finally` tenta desfazer e fechar a transação que ainda estiver aberta.

### A garantia nas três ferramentas

- `add_transaction`: se o turno for recusado, o lançamento novo não permanece.
- `update_transaction`: se o turno for recusado, a alteração é desfeita e o registro mantém os dados anteriores.
- `add_event`: se o turno for recusado, o compromisso novo não permanece.

Se houver várias escritas no mesmo turno, elas são confirmadas ou desfeitas juntas. Uma falha em uma operação impede confirmar as demais.

Na aprovação, a ferramenta não é executada novamente. O programa apenas confirma o SQL que já estava pendente.

Essa garantia vale para o fluxo do `/chat`. As chamadas diretas às ferramentas, inclusive pelo servidor MCP, continuam funcionando sem o juiz do chat.

## 2. As alternativas que não escolhemos para o Postgres

Consideramos as outras famílias, mas achamos que transacionar se encaixava melhor na estrutura atual.

| Alternativa | Como funcionaria no nosso projeto | Vantagem | Custo e motivo de não escolher |
| --- | --- | --- | --- |
| **Interceptar** | Uma etapa avaliaria a ação planejada antes de chamar a ferramenta. | Uma ação reprovada poderia ser barrada antes de executar o SQL. | Precisaríamos representar e avaliar a ação antes da execução. Além disso, o juiz final ainda poderia recusar a resposta depois da escrita. Interceptar sozinho não resolveria essa recusa tardia mantendo o fluxo atual. Para implementar ela seria necessário mudar a estrutura. |
| **Adiar** | A ferramenta prepararia um plano e o SQL seria executado depois da aprovação. | A conexão não precisaria ficar aberta enquanto esperamos os modelos e o juiz. | Precisaríamos guardar e executar os planos, além de lidar com IDs e consultas de registros que ainda não existem. O juiz também não teria o retorno real do SQL para avaliar. Usamos essa ideia somente no envio ao Google Calendar. |
| **Compensar** | A ferramenta confirmaria normalmente e, depois de uma recusa, outra operação apagaria o registro ou restauraria os valores anteriores. | As ferramentas poderiam continuar confirmando as alterações imediatamente. | A operação que desfaz também poderia falhar. Outra pessoa poderia consultar ou alterar o registro nesse intervalo, e restaurar os dados anteriores poderia sobrescrever uma mudança feita depois. |

Escolhemos transacionar porque aproveita o que o Postgres já oferece e permite usar o retorno real das ferramentas como evidência. Também evita confirmar uma alteração para depois tentar desfazê-la.

O principal custo é manter a conexão e possíveis bloqueios no banco enquanto esperamos o restante do turno.

## 3. Efeitos esperados nas métricas do SRE

Comparamos o projeto antes e depois da Etapa 8. Os efeitos no desempenho são expectativas com base no funcionamento do código, sem garantir que os limites serão atingidos.

| Métrica | Antes da Etapa 8 | Depois da Etapa 8 |
| --- | --- | --- |
| **Latência e p95 — SLO de 8 segundos** | A ferramenta confirmava a alteração e fechava a conexão antes do orquestrador e do juiz. | A conexão fica aberta até a decisão do juiz. Acreditamos que isso pode aumentar a espera quando vários turnos tentarem alterar os mesmos registros. Executar as ferramentas em sequência também pode aumentar o tempo total. |
| **Taxa de erro — SLO de 5%** | O banco podia confirmar uma alteração mesmo que o juiz recusasse a resposta depois. Essa inconsistência não aparecia necessariamente como erro no monitor. | Falhas técnicas do juiz e da confirmação são registradas como `erro`. Esperamos identificar melhor esses problemas, mas não podemos garantir uma taxa abaixo de 5%, pois também dependemos dos serviços externos. |
| **Status `ok`, `erro` e `bloqueado`** | O monitor já identificava falhas do fluxo e bloqueios de entrada, mas não diferenciava corretamente todos os resultados do juiz. | Uma recusa normal do juiz fica como `bloqueado`. Falhas técnicas ficam como `erro`. Turnos concluídos sem falha nem recusa ficam como `ok`. O bloqueio do guardrail de entrada continua fora da taxa de erro. |
| **Tokens e custo** | O fluxo já chamava os especialistas, o orquestrador, o guardrail e o juiz. | Mantivemos essas chamadas. O nó que confirma ou desfaz usa código, sem chamar outro modelo. Por isso, não esperamos um aumento de chamadas por causa dele, embora a quantidade de tokens possa variar entre respostas. |

Comparando com a alternativa **adiar o SQL**, esperaríamos menos tempo de conexão aberta, porque o banco só seria acessado depois da aprovação. Mesmo assim, executar o plano ainda levaria tempo e poderia falhar. Se fosse necessário chamar outro modelo para escrever a resposta após essa execução, também haveria mais tokens, custo e latência.

Nossa escolha prioriza manter a escrita de acordo com o veredito. Isso não significa que ela será mais rápida nem que garante o cumprimento dos SLOs.

## 4. Outras decisões e evidências

### Google Calendar

Incluímos `add_google_event`, mas deixamos o envio para depois da aprovação do juiz e do commit no Postgres.

Fizemos isso porque o rollback do Postgres não consegue apagar um evento do Google. Enquanto espera, a ferramenta devolve `pendente`. Se o juiz recusar, o programa descarta o envio.

Se o Google falhar depois do commit, o compromisso continua salvo no Postgres e o usuário recebe um aviso. Não implementamos uma nova tentativa automática.

### Histórico da conversa

Mantivemos `salvar_mensagem` depois da conclusão do grafo. Ela salva no MongoDB a pergunta anonimizada e a resposta final, mesmo quando houve recusa.

Escolhemos manter esse histórico porque registrar a conversa não é o mesmo que confirmar uma compra ou um compromisso.

O Mongo ficou fora da transação. Se ele falhar depois do commit, a alteração no Postgres permanece e o turno termina como erro.

### Se o juiz não responder

Sem chave, com timeout ou com uma resposta inválida, não há aprovação. O programa desfaz as alterações pendentes, mostra uma resposta segura e registra `erro` no monitor.

Se uma ferramenta falhar, as outras escritas do mesmo turno também não são confirmadas.

### Se o programa parar no meio

- **Antes do commit:** o Postgres desfaz as alterações quando identifica que a conexão foi perdida.
- **Depois do commit:** a alteração pode ficar salva mesmo que a resposta não chegue ao usuário. O envio ao Google também pode ficar sem acontecer.
- **Durante o commit:** pode não ser possível saber se o banco confirmou. Por isso, o programa pede para conferir os registros antes de tentar novamente.

### Se o pedido for repetido

Cada mensagem é um novo turno. Se o usuário mandar a mesma compra duas vezes, ela pode ser registrada duas vezes.

Nossa solução evita executar novamente a ferramenta para confirmar a aprovação. Ela não identifica pedidos repetidos. Por isso, em caso de dúvida, é melhor consultar os registros antes de reenviar.

### Como conferimos

Usamos um marcador único em cada tentativa e comparamos o banco antes e depois. Os testes usaram Postgres real com tabelas temporárias e respostas simuladas dos modelos e do juiz.

| Ferramenta | Veredito | Marcador único | Antes → depois | Commits |
| --- | --- | --- | --- | --- |
| `add_transaction` | Recusado | `E8-add_transaction-b00d4521aa` | Nenhum registro → nenhum registro | 0 |
| `add_transaction` | Aprovado | `E8-add_transaction-3f0bc379de` | Nenhum registro → um registro de 30 | 1 |
| `update_transaction` | Recusado | `E8-update_transaction-ecfdde2ee7` | Valor 10 → valor 10 | 0 |
| `update_transaction` | Aprovado | `E8-update_transaction-9f88b7db0c` | Valor 10 → valor 99 | 1 |
| `add_event` | Recusado | `E8-add_event-92b9724f91` | Nenhum evento → nenhum evento | 0 |
| `add_event` | Aprovado | `E8-add_event-0b2b8029ee` | Nenhum evento → um evento | 1 |

Nas recusas, o juiz devolveu `[juiz] sem_apoio noul=0.10`. Nas aprovações, devolveu `[juiz] apoiada noul=0.95`.

Nos casos testados, a recusa desfez a alteração e a aprovação confirmou uma única vez, sem executar novamente a ferramenta.

Os detalhes estão em `tests/evidencias_etapa8.json`, incluindo os testes da versão anterior, em que as alterações permaneciam mesmo depois da recusa.

## 5. Arquivos criados e modificados

### Arquivos criados

- `decisao_tecnica.md`: explica a solução escolhida, as alternativas, os efeitos esperados nas métricas e as evidências.
- `tests/test_etapa8.py`: testa a aprovação, a recusa e as falhas nas escritas do turno.
- `tests/verificar_postgres_etapa8.py`: compara a versão anterior e a corrigida usando tabelas temporárias no Postgres.
- `tests/evidencias_etapa8.json`: guarda os resultados das nove comparações.

### Arquivos modificados

- `app/tools/db.py`: controla a conexão por turno, o commit, o rollback e os pedidos pendentes do Google.
- `app/tools/financeiro.py`: faz as ferramentas financeiras usarem a conexão do turno e impede a confirmação quando uma operação falha.
- `app/tools/agenda.py`: aplica o mesmo controle ao registro e à consulta de compromissos.
- `app/juiz.py`: devolve o veredito interno, verifica se a resposta do serviço é válida e avalia somente a resposta do turno atual.
- `app/graph.py`: inicia o controle do turno, organiza a execução das ferramentas e confirma ou desfaz as alterações depois do juiz.
- `app/tools/calendario_google.py`: deixa o envio ao Google para depois da aprovação e da confirmação no Postgres.
- `app/prompts/agenda_prompt.py`: inclui o estado `pendente` e ajusta os exemplos ao novo funcionamento.
- `app/guardrail.py`: esclarece que corrigir os próprios lançamentos por ID é permitido.
- `app/observabilidade.py`: diferencia a recusa do juiz de uma falha técnica no monitor.
- `tests/test_revisao.py`: adapta os testes existentes ao controle da transação por turno.
- `README.md`: atualiza as instruções e indica a documentação e os testes da Etapa 8.