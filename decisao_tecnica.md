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

O juiz devolve um resultado interno: `aprovado`, `recusado` ou `erro`. Usamos esse resultado para autorizar a confirmação, sem depender de comparar a frase mostrada no chat. Mantivemos a regra do juiz: resposta apoiada e nota de pelo menos 0,70.

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
| **Interceptar** | Uma etapa avaliaria a ação planejada antes de chamar a ferramenta. | Uma ação reprovada poderia ser barrada antes de executar o SQL. | Precisaríamos representar e avaliar a ação antes da execução. Além disso, o juiz final ainda poderia recusar a resposta depois da escrita. Interceptar sozinho não resolveria essa recusa tardia mantendo o juiz final. Seria necessário combinar essa avaliação com uma proteção para a escrita. |
| **Adiar** | A ferramenta prepararia um plano e o SQL seria executado depois da aprovação. | A transação de escrita não precisaria esperar os modelos e o juiz. | Precisaríamos guardar e executar os planos, além de lidar com IDs e consultas de registros que ainda não existem. O juiz também não teria o retorno real do SQL para avaliar. Usamos essa ideia somente no envio ao Google Calendar. |
| **Compensar** | A ferramenta confirmaria normalmente e, depois de uma recusa, outra operação apagaria o registro ou restauraria os valores anteriores. | As ferramentas poderiam continuar confirmando as alterações imediatamente. | A operação que desfaz também poderia falhar. Outra pessoa poderia consultar ou alterar o registro nesse intervalo, e restaurar os dados anteriores poderia sobrescrever uma mudança feita depois. |

Escolhemos transacionar porque aproveita o que o Postgres já oferece e permite usar o retorno real das ferramentas como evidência. Também evita confirmar uma alteração para depois tentar desfazê-la.

O principal custo é manter a conexão e possíveis bloqueios no banco enquanto esperamos o restante do turno.

As famílias podem ser combinadas. Por exemplo, executar vários planos adiados ainda poderia precisar de uma transação para confirmar todos juntos.

## 3. O efeito nas métricas do SRE

Primeiro comparamos o que esperar de cada caminho. Depois mostramos os
resultados medidos antes e depois da nossa implementação.

### Comparação entre as quatro soluções

Implementamos somente transacionar. Para as outras três soluções, a comparação
abaixo explica os efeitos esperados pelo funcionamento de cada uma. Não temos
tempos, taxas de erro ou preços medidos dessas alternativas.

| Solução | Latência e p95 — SLO de 8 segundos | Conexão e concorrência |
| --- | --- | --- |
| **Interceptar** | Uma avaliação extra por modelo ou juiz acrescentaria tempo aos pedidos aprovados. Uma recusa antecipada poderia encerrar o turno mais cedo. Uma verificação feita só por código teria outro custo. | Evitaria a escrita de pedidos já reprovados, mas os dados poderiam mudar entre a avaliação e a execução. Além disso, a recusa do juiz final ainda precisaria de outra proteção. |
| **Adiar** | Preparar e executar o plano também levaria tempo. Poderia reduzir a espera por bloqueios entre turnos, mas não garantiria uma resposta mais rápida em todos os casos. | A transação de escrita seria aberta depois da aprovação. As consultas anteriores ainda poderiam acessar o banco, mas não enxergariam uma alteração que fosse apenas um plano. |
| **Transacionar** | Mantém as chamadas existentes aos modelos e ao juiz. A confirmação acontece no final. Executar as ferramentas em sequência e esperar por registros ocupados pode aumentar o tempo e o p95. | A conexão e possíveis bloqueios ficam retidos até o veredito. As consultas do mesmo turno enxergam as alterações pendentes. |
| **Compensar** | Guardar os dados anteriores daria trabalho adicional. Na recusa, seria preciso executar outro SQL para desfazer, o que poderia aumentar a latência. | A conexão original seria liberada cedo, mas a reversão voltaria a disputar o banco. Nesse intervalo, outro turno poderia consultar ou alterar o registro. |

| Solução | Tokens e custo | Falhas e status |
| --- | --- | --- |
| **Interceptar** | Outra chamada de modelo geraria mais tokens e custo. Uma avaliação só por código não geraria tokens. Uma chamada extra ao JEV consumiria o serviço, mas não entraria na conta atual de tokens. | Recusa antecipada seria `bloqueado`; falha na avaliação seria `erro`, sem executar a escrita. Aprovar a ação antes não garante a aprovação da resposta final. |
| **Adiar** | Preparar e executar planos com código não exige outro modelo. Se chamássemos um modelo para redigir novamente após o SQL, haveria mais tokens, custo e latência. | Recusa descartaria o plano. Erro ao executá-lo seria `erro`; `ok` só poderia ser informado após a execução. Várias escritas ainda precisariam ser confirmadas juntas para evitar um resultado parcial. |
| **Transacionar** | O controle de commit/rollback usa código, sem outro modelo. Os tokens ainda podem variar entre respostas. O custo principal é manter recursos do banco ocupados enquanto esperamos. | Recusa normal fica como `bloqueado`; falha técnica fica como `erro`; conclusão sem falha nem recusa fica como `ok`. As escritas pendentes são desfeitas na recusa ou falha anterior ao commit. |
| **Compensar** | Desfazer com código não exige outro modelo, mas consome mais operações do banco. Uma nova redação por modelo, se adotada, teria custo separado. | A recusa só poderia terminar como `bloqueado` depois de restaurar o estado. Se a reversão falhasse, seria `erro` e a alteração poderia permanecer. |

Em todos os caminhos, uma exceção deve contar como erro. O bloqueio esperado
do guardrail de entrada não conta como erro. Mostrar uma frase segura por
causa de uma falha técnica também não pode ser contado como sucesso.

O monitor estima o custo dos tokens dos modelos que acompanha. Ele não mede
o custo de infraestrutura, operações SQL, JEV ou Google Calendar. Portanto,
uma operação sem tokens ainda pode consumir tempo e recursos.

Escolhemos transacionar pela garantia de escrita e por aproveitar o código
existente. Isso não significa que seja a solução mais rápida ou mais barata.
Para comparar o desempenho real das quatro, precisaríamos implementar e
medir todas com os mesmos testes.

### O que medimos antes e depois

Fizemos 22 tentativas: dez pedidos financeiros e um bloqueio de entrada em
cada versão. Os pedidos financeiros foram criar uma despesa e consultar o
saldo, repetidos cinco vezes. A ordem alternou entre as versões, e cada
tentativa começou com uma nova sessão e os mesmos dados de teste.

A cota do Gemini acabou durante a primeira rodada. Guardamos essa tentativa
separadamente e usamos o mesmo fallback Groq nas duas versões na comparação
abaixo. O Gemini ficou indisponível apenas nos processos de teste, sem mudar
a configuração da aplicação.

| Medida | Antes da Etapa 8 | Depois da Etapa 8 |
| --- | ---: | ---: |
| Latência média dos pedidos financeiros | 29,39 s | 30,83 s |
| p95 da amostra financeira | 55,30 s | 50,21 s |
| Tokens médios por tentativa financeira | 6.895,1 | 8.012,1 |
| Custo médio estimado por tentativa financeira | US$ 0,00126111 | US$ 0,00149274 |
| Tempo médio de retenção da conexão SQL | 0,52 s | 16,16 s |
| Erros técnicos nas 11 tentativas | 8/11 — 72,7% | 6/11 — 54,5% |
| Status `ok` / `erro` / `bloqueado` | 2 / 8 / 1 | 3 / 6 / 2 |

Os SLOs de 8 segundos e 5% de erros não foram atingidos nessa rodada. Houve
falhas no fallback nas duas versões, inclusive nas consultas de saldo. Em
um diagnóstico adicional, o Groq tentou chamar uma ferramenta chamada `JSON`,
que não existe. Esse diagnóstico ficou separado das 22 tentativas.

As médias incluem falhas, que podem terminar mais cedo e usar menos tokens
sem atender ao usuário. Por isso, não podemos usar esses números para afirmar
que a correção deixou o sistema mais rápido ou barato. Com dez pedidos por
versão, o p95 calculado também é o maior tempo observado, sem representar um
p95 estável de produção.

O SQL usou tabelas temporárias em uma conexão já aberta antes da medição.
Os empréstimos dessa conexão foram executados um por vez nas duas versões.
Assim, não medimos o tempo de abrir conexões físicas nem o comportamento com
vários usuários simultâneos. Nenhum registro pessoal foi alterado.

Esta tabela reúne os resultados da medição. Os dados brutos e os materiais
auxiliares ficaram arquivados localmente, fora da entrega.
O resultado importante para a Etapa 8 foi preservado: na versão corrigida,
as criações recusadas ou interrompidas por falha antes do commit não ficaram
salvas; as três criações aprovadas tiveram um commit cada.

## 4. Outras decisões e evidências

### Google Calendar

Incluímos `add_google_event`, mas deixamos o envio para depois da aprovação do juiz e do commit no Postgres.

Fizemos isso porque o rollback do Postgres não consegue apagar um evento do Google. Enquanto espera, a ferramenta devolve `pendente`. Se o juiz recusar, o programa descarta o envio.

Se o Google falhar depois do commit, o compromisso continua salvo no Postgres, o usuário recebe um aviso e o monitor registra erro. Sem uma escrita local confirmada, o envio não acontece.

Os pedidos pendentes ficam só na memória do programa. Não implementamos uma nova tentativa automática nem um mecanismo para recuperar esses envios após uma queda.

### Histórico da conversa

Mantivemos `salvar_mensagem` depois da conclusão do grafo. Ela salva no MongoDB a pergunta anonimizada e a resposta final, mesmo quando houve recusa.

Escolhemos manter esse histórico porque registrar a conversa não é o mesmo que confirmar uma compra ou um compromisso.

O Mongo ficou fora da transação. Se ele falhar depois do commit, a alteração no Postgres permanece e o turno termina como erro.

### Se o juiz não responder

Sem chave, com timeout ou com uma resposta inválida, não há aprovação. O programa desfaz as alterações pendentes, mostra uma resposta segura e registra `erro` no monitor.

Se uma ferramenta falhar, as outras escritas do mesmo turno também não são confirmadas. Isso inclui erros SQL e argumentos inválidos. Atualizar um ID inexistente também não é informado como sucesso.

### Se o programa parar no meio

- **Antes do commit:** o Postgres desfaz as alterações quando identifica que a conexão foi perdida. Essa identificação pode demorar; até lá, os bloqueios podem continuar.
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

Na versão anterior, as três alterações permaneciam após a recusa. A linha de base está no commit `1b6e64fbb6428245c37104285dc7350846ac915f`. Os casos foram:

| Ferramenta | Marcador da versão anterior | Antes → depois da recusa | Commits |
| --- | --- | --- | --- |
| `add_transaction` | `E8-add_transaction-ee78277c42` | Nenhum registro → um registro de 30 | 1 |
| `update_transaction` | `E8-update_transaction-50ffae3c18` | Valor 10 → valor 99 | 1 |
| `add_event` | `E8-add_event-ce6ca611ee` | Nenhum evento → um evento | 1 |

Antes de preparar a entrega, executamos 45 testes Python e cinco cenários do frontend, que passaram. Os scripts dessas verificações ficaram arquivados localmente. Esses testes cobrem as falhas e os fluxos existentes com serviços simulados. O envio ao Google Calendar foi verificado de forma simulada; não fizemos um envio real para uma conta Google.

## 5. Arquivos criados e modificados

A comparação usa a primeira entrega, no commit
`1b6e64fbb6428245c37104285dc7350846ac915f`. Os scripts de validação ficaram arquivados localmente; a entrega reúne
as evidências neste documento.

### Arquivos criados

- `decisao_tecnica.md`: explica a escolha, as alternativas, as métricas e as evidências.

### Arquivos modificados

- `app/tools/db.py`: controla a conexão por turno, o commit, o rollback e os pedidos pendentes do Google.
- `app/tools/financeiro.py`: faz as ferramentas financeiras usarem a conexão do turno e impede a confirmação quando uma operação falha.
- `app/tools/agenda.py`: aplica o mesmo controle ao registro e à consulta de compromissos.
- `app/juiz.py`: devolve o veredito interno, verifica a resposta do serviço e avalia somente a resposta do turno atual.
- `app/graph.py`: inicia o controle do turno, organiza as ferramentas e confirma ou desfaz as alterações depois do juiz.
- `app/tools/calendario_google.py`: deixa o envio ao Google para depois da aprovação e da confirmação no Postgres.
- `app/prompts/agenda_prompt.py`: inclui o estado `pendente` e ajusta os exemplos ao novo funcionamento.
- `app/guardrail.py`: esclarece que corrigir os próprios lançamentos por ID é permitido.
- `app/observabilidade.py`: diferencia a recusa do juiz de uma falha técnica no monitor.
- `README.md`: atualiza as instruções e indica a documentação e os testes da Etapa 8.
