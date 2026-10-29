# Lumi

Lumi é um assessor de IA acadêmico desenvolvido com FastAPI, LangChain/LangGraph, MongoDB, PostgreSQL e um frontend simples em HTML/CSS/JavaScript.

## 1. Preparar o ambiente

Na raiz do projeto, crie o ambiente e instale as dependências:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Configurar o `.env`

O projeto espera um arquivo `.env` na raiz com estas variáveis:

```env
GEMINI_API_KEY=...
GROQ_API_KEY=...
SQL_URL=...
MONGODB_URI=...
QDRANT_URL=...
QDRANT_API_KEY=...
GOOGLE_OAUTH_CREDENTIALS=gcp-oauth.keys.json
GOOGLE_CALENDAR_MCP_URL=https://calendarmcp.googleapis.com/mcp/v1
TYPESAFE_API_KEY=...
```

Não versione nem compartilhe os valores reais dessas variáveis.

`TYPESAFE_API_KEY` é a chave do juiz da Etapa 7. Ela fica fora de
`OBRIGATORIAS`, como no roteiro: sem chave, com erro de rede ou com veredito
insuficiente, o juiz devolve “Não tenho evidência para afirmar isso.”

## 3. Serviços necessários

Antes de iniciar a aplicação, deixe disponíveis:

- MongoDB, usado para sessões, mensagens e memória de longo prazo;
- PostgreSQL, usado pelas tools financeiras e de agenda (tabela `events` do roteiro);
- Qdrant, usado pela memória semântica e pelo FAQ;
- acesso às APIs dos modelos configurados no `.env`.

Na primeira preparação do FAQ no Qdrant, execute uma vez:

```bash
python -m app.ingest_faq
```

## 4. Executar

A partir da raiz do projeto:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Depois acesse:

- aplicação: `http://localhost:8000/`
- documentação FastAPI: `http://localhost:8000/docs`
- verificação de configuração: `http://localhost:8000/health`
- perfil financeiro: `http://localhost:8000/perfil.html`
- painel de monitoramento: `http://localhost:8000/monitor.html`

`/health` verifica configuração e o arquivo do FAQ; não testa a conexão com
os serviços. `/monitor` fornece os números usados pelo painel da Etapa 6.

## 5. Ciclo de sessão

O frontend mantém um `session_id` durante a conversa. Ao clicar em **Nova sessão**, ele encerra explicitamente a conversa anterior pela API, permitindo que o MongoDB grave o resumo antes de gerar um novo identificador.

Se o encerramento falhar, a conversa e seu identificador são mantidos para
permitir nova tentativa. O botão fica indisponível enquanto o chat responde.

O resumo é salvo no MongoDB antes da indexação no Qdrant. Se o Qdrant ou a
geração do embedding falhar, a sessão é encerrada com o resumo preservado e
um aviso no terminal. A consulta de memória usa os resumos recentes do MongoDB
quando a busca semântica está indisponível. A indexação que falhou não é
refeita automaticamente; a busca por similaridade depende do índice remoto.
Se não for possível gerar ou salvar o resumo no MongoDB, a API retorna uma
mensagem tratada e o frontend mantém a sessão para nova tentativa.

## 6. MCP e Google Calendar (Etapas 5 e 5.2)

O servidor MCP em `app/mcp_server.py` publica as cinco tools financeiras e as duas de agenda. Ele chama as tools LangChain existentes com `.invoke()`; o chat HTTP continua usando o grafo diretamente. A configuração `.cursor/mcp.json` é pessoal e fica fora da entrega. Para usar a integração em outra máquina, crie a configuração local com os caminhos absolutos de `command` e `args`, conforme o roteiro da Etapa 5.

Para preparar o ambiente usado pelo Cursor, instale as dependências nele:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

No Cursor em modo Agent, habilite `assessor-financeiro` nas integrações MCP. O servidor usa stdio; iniciá-lo manualmente deixa o processo aguardando mensagens do cliente. Confira se `tools/list` mostra `total_balance`, `daily_balance`, `query_transactions`, `add_transaction`, `update_transaction`, `query_events` e `add_event`.

O cliente do Google está em `app/tools/calendario_google.py`. O arquivo OAuth Desktop distribuído pelo professor fica na raiz como `gcp-oauth.keys.json` e está ignorado pelo Git. Para vincular **sua** conta Google, rode na raiz:

```powershell
.venv\Scripts\python.exe -c "from app.tools.calendario_google import autenticar; print(autenticar())"
```

O navegador abre para você escolher o Gmail e autorizar. O token fica em `google-calendar.token.json`, também ignorado pelo Git. A tool `add_google_event` tenta o MCP oficial e usa a Calendar API com o mesmo token quando o serviço MCP não está habilitado no projeto Cloud, como indicado no roteiro. No chat, o envio ao Google aguarda a aprovação do juiz e o commit no Postgres. Se esse envio falhar, a resposta informa que o registro local foi salvo.

Este fluxo OAuth Desktop é o recorte individual da aula: o token pertence à conta autenticada **nesta instalação**. Para oferecer calendários diferentes a vários usuários no mesmo servidor, seria necessário o fluxo Web com tokens por usuário descrito no roteiro.

## 7. Etapa 8: confirmação da escrita após o juiz

Financeiro e agenda passam por orquestrador, guardrail de saída e juiz, nessa
ordem. O FAQ usa somente os trechos do PDF e vai direto para o juiz. Depois do
veredito, o histórico guarda apenas a pergunta e a resposta final do turno.

O juiz preserva a resposta original quando `choice=apoiada` e `noul>=0.70`.
Nos demais casos, usa a frase fixa prevista nos slides.

`add_transaction`, `update_transaction` e `add_event` compartilham uma transação
por turno. As ferramentas executam o SQL, mas o commit espera o veredito.
Aprovação confirma uma vez; recusa ou falha antes da confirmação desfaz as
escritas do turno. As consultas continuam disponíveis na mesma conexão.

A decisão, as alternativas, os limites e os testes estão em
[`decisao_tecnica.md`](decisao_tecnica.md). A cópia anterior à correção foi
preservada no commit de referência citado nesse documento.

## 8. Conferência local dos roteiros

Execute os testes com as dependências já instaladas:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/frontend_session.test.js
.venv\Scripts\python.exe -m compileall -q app tests
node --check app/frontend/app.js
node --check app/frontend/perfil.js
```

Os testes usam modelos simulados, MongoDB simulado e Qdrant em memória.
As requisições HTTP externas e o Postgres real ficam bloqueados durante os
testes. Não é preciso fornecer chaves reais nem cadastrar eventos ou gastos.
O teste de JavaScript usa apenas os módulos que acompanham o Node.js. Os
testes `test_etapa8.py` conferem a confirmação/recusa e as falhas do turno.

Para comparar as ferramentas originais com a correção em tabelas temporárias
do Postgres real, veja o comando e os requisitos em `decisao_tecnica.md`.

Consulte `decisao_tecnica.md` para a relação de alterações, as evidências e os
limites da validação. Os relatórios de versões anteriores são históricos
locais e não fazem parte desta entrega.

## 9. Entrega da Etapa 8

O roteiro pede a correção no repositório do grupo e `decisao_tecnica.md` na
raiz, com a justificativa e as listas de arquivos criados e modificados.
Preserve o commit anterior para permitir a comparação. O HTML da prática
não especifica um novo ZIP, PDF, vídeo ou canal de envio ao professor.

A seleção de entrega contém `app/`, `tests/`, `.gitignore`, `README.md`,
`requirements.txt`, `LICENSE` e `decisao_tecnica.md`. O arquivo vazio
`app/tools/connection.py` fica fora dessa seleção. Não inclua `.env`, chaves,
tokens, `.venv`, caches, `temp/`, `.cursor/` ou relatórios antigos locais.

A publicação desta versão foi autorizada pelo grupo. A linha de base deve
permanecer no histórico. A cota do Gemini estava esgotada no último diagnóstico; a demonstração ao vivo
precisa de credenciais com cota disponível e dos serviços ativos. A latência
observada acima do SLO e o limite dos testes do Google estão documentados.
