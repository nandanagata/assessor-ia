"""Persistência e consulta interna do perfil financeiro."""

import uuid

from qdrant_client import models

from app.schemas import PerfilRequest
from app.tools.db import db
from app.vectorstore import (
    COLLECTION_PERFIL,
    EMBEDDING_DIM,
    gerar_embedding,
    gerar_embeddings_batch,
    qdrant,
)


col_perfis = db["perfis"]
col_perfis.create_index("user_id", unique=True)


def _garantir_collection_perfil() -> None:
    """Garante a collection e o índice usado nos filtros por usuário."""
    if not qdrant.collection_exists(COLLECTION_PERFIL):
        qdrant.create_collection(
            collection_name=COLLECTION_PERFIL,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIM,
                distance=models.Distance.COSINE,
            ),
        )

    # O Qdrant Cloud exige um índice keyword para filtrar os pontos por user_id.
    # Essa verificação também corrige collections criadas por uma execução anterior.
    info = qdrant.get_collection(COLLECTION_PERFIL)
    if "user_id" not in (info.payload_schema or {}):
        qdrant.create_payload_index(
            collection_name=COLLECTION_PERFIL,
            field_name="user_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )


def salvar_perfil(perfil: PerfilRequest) -> dict:
    """Atualiza os dados fixos no MongoDB e substitui as restrições no Qdrant."""
    dados = perfil.model_dump()
    restricoes = dados.pop("restricoes")

    _garantir_collection_perfil()
    vetores = gerar_embeddings_batch(restricoes)

    col_perfis.update_one(
        {"user_id": perfil.user_id},
        {"$set": dados},
        upsert=True,
    )

    filtro_usuario = models.Filter(
        must=[
            models.FieldCondition(
                key="user_id",
                match=models.MatchValue(value=perfil.user_id),
            )
        ]
    )
    qdrant.delete(
        collection_name=COLLECTION_PERFIL,
        points_selector=models.FilterSelector(filter=filtro_usuario),
        wait=True,
    )

    pontos = [
        models.PointStruct(
            id=str(uuid.uuid4()),
            vector=vetor,
            payload={"user_id": perfil.user_id, "restricao": restricao},
        )
        for restricao, vetor in zip(restricoes, vetores)
    ]
    qdrant.upsert(
        collection_name=COLLECTION_PERFIL,
        points=pontos,
        wait=True,
    )

    return perfil.model_dump()


def buscar_perfil(user_id: str) -> dict | None:
    """Consulta internamente os dados estruturados do perfil pelo usuário."""
    return col_perfis.find_one({"user_id": user_id}, {"_id": 0})


def buscar_restricoes(user_id: str, pergunta: str, limite: int = 5) -> list[str]:
    """Busca semanticamente somente as restrições pertencentes ao usuário."""
    _garantir_collection_perfil()
    vetor = gerar_embedding(pergunta)
    resultados = qdrant.query_points(
        collection_name=COLLECTION_PERFIL,
        query=vetor,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="user_id",
                    match=models.MatchValue(value=user_id),
                )
            ]
        ),
        limit=limite,
    )
    return [
        ponto.payload["restricao"]
        for ponto in resultados.points
        if ponto.payload and ponto.payload.get("restricao")
    ]
