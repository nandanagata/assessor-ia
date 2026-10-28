from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ChatRequest(BaseModel):
    """O que o navegador envia no POST /chat."""

    session_id: str = Field(
        ...,
        min_length=1,
        description="Identifica a conversa (UUID gerado pelo front a cada sessão).",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    user_id: str = Field(
        default="usuario_teste",
        min_length=1,
        description="Identifica o usuário de forma estável entre sessões. "
                    "É o que permite a memória de longo prazo funcionar.",
        examples=["usuario_teste"],
    )
    pergunta: str = Field(
        ...,
        min_length=1,
        description="A mensagem do usuário — o que antes vinha do input().",
        examples=["gastei 50 reais no mercado hoje"],
    )

    @field_validator("session_id", "user_id", "pergunta")
    @classmethod
    def validar_texto(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("O campo não pode ficar vazio.")
        return valor


class ChatResponse(BaseModel):
    """O que a API devolve no POST /chat."""
    resposta:         str
    agentes_chamados: list[str] = Field(default_factory=list)


class PerfilRequest(BaseModel):
    """Dados enviados pela tela Perfil no POST /perfil."""

    user_id: str = Field(..., min_length=1)
    renda_mensal: float = Field(..., gt=0)
    gasto_fixo_mensal: float = Field(..., ge=0)
    horizonte_meses: int = Field(..., ge=1, le=120)
    perfil_investidor: Literal["conservador", "moderado", "arrojado"]
    restricoes: list[str] = Field(..., min_length=1, max_length=5)

    @field_validator("restricoes")
    @classmethod
    def validar_restricoes(cls, restricoes: list[str]) -> list[str]:
        restricoes_limpas = [restricao.strip() for restricao in restricoes]
        if any(not restricao for restricao in restricoes_limpas):
            raise ValueError("Cada restrição precisa conter uma frase.")
        return restricoes_limpas

    @model_validator(mode="after")
    def validar_renda_e_gasto(self):
        if self.gasto_fixo_mensal >= self.renda_mensal:
            raise ValueError("O gasto fixo mensal precisa ser menor que a renda mensal.")
        return self


class SessionResponse(BaseModel):
    """Ainda não é usado — é do Passo 6 da Etapa 3."""
    session_id: str
    resumo:     str | None = None
