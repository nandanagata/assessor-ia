# Assessor — primeira entrega

Projeto com o juiz da Etapa 7, antes da implementação da prova da Etapa 8.
As tools de escrita ainda confirmam a operação antes do veredito do juiz.

## Preparar e executar

Crie seu ambiente virtual e instale as dependências:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Configure localmente um arquivo `.env` na raiz com `GEMINI_API_KEY`,
`GROQ_API_KEY`, `SQL_URL`, `MONGODB_URI`, `QDRANT_URL`, `QDRANT_API_KEY` e
`TYPESAFE_API_KEY`. Credenciais e tokens não acompanham esta entrega.

Disponibilize PostgreSQL, MongoDB e Qdrant conforme os roteiros. Prepare as
collections e indexe o PDF do FAQ uma vez com:

```powershell
.venv\Scripts\python.exe -m app.ingest_faq
```

Inicie a aplicação:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Acesse `http://localhost:8000/`. As telas adicionais ficam em `/perfil.html`
e `/monitor.html`. A documentação da API está em `/docs`.

O servidor MCP local tem ponto de entrada em `app/mcp_server.py`. A
configuração do editor deve ser criada na máquina em que ele será usado.

Para o Google Calendar, disponibilize localmente o arquivo OAuth da aula
como `gcp-oauth.keys.json` na raiz e autentique a conta:

```powershell
.venv\Scripts\python.exe -c "from app.tools.calendario_google import autenticar; print(autenticar())"
```

A integração com o Google usa `GOOGLE_OAUTH_CREDENTIALS` e
`GOOGLE_CALENDAR_MCP_URL`, com padrões em `app/config/config.py`.

## Encerramento de sessão

O resumo é salvo no MongoDB antes de indexar no Qdrant. Se o índice estiver
indisponível, a sessão pode ser encerrada com o resumo preservado. O terminal
registra a falha, e a consulta de memória pode usar os resumos recentes do
MongoDB. A indexação que falhou não é refeita automaticamente.
Se a geração ou a gravação do resumo no MongoDB falhar, a conversa permanece
aberta e a API informa que é necessário tentar novamente.
