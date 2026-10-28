from fastapi import FastAPI
from app.routes.chat import router as chat_router
from app.routes.sessions import router as sessions_router
from app.routes.perfil import router as perfil_router
from app.routes.monitor import router as monitor_router
from app.config.config import validar_config
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config.config import FRONTEND_DIR

for _problema in validar_config():
    print(f"[config] ATENÇÃO: {_problema}")

app = FastAPI(
    title="Lumi - Assessor IA",
    description="Aplicativo de assessoria financeira e agenda com IA",
    version="0.1.0",
)

# Configurações de Segurança
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(perfil_router)
app.include_router(monitor_router)

@app.get("/health", tags=["infra"])
def health() -> dict:
    problemas = validar_config()
    return {
        "status": "ok" if not problemas else "atencao",
        "problemas_de_configuracao": problemas,
    }

# Conexão com o frontend
if (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/", tags=["infra"])
    def raiz() -> dict:
        return {
            "mensagem": "API já iniciada. Frontend não encontrado. Acesse /docs para a documentação da API.",
        }
