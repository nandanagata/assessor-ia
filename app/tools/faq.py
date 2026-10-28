from langchain.tools import tool
from qdrant_client.http.exceptions import ResponseHandlingException
from app.vectorstore import qdrant, gerar_embedding, COLLECTION_FAQ


class ConsultaFAQIndisponivel(RuntimeError):
    """A conexão com o banco do FAQ não pôde ser concluída."""


@tool
def faq_retriever(question: str) -> str:
    """Busca no FAQ oficial os trechos mais relevantes para responder a pergunta."""
    vetor = gerar_embedding(question)

    try:
        resultados = qdrant.query_points(
            collection_name=COLLECTION_FAQ,
            query=vetor,
            limit=6,
        )
    except ResponseHandlingException as erro:
        raise ConsultaFAQIndisponivel(
            "Não foi possível consultar o FAQ porque a conexão com o Qdrant falhou. "
            "Verifique se o cluster está ativo e se a rede permite o acesso."
        ) from erro

    if not resultados.points:
        return "Nenhum trecho relevante encontrado no FAQ."

    return "\n\n".join(
        ponto.payload["page_content"] for ponto in resultados.points
    )
