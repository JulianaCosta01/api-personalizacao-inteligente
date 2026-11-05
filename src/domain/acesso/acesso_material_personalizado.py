from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from domain.acesso.status_leitura import StatusLeitura


def _derivar_status_leitura(porcentagem_leitura: float) -> StatusLeitura:
    # status_leitura é sempre derivado no servidor a partir de
    # porcentagem_leitura, nunca aceito diretamente do cliente.
    if porcentagem_leitura <= 0:
        return StatusLeitura.NAO_INICIADO
    if porcentagem_leitura >= 1:
        return StatusLeitura.CONCLUIDO
    return StatusLeitura.EM_ANDAMENTO


@dataclass
class AcessoMaterialPersonalizado:
    """Progresso de leitura de um aluno sobre um material personalizado.

    Uma linha por par (material_personalizado_id, aluno_id). Quem decide entre criar e
    atualizar é a camada de Application.
    """

    id: UUID
    material_personalizado_id: UUID
    aluno_id: UUID
    data_primeiro_acesso: datetime
    data_ultimo_acesso: datetime
    tempo_total_leitura: int
    quantidade_acessos: int
    porcentagem_leitura: float
    download_realizado: bool
    status_leitura: StatusLeitura

    def registrar_acesso(
        self,
        tempo_leitura_incremento_segundos: int,
        porcentagem_leitura: float,
        download_realizado: bool,
    ) -> None:
        # quantidade_acessos incrementa, tempo_total_leitura
        # acumula, e status_leitura é derivado da nova porcentagem_leitura.
        self.data_ultimo_acesso = datetime.now(UTC)
        self.quantidade_acessos += 1
        self.tempo_total_leitura += tempo_leitura_incremento_segundos
        self.porcentagem_leitura = porcentagem_leitura
        self.download_realizado = download_realizado
        self.status_leitura = _derivar_status_leitura(porcentagem_leitura)
