from fastapi import APIRouter

from app.perfil import salvar_perfil
from app.schemas import PerfilRequest


router = APIRouter(tags=["perfil"])


@router.post("/perfil", response_model=PerfilRequest)
def cadastrar_perfil(perfil: PerfilRequest) -> PerfilRequest:
    """Salva ou atualiza o perfil enviado pela tela Perfil."""
    return PerfilRequest(**salvar_perfil(perfil))
