from uuid import UUID

from application.ports.acesso_repository import IAcessoRepository
from domain.acesso.acesso_material_personalizado import AcessoMaterialPersonalizado
from domain.shared.exceptions import RecursoNaoEncontradoError


class ConsultarAcessoUseCase:
    """Documento 3 §4.7 — GET /materiais-personalizados/{id}/acesso. O recurso só
    existe a partir do primeiro PUT; antes disso, 404 (não há aluno_id no path
    ou query desta rota para diferenciar "material não existe" de "sem acesso
    ainda" — a documentação trata os dois casos como o mesmo 404)."""

    def __init__(self, acesso_repositorio: IAcessoRepository) -> None:
        self._acesso_repositorio = acesso_repositorio

    async def executar(self, material_personalizado_id: UUID) -> AcessoMaterialPersonalizado:
        acesso = await self._acesso_repositorio.obter_por_material_personalizado_id(
            material_personalizado_id
        )
        if acesso is None:
            raise RecursoNaoEncontradoError(
                code="ACESSO_NAO_ENCONTRADO",
                message="Ainda não houve nenhum acesso a este material.",
                details={"material_personalizado_id": str(material_personalizado_id)},
            )
        return acesso
