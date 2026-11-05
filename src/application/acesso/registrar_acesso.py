import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from application.ports.acesso_repository import IAcessoRepository
from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from application.ports.processamento_repository import IProcessamentoRepository
from domain.acesso.acesso_material_personalizado import AcessoMaterialPersonalizado
from domain.acesso.status_leitura import StatusLeitura
from domain.shared.exceptions import EntradaInvalidaError, RecursoNaoEncontradoError

logger = logging.getLogger(__name__)


@dataclass
class RegistrarAcessoInput:
    material_personalizado_id: UUID
    aluno_id: UUID
    tempo_leitura_incremento_segundos: int
    porcentagem_leitura: float
    download_realizado: bool


@dataclass
class RegistrarAcessoResultado:
    acesso: AcessoMaterialPersonalizado
    criado: bool


class RegistrarAcessoUseCase:
    """PUT /materiais-personalizados/{id}/acesso."""

    def __init__(
        self,
        processamento_repositorio: IProcessamentoRepository,
        material_personalizado_repositorio: IMaterialPersonalizadoRepository,
        acesso_repositorio: IAcessoRepository,
    ) -> None:
        self._processamento_repositorio = processamento_repositorio
        self._material_personalizado_repositorio = material_personalizado_repositorio
        self._acesso_repositorio = acesso_repositorio

    async def executar(self, dados: RegistrarAcessoInput) -> RegistrarAcessoResultado:
        material = await self._material_personalizado_repositorio.obter_por_id(
            dados.material_personalizado_id
        )
        if material is None:
            raise RecursoNaoEncontradoError(
                code="MATERIAL_PERSONALIZADO_NAO_ENCONTRADO",
                message="Material personalizado não encontrado.",
                details={"material_personalizado_id": str(dados.material_personalizado_id)},
            )

        processamento = await self._processamento_repositorio.obter_por_id(
            material.processamento_id
        )
        if processamento is None:
            # Defensivo: processamento_id é FK NOT NULL (ondelete=RESTRICT), chegar
            # aqui indica inconsistência de dados, não ausência documentada.
            logger.warning(
                "Material personalizado %s referencia processamento %s inexistente.",
                dados.material_personalizado_id,
                material.processamento_id,
            )
            raise RecursoNaoEncontradoError(
                code="PROCESSAMENTO_NAO_ENCONTRADO",
                message="Processamento não encontrado.",
                details={"processamento_id": str(material.processamento_id)},
            )

        if processamento.aluno_id != dados.aluno_id:
            # aluno_id do corpo só é aceito se corresponder ao
            # dono do Processamento que originou o material (proteção BOLA/IDOR).
            logger.warning(
                "Tentativa de registrar acesso com aluno_id %s divergente do "
                "dono %s do material personalizado %s (possível BOLA/IDOR).",
                dados.aluno_id,
                processamento.aluno_id,
                dados.material_personalizado_id,
            )
            raise EntradaInvalidaError(
                code="ALUNO_ID_INVALIDO",
                message="aluno_id não corresponde ao aluno do processamento de origem.",
                details={
                    "aluno_id": str(dados.aluno_id),
                    "material_personalizado_id": str(dados.material_personalizado_id),
                },
            )

        existente = await self._acesso_repositorio.obter_por_material_personalizado_id_e_aluno_id(
            material_personalizado_id=dados.material_personalizado_id,
            aluno_id=dados.aluno_id,
        )

        if existente is None:
            agora = datetime.now(UTC)
            acesso = AcessoMaterialPersonalizado(
                id=uuid4(),
                material_personalizado_id=dados.material_personalizado_id,
                aluno_id=dados.aluno_id,
                data_primeiro_acesso=agora,
                data_ultimo_acesso=agora,
                tempo_total_leitura=0,
                quantidade_acessos=0,
                porcentagem_leitura=0.0,
                download_realizado=False,
                status_leitura=StatusLeitura.NAO_INICIADO,
            )
            acesso.registrar_acesso(
                tempo_leitura_incremento_segundos=dados.tempo_leitura_incremento_segundos,
                porcentagem_leitura=dados.porcentagem_leitura,
                download_realizado=dados.download_realizado,
            )
            await self._acesso_repositorio.adicionar(acesso)
            return RegistrarAcessoResultado(acesso=acesso, criado=True)

        existente.registrar_acesso(
            tempo_leitura_incremento_segundos=dados.tempo_leitura_incremento_segundos,
            porcentagem_leitura=dados.porcentagem_leitura,
            download_realizado=dados.download_realizado,
        )
        await self._acesso_repositorio.atualizar(existente)
        return RegistrarAcessoResultado(acesso=existente, criado=False)
