# Etapa 8 — o juiz e a escrita

## Decisão: uma transação do Postgres por turno

Escolhemos **transacionar**. As três ferramentas obrigatórias já usam Postgres
e já têm `commit()` e `rollback()`. O problema era o momento do commit.
Mantivemos o SQL das ferramentas e passamos a decisão final para depois do juiz.
Não criamos agente, dependência, tabela permanente, rota ou API nova.

Antes:

`tool → SQL → commit/fechar → orquestrador → guardrail de saída → juiz → resposta`

Depois:

`tool → SQL pendente → orquestrador → guardrail de saída → juiz → confirmar_escritas → resposta`

Em `confirmar_escritas`, aprovação confirma a conexão uma vez; recusa desfaz
todas as escritas da conexão. Isso alcança tanto os INSERTs de
`add_transaction` e `add_event` quanto o UPDATE de `update_transaction`.
A ferramenta não é executada novamente depois da aprovação.

Uma transação é como um rascunho: as alterações podem ser consultadas pelas
ferramentas do próprio turno, mas ainda não estão confirmadas para as demais
conexões. `commit()` confirma o conjunto; `rollback()` abandona o conjunto.
IDs de sequências podem ter intervalos após um rollback; isso não significa
que uma linha foi salva.

## Como o código faz isso

1. `executar_fluxo_assessor` registra a transação usando o identificador único
   que o monitor já cria para cada turno. A conexão é aberta somente quando
   alguma ferramenta SQL precisa dela.
2. `RunnableConfig` transmite esse identificador às ferramentas. A conexão
   fica em `app/tools/db.py`, fora das mensagens e do estado do MemorySaver.
3. `get_conn(config)` devolve a conexão do turno. Cada ferramenta fecha seu
   cursor; a conexão continua disponível. As consultas usam a mesma conexão
   para enxergar as alterações pendentes.
4. `confirmar_operacao` registra que houve uma escrita, sem confirmar o banco.
   `desfazer_operacao` marca o turno como falho. Se uma ferramenta falhar, as
   outras escritas do turno também não podem ser confirmadas.
5. O juiz mantém suas regras e o limiar de 0,70. Além da resposta, devolve um
   campo interno: `aprovado`, `recusado` ou `erro`. Não usamos comparação com
   uma frase do chat para autorizar o commit.
6. O novo nó `confirmar_escritas` confirma ou desfaz e fecha a conexão. Ele
   também detecta erros de argumentos que o LangChain pode produzir antes de
   executar a função da ferramenta.
7. Se uma exceção interromper o grafo antes desse nó, o `finally` da função
   principal desfaz e fecha a transação que ainda estiver aberta.

Existe um `Lock` por turno porque o LangChain pode executar ferramentas em
threads diferentes. Ele permite uma ferramenta por vez na conexão daquele
turno. Outros turnos recebem outras conexões e outros locks. Isso não muda o
isolamento padrão do Postgres: dois turnos alterando o mesmo registro ainda
obedecem às regras e aos bloqueios do próprio banco.

O grafo também recebe `max_concurrency=1`: ferramentas pedidas juntas pelo
modelo são executadas na ordem da lista, sem disputar qual começa primeiro.
Assim, uma consulta colocada depois de uma escrita consegue ler essa escrita
pendente. O lock protege a conexão; esse limite organiza a execução do turno.
Turnos de requisições diferentes continuam tendo contextos separados. Se o
modelo colocar a consulta antes da escrita, ela consulta o estado anterior;
o programa não inventa nem troca a ordem solicitada pelo modelo.

As chamadas diretas às ferramentas, inclusive pelo servidor MCP existente,
preservam o funcionamento anterior: sem um turno de chat registrado, a própria
ferramenta confirma e fecha. A garantia do juiz é a garantia do fluxo `/chat`;
o MCP continua sendo uma interface direta às ferramentas, sem esse juiz.

## Caminhos que não escolhemos para o Postgres

| Caminho | Como funcionaria aqui | Vantagem real | Custo e motivo da escolha |
| --- | --- | --- | --- |
| Interceptar | Um nó julgaria a ação planejada antes de chamar a ferramenta. | Uma ação já reprovada nem abriria uma escrita SQL. | Seria necessário representar e julgar a ação antecipadamente. O juiz final ainda poderia reprovar a frase depois do SQL; interceptar sozinho não resolve essa recusa tardia mantendo o juiz atual. |
| Adiar | A ferramenta devolveria um plano; o SQL só seria executado depois da aprovação. | A conexão ficaria aberta por menos tempo, sem esperar os modelos e o juiz. | Seria preciso guardar argumentos, executar planos e tratar IDs e leituras de registros ainda inexistentes. A resposta julgada não teria o retorno SQL real. Para várias escritas ainda precisaríamos de uma transação na execução. |
| Compensar | Após a recusa, apagaríamos INSERTs e restauraríamos os valores anteriores de UPDATEs. | As ferramentas poderiam continuar confirmando imediatamente. | Precisaríamos guardar o estado anterior e executar outra escrita, que também pode falhar. Outra sessão poderia ler ou alterar o registro no intervalo; restaurar o valor antigo poderia apagar uma alteração concorrente. |

Transacionar aproveita o comportamento que o banco e as ferramentas já têm,
mantém retornos SQL reais como evidência e evita tornar permanente uma escrita
que depois precisaria ser compensada. Seu custo principal é segurar a conexão
e possíveis bloqueios enquanto espera o veredito.

## Falhas, outros bancos e repetições

- **Recusa normal:** a resposta segura ganha “Nenhuma alteração deste turno
  foi salva”. Os registros SQL voltam ao estado anterior. O monitor registra
  `bloqueado`.
- **Juiz sem chave, timeout ou exceção:** não há aprovação; as escritas são
  desfeitas. A resposta é segura e o monitor registra `erro`. Uma resposta
  inválida do serviço também entra no tratamento de exceção já existente.
  Aceitamos somente os três rótulos previstos e uma probabilidade de 0 a 1;
  valores infinitos, NaN ou booleanos não autorizam um commit. Sem resposta
  final do turno, devolvemos a frase segura sem julgar texto de outro turno
  ou o JSON interno do especialista.
- **Erro SQL ou de argumentos:** nenhuma escrita do turno é confirmada,
  mesmo que a frase candidata tenha sido aprovada. A resposta informa que não
  foi possível confirmar a operação e o monitor registra `erro`.
  Um UPDATE por ID inexistente também é erro: zero linhas alteradas não é
  informado como sucesso nem permite confirmar as demais escritas do turno.
- **Erro ao confirmar o banco:** tentamos rollback e fechamento e informamos
  “Não consegui confirmar a operação. Confira os registros antes de tentar
  novamente”. Se a rede cair durante o commit, a confirmação pode ter chegado
  ao servidor sem que a aplicação receba a resposta. Não repetimos o SQL nem
  afirmamos que nada foi salvo nesse caso.
- **Queda do processo antes do commit:** a conexão se perde e o Postgres
  desfaz a transação não confirmada. A detecção da desconexão pode demorar;
  nesse intervalo podem existir bloqueios, mas não houve um commit de recusa.
- **Queda depois do commit:** o SQL aprovado pode permanecer mesmo sem a
  resposta chegar ao navegador ou ao Mongo. Não há transação distribuída.
- **Repetição do pedido:** cada chamada do chat é um novo turno. Não há
  repetição automática da escrita nem promessa de idempotência entre pedidos
  HTTP. Reenviar uma criação pode criar outra linha; reenviar um UPDATE pode
  aplicar novamente os valores. Diante de uma confirmação incerta, consulte
  os registros antes de reenviar. Não adicionamos uma tabela de idempotência.

**Google Calendar:** não participa do rollback do Postgres. Durante o turno,
`add_google_event` guarda os argumentos e devolve `pendente`. Somente após
aprovação e commit local o programa realiza o envio, sem chamar outro modelo.
A resposta recebe um aviso determinado pelo resultado real da ferramenta.
Sem escrita local, não enviamos ao Google. Na recusa, descartamos a fila.
Se o Google falhar depois do commit, o registro local fica salvo e o usuário
recebe esse aviso; o monitor marca `erro`. Uma queda nesse intervalo pode
deixar apenas o registro local. Não criamos fila durável, tentativa automática
ou compensação no Google. A API externa pode ter recebido um pedido mesmo
quando sua resposta se perde.

**Mongo / `salvar_mensagem`:** mantivemos o histórico depois da conclusão do
grafo. Ele guarda a pergunta anonimizada e a resposta final exibida, inclusive
uma recusa. Histórico de conversa não é uma confirmação de lançamento SQL.
Uma falha no Mongo depois do commit não desfaz o Postgres; o turno termina
como erro. Não colocamos o Mongo dentro da transação SQL.

## Efeito no monitor da Etapa 6

| Medida | Transação compartilhada escolhida | Alternativa: adiar o SQL |
| --- | --- | --- |
| Latência e p95, SLO de 8 s | Mesmas chamadas aos modelos e ao juiz. A conexão e os bloqueios aguardam o veredito; contenção entre turnos pode aumentar o p95. O tempo de commit/rollback e o envio ao Google entram antes de fechar o turno. | O banco seria aberto depois do veredito, reduzindo o tempo de bloqueios. A execução do plano continuaria dentro da latência total; não garante p95 menor em qualquer cenário. |
| Erros, SLO de 5% | Exceção do grafo, falha do juiz, SQL, commit ou Google conta como `erro`. Recusa comum e bloqueio do guardrail de entrada ficam como `bloqueado`, fora da taxa de erro. | Falhar ao executar o plano depois da aprovação também contaria como `erro`; seria necessário substituir a confirmação candidata por uma mensagem verdadeira. |
| Status | `ok` após sucesso; `bloqueado` em recusa comum; `erro` em falha técnica. Um texto seguro causado por timeout não é contado como sucesso. | Mesmas distinções seriam necessárias. Aprovar o plano não provaria que a execução ocorreu. |
| Tokens e custo | Nenhuma chamada nova de modelo; continuamos usando os callbacks e preços do monitor existente. O nó de confirmação não gera tokens. | Um plano determinístico também poderia manter as chamadas. Pedir outra redação ao modelo depois da execução acrescentaria tokens, custo e latência; evitamos essa necessidade. |

Executar as ferramentas do turno em sequência evita resultados que dependem
da corrida entre leitura e escrita. Em contrapartida, ferramentas independentes
que antes poderiam rodar juntas passam a somar seus tempos; isso também pode
aumentar a latência e o p95, sem adicionar chamadas ou tokens por si só.

O custo calculado pelo monitor continua sendo o dos modelos instrumentados;
não mede infraestrutura dos bancos nem atribui tokens/preço à requisição HTTP
do JEV ou ao Google. Os testes controlados abaixo verificam comportamento;
a rodada com serviços reais, registrada ao final, ficou acima do SLO de
latência. Essa amostra não garante o desempenho futuro de produção nem a
precisão do JEV em toda pergunta.

## Evidência e reprodução

Linha de base: `Assessor.zip` original, SHA-256
`341d3748f9d008035fea7bc9740f43c041c39c33a221d80a45d7bc0845f01e7a`.
O código anterior também está no commit
`1b6e64fbb6428245c37104285dc7350846ac915f` já existente no repositório.
A implementação foi validada localmente e sua publicação foi autorizada pelo
grupo em 29/10/2026, preservando o commit anterior como linha de base.

Executamos nove comparações em **Postgres real, usando somente tabelas TEMP**.
Na linha de base foram executadas as ferramentas originais do ZIP, seguidas
do juiz original. Na versão corrigida foi executado o grafo completo. Modelos
e respostas HTTP do JEV foram simulados para controlar a aprovação/recusa.
Não houve chamada real ao JEV, aos modelos ou ao Google nesses testes.
As tabelas temporárias foram descartadas ao fechar a conexão.

| Ferramenta | Antes da correção, juiz recusa | Depois, juiz recusa | Depois, juiz aprova |
| --- | --- | --- | --- |
| `add_transaction` | 0 → 1 linha; 1 commit | 0 → 0 linhas; 0 commits | 0 → 1 linha; 1 commit |
| `update_transaction` | 10 → 99; 1 commit | 10 → 10; 0 commits | 10 → 99; 1 commit |
| `add_event` | 0 → 1 linha; 1 commit | 0 → 0 linhas; 0 commits | 0 → 1 linha; 1 commit |

Cada tentativa tem marcador próprio. O arquivo
[`tests/evidencias_etapa8.json`](tests/evidencias_etapa8.json) contém os nove
marcadores, estados anteriores e posteriores, contagens de commit/rollback e
rótulos `[juiz] sem_apoio noul=0.10` ou `[juiz] apoiada noul=0.95`.
A aprovação não cria uma segunda linha nem executa novamente a ferramenta.

Passaram 45 testes Python e cinco cenários do frontend, além das nove
comparações no Postgres. Os testes automatizados também cobrem várias escritas na mesma transação,
leitura pendente, falhas, argumentos inválidos, turnos simultâneos separados,
Google adiado, histórico final do Mongo e os fluxos anteriores do projeto.

Comandos, a partir da raiz:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/frontend_session.test.js
.venv\Scripts\python.exe tests/verificar_postgres_etapa8.py
```

O terceiro comando precisa do Postgres configurado no `.env` local e da cópia
original em `Downloads/Assessor.zip`; abre somente tabelas temporárias. Os
demais usam os serviços simulados. Para uma demonstração com provedores reais,
use um marcador novo por tentativa e confira o Postgres antes e depois junto
do rótulo `[juiz]`: só a frase exibida pelo chat não comprova o resultado.

## Arquivos criados

As listas comparam os arquivos selecionados para a entrega com o commit de
linha de base `1b6e64fbb6428245c37104285dc7350846ac915f`. Os testes de revisão
já existiam na pasta local, mas não estavam naquela entrega; por isso constam
como arquivos criados em relação ao repositório.

- `decisao_tecnica.md`: decisão, funcionamento, limites e evidência.
- `tests/test_revisao.py`: regressões dos fluxos existentes, com modelos e bancos simulados e mocks adaptados à conexão por turno.
- `tests/frontend_session.test.js`: cinco cenários de regressão do ciclo de sessão no navegador.
- `tests/test_etapa8.py`: regressões da garantia de escrita por turno.
- `tests/verificar_postgres_etapa8.py`: comparação controlada em Postgres real.
- `tests/evidencias_etapa8.json`: resultados das nove comparações, sem segredos.

## Arquivos modificados

- `app/tools/db.py`: conexão por turno, controle de commit/rollback, lock e fila do Google.
- `app/tools/financeiro.py`: escritas e leituras usam a conexão compartilhada; erros, incluindo UPDATE por ID inexistente, impedem confirmar o turno.
- `app/tools/agenda.py`: mesmo controle para `add_event` e `query_events`.
- `app/juiz.py`: publica o veredito interno, valida o contrato da resposta e coleta a resposta do turno atual, preservando a rubrica e o limiar existentes.
- `app/graph.py`: abre o contexto do turno, preserva a ordem das ferramentas, conclui após o juiz e desfaz em exceções.
- `app/tools/calendario_google.py`: adia o efeito externo quando participa do chat.
- `app/prompts/agenda_prompt.py`: inclui `pendente` no campo `google` e alinha as regras e os exemplos ao envio após aprovação e commit, com avisos de sucesso/falha acrescentados pelo programa.
- `app/guardrail.py`: esclarece no prompt do classificador que corrigir os próprios lançamentos por ID é permitido; ajuste de uma linha após um falso bloqueio na validação real.
- `app/observabilidade.py`: distingue recusa comum de falha técnica na conclusão.
- `README.md`: atualiza o estado da Etapa 8 e aponta para a decisão e os testes atuais.

O `.gitignore` é o mesmo da linha de base publicada e exclui credenciais,
ambientes, caches e configurações pessoais. As cópias de segurança e os logs
em `temp/` são arquivos de trabalho, fora dos arquivos da solução. `.env`,
credenciais e tokens permanecem locais. Relatórios antigos da pasta local e
o arquivo vazio `app/tools/connection.py` não fazem parte da seleção de entrega.
O material usado para definir o escopo foi o HTML da Etapa 8, junto dos roteiros
locais das etapas anteriores; não foram acrescentadas fontes externas.

## Revisão de 29/10/2026

Os testes reproduziram e passaram a proteger os casos de nota inválida do
juiz, resposta final vazia, reaproveitamento indevido de resposta anterior e
UPDATE por ID inexistente. Também foi conferida a ordem entre uma escrita e
a leitura seguinte no mesmo turno. Os exemplos da agenda mantêm `pendente`
como estado interno; a resposta preparada não anuncia que ainda está esperando
uma aprovação que já terá terminado quando o usuário receber o texto.

A revisão manteve o núcleo da solução em oito arquivos de código da aplicação,
sem dependências, agentes, tabelas permanentes, rotas ou formatos de API novos.
Na validação real abaixo, houve ainda um ajuste de uma linha em `app/guardrail.py`.
Os relatórios de versões anteriores e `LINHA_BASE_ETAPA7.md` permanecem como
históricos apenas na pasta local; este documento descreve a implementação atual. A validação controlada não
substitui a demonstração com modelos, JEV e Google reais, nem comprova o SLO
de produção. Nenhum commit ou envio ao GitHub foi feito nesta revisão.

## Validação com serviços reais — 29/10/2026

Postgres, MongoDB, Qdrant, Groq, Gemini e JEV foram acessados com a configuração
local. As páginas do servidor aberto, `/health` e `/openapi.json` responderam
HTTP 200. Os testes de conversa usaram os endpoints FastAPI via TestClient no
processo de teste, com os agentes, modelos e serviços reais.

O isolamento foi feito com tabelas TEMP no Postgres, coleções de teste no
Mongo e um `user_id` exclusivo no Qdrant. Os registros pessoais existentes
foram preservados. A limpeza removeu somente documentos e pontos desse usuário;
as coleções Mongo de teste foram mantidas vazias. Não houve criação de eventos
locais nem envio ao Google Calendar nesta rodada; apenas consulta de agenda.

Funcionaram a criação de despesa, a atualização, a consulta de transações,
o saldo diário, a consulta de agenda, o FAQ do PDF, o bloqueio de injeção,
a resposta fora de escopo, o encerramento com resumo no Mongo, a indexação e
recuperação do resumo no Qdrant, a memória em outra sessão, o perfil financeiro
e o isolamento de usuários. O monitor registrou tokens, estimativa de custo,
status e latência, sem turnos ou transações deixados abertos.

Na primeira rodada, a alteração pelo ID foi indevidamente classificada como
acesso a dados internos. Acrescentamos ao prompt do classificador que corrigir
os próprios lançamentos por descrição ou ID é permitido; as verificações de
segredos e de injeção continuam no fluxo. No reteste real, criação e atualização
passaram, cada uma com um commit. Os 45 testes locais também passaram após o ajuste.

Os identificadores abaixo são marcadores únicos dos turnos, emitidos nos logs
`[transacao]`. O registro de criação/atualização tinha a descrição
`VALIDACAO-1A314669-COMPRA`; o teste de recusa usou `VALIDACAO-5FD47E3D-RECUSA`.

| Caso | ID do turno | Estado antes → depois | Rótulo real do juiz | Commits |
| --- | --- | --- | --- | --- |
| Criar despesa | `1eeab3b39a9746e8953a7958df55212d` | Registro ausente → ID 2 com R$ 12 | `[juiz] apoiada noul=0.83` | 1 |
| Atualizar despesa | `c4d93e1b0d9c4b9487f8d97aeffb5dba` | ID 2: R$ 12 → R$ 18 | `[juiz] apoiada noul=0.94` | 1 |
| Recusar com SQL pendente | `199e841d6b984779bb0823277341bc54` | Apenas a linha de base de R$ 10 → mesma linha, sem o INSERT de R$ 7 | `[juiz] sem_apoio noul=0.01` | 0 |

No último caso, somente a resposta candidata enviada ao juiz foi substituída,
no teste, por uma afirmação falsa de R$ 999999. Os modelos anteriores, o SQL e
o JEV eram reais. Foi uma injeção de falha controlada para verificar a recusa:
o programa executou rollback e devolveu a frase segura, sem persistir o INSERT.

Na rodada principal de nove turnos de chat, o monitor registrou p95 de
30.860 ms e média de 16.295 ms. Portanto, o SLO de 8 segundos não foi atingido.
A taxa de erros técnicos registrada foi 0%, mas houve o falso bloqueio descrito
acima: essa métrica sozinha não comprova que toda intenção foi atendida.
Também houve uma falha inicial na chamada de embedding e um timeout ao abrir
uma conexão SQL em outra execução; novas tentativas funcionaram. A disponibilidade
futura dos serviços externos não é garantida por esta validação.

Os logs e os roteiros desta rodada estão em `temp/`, ignorados na entrega,
sem publicação de credenciais. Os dados de teste foram limpos; as contagens
originais do Qdrant permaneceram em 13 trechos de FAQ, sete resumos e três
restrições de perfil. Nenhum commit ou envio ao GitHub foi realizado.

## Diagnóstico de desempenho — 29/10/2026

Ao tentar detalhar a latência, o Gemini retornou `RESOURCE_EXHAUSTED` (HTTP
429): a cota gratuita informada pela API era de 20 requisições por dia e estava
esgotada. A tentativa de consulta terminou em erro após aproximadamente 60
segundos. Os testes reais anteriores consumiram parte dessa cota; não foram
feitas novas chamadas ao Gemini depois da confirmação desse limite.

O fallback existente foi verificado sem chamar o Google: o modelo primário
foi tornado indisponível apenas no processo de teste. O Groq de reserva
respondeu e conseguiu executar o fluxo completo de consulta de saldo, com
Postgres temporário e juiz real. Esse turno levou 17.287 ms; não é uma
comparação de p95 nem prova de melhoria sobre a rodada anterior.

| Etapa na consulta com fallback | Tempo observado |
| --- | --- |
| Guardrail de entrada | 928 ms |
| Roteador | 802 ms |
| Especialista: escolher a ferramenta | 1.174 ms |
| Especialista: produzir o JSON com o resultado | 5.062 ms |
| Orquestrador | 4.922 ms |
| Guardrail de saída | 3.319 ms |
| Juiz JEV | 372 ms |

As chamadas de modelo, somadas, consumiram cerca de 16,2 segundos. Nessa
amostra, a fronteira de commit/rollback e o juiz não foram os principais
responsáveis pelo tempo total.

Foi experimentado `reasoning_effort="low"` somente no processo de teste,
mantendo o primário indisponível e usando o Groq já configurado. Embora a
resposta tenha sido correta e aprovada, esse turno levou 77.818 ms. Uma única
amostra não permite separar efeitos do parâmetro, fila do provedor e rede;
não houve evidência suficiente para recomendar a alteração.

Nenhuma configuração de desempenho foi aplicada ao código entregue. O fluxo,
os modelos, o fallback e as proteções foram mantidos. Uma nova comparação com
o Gemini precisa de cota disponível; qualquer otimização deve ser validada
sem remover etapas exigidas pelo professor e sem tratar timeout menor como
cumprimento do SLO. Os dados exclusivos dos experimentos foram limpos e os
roteiros ficaram somente em `temp/`. Não houve commit ou envio ao GitHub.

## Publicação da entrega

A publicação foi autorizada pelo grupo em 29/10/2026. A seleção final contém
50 arquivos: código, testes, evidências, README, dependências, licença,
`.gitignore` e este documento na raiz. Credenciais, tokens, arquivos pessoais,
caches, relatórios antigos e experimentos de desempenho ficam fora da entrega.
Os registros anteriores de trabalho sem commit descrevem as etapas de validação
local que precederam essa autorização. A linha de base permanece no histórico.
