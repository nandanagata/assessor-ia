import logging

from fastapi import APIRouter, HTTPException
from app.schemas import ChatRequest, ChatResponse
from app.graph import executar_fluxo_assessor
from app.tools.faq import ConsultaFAQIndisponivel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def conversar(requisicao: ChatRequest) -> ChatResponse:
    """Uma mensagem do usuário, uma resposta do assessor."""
    try:
        resposta = executar_fluxo_assessor(
            requisicao.pergunta, requisicao.session_id, requisicao.user_id
        )
    except ConsultaFAQIndisponivel as erro:
        logger.exception("Falha de conexão ao consultar o FAQ")
        raise HTTPException(status_code=503, detail=str(erro)) from erro
    return ChatResponse(resposta=resposta)
