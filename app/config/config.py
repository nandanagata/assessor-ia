import os
from pathlib import Path
from dotenv import load_dotenv

# BASE_DIR aponta para a raiz do projeto. Como este arquivo está em
# app/config/, precisamos subir três níveis a partir do próprio arquivo.
# Assim os caminhos não dependem da pasta de onde o uvicorn foi executado.
BASE_DIR     = Path(__file__).resolve().parents[2]
DATA_DIR     = BASE_DIR / "app" / "data"
FRONTEND_DIR = BASE_DIR / "app" / "frontend"

FAQ_PDF_PATH = DATA_DIR / "Lumi_Seu_Parceiro_para_Financas_e_Compromissos.pdf"

load_dotenv(BASE_DIR / ".env")          # o único load_dotenv() do projeto

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
SQL_URL   = os.getenv("SQL_URL")
MONGODB_URI    = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
GOOGLE_OAUTH_CREDENTIALS = os.getenv(
    "GOOGLE_OAUTH_CREDENTIALS", str(BASE_DIR / "gcp-oauth.keys.json")
)
GOOGLE_CALENDAR_MCP_URL = os.getenv(
    "GOOGLE_CALENDAR_MCP_URL", "https://calendarmcp.googleapis.com/mcp/v1"
)
GOOGLE_CALENDAR_ACCESS_TOKEN = os.getenv("GOOGLE_CALENDAR_ACCESS_TOKEN")
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")

OBRIGATORIAS = {
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "GROQ_API_KEY":   GROQ_API_KEY,
    "SQL_URL":   SQL_URL,
    "MONGODB_URI":    MONGODB_URI,
    "QDRANT_URL": QDRANT_URL,
    "QDRANT_API_KEY": QDRANT_API_KEY,
}


def validar_config() -> list[str]:
    """Devolve a lista de problemas de configuração (vazia = tudo certo)."""
    problemas = []
    for nome, valor in OBRIGATORIAS.items():
        if not valor:
            problemas.append(f"Variável ausente no .env: {nome}")
    if not FAQ_PDF_PATH.exists():
        problemas.append(f"PDF do FAQ não encontrado em: {FAQ_PDF_PATH}")
    return problemas
