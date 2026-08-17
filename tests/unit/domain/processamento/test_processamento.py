from datetime import UTC, datetime
from uuid import uuid4

from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento


def _processamento() -> Processamento:
    return Processamento(
        id=uuid4(),
        aluno_id=uuid4(),
        material_didatico_id=uuid4(),
        perfil_id=uuid4(),
        status=StatusProcessamento.PENDENTE,
        modelo_ia=None,
        data_criacao=datetime.now(UTC),
        inicio=None,
        fim=None,
        erro=None,
    )


def test_criado_com_status_pendente_e_campos_de_execucao_nulos() -> None:
    processamento = _processamento()

    assert processamento.status == StatusProcessamento.PENDENTE
    assert processamento.inicio is None
    assert processamento.fim is None
    assert processamento.erro is None


def test_marcar_como_erro_atualiza_status_erro_e_fim() -> None:
    processamento = _processamento()

    processamento.marcar_como_erro("falha ao publicar na fila")

    assert processamento.status == StatusProcessamento.ERRO
    assert processamento.erro == "falha ao publicar na fila"
    assert processamento.fim is not None


def test_marcar_como_erro_preserva_id_aluno_material_e_perfil() -> None:
    processamento = _processamento()
    id_original = processamento.id
    aluno_id_original = processamento.aluno_id
    material_id_original = processamento.material_didatico_id
    perfil_id_original = processamento.perfil_id

    processamento.marcar_como_erro("falha")

    assert processamento.id == id_original
    assert processamento.aluno_id == aluno_id_original
    assert processamento.material_didatico_id == material_id_original
    assert processamento.perfil_id == perfil_id_original


def test_marcar_como_concluido_atualiza_status_e_fim() -> None:
    processamento = _processamento()

    processamento.marcar_como_concluido()

    assert processamento.status == StatusProcessamento.CONCLUIDO
    assert processamento.fim is not None
    assert processamento.erro is None
