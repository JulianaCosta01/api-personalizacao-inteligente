from datetime import UTC, datetime
from uuid import uuid4

from domain.log.log_interacao import LogInteracao


def _log(**overrides: object) -> LogInteracao:
    valores: dict[str, object] = {
        "id": uuid4(),
        "aluno_id": uuid4(),
        "processamento_id": uuid4(),
        "acao": "abertura_material_personalizado",
        "descricao": None,
        "timestamp": datetime.now(UTC),
    }
    valores.update(overrides)
    return LogInteracao(**valores)  # type: ignore[arg-type]


def test_criado_com_os_campos_informados() -> None:
    aluno_id = uuid4()
    processamento_id = uuid4()

    log = _log(aluno_id=aluno_id, processamento_id=processamento_id, acao="fim_processamento")

    assert log.aluno_id == aluno_id
    assert log.processamento_id == processamento_id
    assert log.acao == "fim_processamento"


def test_processamento_id_e_descricao_aceitam_none() -> None:
    log = _log(processamento_id=None, descricao=None)

    assert log.processamento_id is None
    assert log.descricao is None


def test_descricao_aceita_texto_livre() -> None:
    log = _log(descricao="aluno abriu o material pela primeira vez")

    assert log.descricao == "aluno abriu o material pela primeira vez"
