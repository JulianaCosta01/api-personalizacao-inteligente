import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from application.ports.aluno_repository import IAlunoRepository
from application.ports.llm import ILLMPort
from application.ports.perfil_repository import IPerfilRepository
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from domain.shared.exceptions import RecursoNaoEncontradoError

logger = logging.getLogger(__name__)


@dataclass
class CriarPerfilInput:
    aluno_id: UUID
    estilo_processamento: EstiloProcessamento
    percepcao: Percepcao
    entrada: Entrada
    compreensao: Compreensao


class CriarPerfilUseCase:
    def __init__(
        self,
        aluno_repositorio: IAlunoRepository,
        perfil_repositorio: IPerfilRepository,
        llm: ILLMPort,
    ) -> None:
        self._aluno_repositorio = aluno_repositorio
        self._perfil_repositorio = perfil_repositorio
        self._llm = llm

    async def executar(self, dados: CriarPerfilInput) -> Perfil:
        aluno = await self._aluno_repositorio.obter_por_id(dados.aluno_id)
        if aluno is None:
            raise RecursoNaoEncontradoError(
                code="ALUNO_NAO_ENCONTRADO",
                message="Aluno não encontrado.",
                details={"aluno_id": str(dados.aluno_id)},
            )

        perfil = Perfil(
            id=uuid4(),
            aluno_id=dados.aluno_id,
            estilo_processamento=dados.estilo_processamento,
            percepcao=dados.percepcao,
            entrada=dados.entrada,
            compreensao=dados.compreensao,
            descricao_llm=None,
            data_atualizacao=datetime.now(UTC),
        )
        await self._perfil_repositorio.adicionar(perfil)

        descricao = await self._gerar_descricao(perfil)
        if descricao is not None:
            perfil.descricao_llm = descricao
            await self._perfil_repositorio.atualizar(perfil)

        return perfil

    async def _gerar_descricao(self, perfil: Perfil) -> str | None:
        # Falha ou timeout do Gemini nunca impede a criação do Perfil: as
        # quatro dimensões já estão persistidas nesse ponto.
        try:
            return await self._llm.gerar_descricao_perfil(
                perfil.estilo_processamento,
                perfil.percepcao,
                perfil.entrada,
                perfil.compreensao,
            )
        except Exception:
            logger.exception("Falha ao gerar descricao_llm do Perfil %s", perfil.id)
            return None
