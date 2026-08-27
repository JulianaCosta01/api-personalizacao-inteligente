from datetime import UTC, datetime
from uuid import uuid4

from domain.acesso.acesso_material_personalizado import AcessoMaterialPersonalizado
from domain.acesso.status_leitura import StatusLeitura


def _acesso(**overrides: object) -> AcessoMaterialPersonalizado:
    agora = datetime.now(UTC)
    valores: dict[str, object] = {
        "id": uuid4(),
        "material_personalizado_id": uuid4(),
        "aluno_id": uuid4(),
        "data_primeiro_acesso": agora,
        "data_ultimo_acesso": agora,
        "tempo_total_leitura": 0,
        "quantidade_acessos": 0,
        "porcentagem_leitura": 0.0,
        "download_realizado": False,
        "status_leitura": StatusLeitura.NAO_INICIADO,
    }
    valores.update(overrides)
    return AcessoMaterialPersonalizado(**valores)  # type: ignore[arg-type]


def test_criado_com_estado_inicial_zerado() -> None:
    acesso = _acesso()

    assert acesso.quantidade_acessos == 0
    assert acesso.tempo_total_leitura == 0
    assert acesso.status_leitura == StatusLeitura.NAO_INICIADO


def test_registrar_acesso_incrementa_quantidade_de_acessos() -> None:
    acesso = _acesso(quantidade_acessos=2)

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=30, porcentagem_leitura=0.5, download_realizado=False
    )

    assert acesso.quantidade_acessos == 3


def test_registrar_acesso_acumula_tempo_total_de_leitura() -> None:
    acesso = _acesso(tempo_total_leitura=120)

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=45, porcentagem_leitura=0.5, download_realizado=False
    )

    assert acesso.tempo_total_leitura == 165


def test_registrar_acesso_sobrescreve_porcentagem_e_download() -> None:
    acesso = _acesso(porcentagem_leitura=0.3, download_realizado=False)

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=10, porcentagem_leitura=0.78, download_realizado=True
    )

    assert acesso.porcentagem_leitura == 0.78
    assert acesso.download_realizado is True


def test_registrar_acesso_atualiza_data_do_ultimo_acesso() -> None:
    acesso = _acesso(data_ultimo_acesso=datetime(2020, 1, 1, tzinfo=UTC))

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=10, porcentagem_leitura=0.1, download_realizado=False
    )

    assert acesso.data_ultimo_acesso > datetime(2020, 1, 1, tzinfo=UTC)


def test_registrar_acesso_preserva_data_do_primeiro_acesso() -> None:
    primeiro_acesso = datetime(2020, 1, 1, tzinfo=UTC)
    acesso = _acesso(data_primeiro_acesso=primeiro_acesso)

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=10, porcentagem_leitura=0.1, download_realizado=False
    )

    assert acesso.data_primeiro_acesso == primeiro_acesso


def test_registrar_acesso_com_porcentagem_zero_deriva_nao_iniciado() -> None:
    acesso = _acesso()

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=0, porcentagem_leitura=0.0, download_realizado=False
    )

    assert acesso.status_leitura == StatusLeitura.NAO_INICIADO


def test_registrar_acesso_com_porcentagem_parcial_deriva_em_andamento() -> None:
    acesso = _acesso()

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=10, porcentagem_leitura=0.01, download_realizado=False
    )

    assert acesso.status_leitura == StatusLeitura.EM_ANDAMENTO

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=10, porcentagem_leitura=0.99, download_realizado=False
    )

    assert acesso.status_leitura == StatusLeitura.EM_ANDAMENTO


def test_registrar_acesso_com_porcentagem_completa_deriva_concluido() -> None:
    acesso = _acesso()

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=10, porcentagem_leitura=1.0, download_realizado=False
    )

    assert acesso.status_leitura == StatusLeitura.CONCLUIDO


def test_registrar_acesso_preserva_id_material_e_aluno() -> None:
    acesso = _acesso()
    id_original = acesso.id
    material_id_original = acesso.material_personalizado_id
    aluno_id_original = acesso.aluno_id

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=10, porcentagem_leitura=0.5, download_realizado=False
    )

    assert acesso.id == id_original
    assert acesso.material_personalizado_id == material_id_original
    assert acesso.aluno_id == aluno_id_original
