from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from infrastructure.config.settings import Settings

_NOMES_DO_RECURSO = [
    "IMAGENS_GERADAS_HABILITADAS",
    "IMAGENS_PROVEDOR",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_IMAGE_MODEL",
    "CLOUDFLARE_IMAGE_STEPS",
    "CLOUDFLARE_IMAGE_TIMEOUT_SEGUNDOS",
    "IMAGENS_TIMEOUT_TOTAL_SEGUNDOS",
    "IMAGENS_ORCAMENTO_TOTAL_SEGUNDOS",
    "IMAGENS_MAX_POR_MATERIAL",
]
_CONTA = "0123456789abcdef0123456789abcdef"
_MODELO = "@cf/black-forest-labs/flux-1-schnell"


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isola os testes de qualquer variável do ambiente real e do .env (_env_file=None abaixo).
    for nome in _NOMES_DO_RECURSO:
        monkeypatch.delenv(nome, raising=False)


def _settings(**alteracoes: Any) -> Settings:
    return Settings(_env_file=None, **alteracoes)


def test_recurso_vem_desligado_por_padrao() -> None:
    assert _settings().imagens_geradas_habilitadas is False


def test_valores_padrao_sao_conservadores() -> None:
    s = _settings()
    assert s.imagens_max_por_material == 1
    assert s.cloudflare_image_steps == 4
    assert s.cloudflare_image_timeout_segundos == 60.0
    assert s.imagens_timeout_total_segundos == 120.0


def test_orcamento_total_padrao_e_150_segundos() -> None:
    assert _settings().imagens_orcamento_total_segundos == 150.0


@pytest.mark.parametrize("valor", [10, 10.0, 60, 150, 600])
def test_orcamento_total_aceita_valores_dentro_do_intervalo(valor: float) -> None:
    assert _settings(imagens_orcamento_total_segundos=valor).imagens_orcamento_total_segundos == (
        valor
    )


@pytest.mark.parametrize("valor", [0, -1, 9.99, 600.01, 10_000, float("nan"), float("inf")])
def test_orcamento_total_fora_do_intervalo_falha_na_inicializacao(valor: float) -> None:
    with pytest.raises(ValidationError):
        _settings(imagens_orcamento_total_segundos=valor)


def test_orcamento_total_vem_da_variavel_de_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAGENS_ORCAMENTO_TOTAL_SEGUNDOS", "90")
    assert _settings().imagens_orcamento_total_segundos == 90.0


def test_orcamento_total_nao_altera_o_timeout_por_imagem() -> None:
    s = _settings(imagens_orcamento_total_segundos=30)
    assert s.imagens_timeout_total_segundos == 120.0
    assert s.cloudflare_image_timeout_segundos == 60.0


def test_nenhum_modelo_nem_credencial_sao_presumidos() -> None:
    s = _settings()
    assert s.cloudflare_account_id is None
    assert s.cloudflare_api_token is None
    assert s.cloudflare_image_model is None


def test_sem_credencial_o_projeto_sobe_normalmente_com_o_recurso_desligado() -> None:
    assert _settings(imagens_geradas_habilitadas=False).cloudflare_api_token is None


def test_ligar_sem_token_falha_na_inicializacao() -> None:
    with pytest.raises(ValidationError, match="CLOUDFLARE_API_TOKEN"):
        _settings(
            imagens_geradas_habilitadas=True,
            cloudflare_account_id=_CONTA,
            cloudflare_image_model=_MODELO,
        )


def test_ligar_sem_modelo_falha_na_inicializacao() -> None:
    with pytest.raises(ValidationError, match="CLOUDFLARE_IMAGE_MODEL"):
        _settings(
            imagens_geradas_habilitadas=True,
            cloudflare_account_id=_CONTA,
            cloudflare_api_token="token-de-teste",
        )


@pytest.mark.parametrize("vazio", ["", "   "])
def test_token_e_modelo_vazios_valem_como_ausentes(vazio: str) -> None:
    with pytest.raises(ValidationError, match="CLOUDFLARE_API_TOKEN"):
        _settings(
            imagens_geradas_habilitadas=True,
            cloudflare_account_id=_CONTA,
            cloudflare_api_token=vazio,
            cloudflare_image_model=_MODELO,
        )
    with pytest.raises(ValidationError, match="CLOUDFLARE_IMAGE_MODEL"):
        _settings(
            imagens_geradas_habilitadas=True,
            cloudflare_account_id=_CONTA,
            cloudflare_api_token="token-de-teste",
            cloudflare_image_model=vazio,
        )
    s = _settings(cloudflare_api_token=vazio, cloudflare_image_model=vazio)
    assert s.cloudflare_api_token is None and s.cloudflare_image_model is None


def test_configuracao_completa_liga_o_recurso() -> None:
    s = _settings(
        imagens_geradas_habilitadas=True,
        cloudflare_account_id=_CONTA,
        cloudflare_api_token="token-de-teste",
        cloudflare_image_model=_MODELO,
    )
    assert s.imagens_geradas_habilitadas is True
    assert s.cloudflare_image_model == _MODELO
    assert isinstance(s.cloudflare_api_token, SecretStr)
    assert s.cloudflare_api_token.get_secret_value() == "token-de-teste"


def test_token_nao_aparece_em_repr_nem_em_str() -> None:
    s = _settings(cloudflare_api_token="segredo-que-nao-pode-vazar")
    assert "segredo-que-nao-pode-vazar" not in repr(s)
    assert "segredo-que-nao-pode-vazar" not in str(s)


def test_variaveis_de_ambiente_sao_lidas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAGENS_GERADAS_HABILITADAS", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", _CONTA)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-de-teste")
    monkeypatch.setenv("CLOUDFLARE_IMAGE_MODEL", _MODELO)
    monkeypatch.setenv("IMAGENS_MAX_POR_MATERIAL", "3")
    s = _settings()
    assert s.imagens_geradas_habilitadas is True
    assert s.imagens_max_por_material == 3


@pytest.mark.parametrize("valor", ["0", "-1", "6", "100", "abc", "1.5"])
def test_maximo_de_imagens_fora_de_1_a_5_e_rejeitado(valor: str) -> None:
    with pytest.raises(ValidationError):
        _settings(imagens_max_por_material=valor)


@pytest.mark.parametrize("valor", [1, 3, 5])
def test_maximo_de_imagens_dentro_do_limite_e_aceito(valor: int) -> None:
    assert _settings(imagens_max_por_material=valor).imagens_max_por_material == valor


@pytest.mark.parametrize("valor", [0, -5, 300.1, "abc"])
def test_timeout_por_tentativa_invalido_e_rejeitado(valor: Any) -> None:
    with pytest.raises(ValidationError):
        _settings(cloudflare_image_timeout_segundos=valor)


@pytest.mark.parametrize("valor", [0, -5, 600.1])
def test_timeout_total_invalido_e_rejeitado(valor: float) -> None:
    with pytest.raises(ValidationError):
        _settings(imagens_timeout_total_segundos=valor)


def test_timeout_total_menor_que_o_por_tentativa_e_rejeitado() -> None:
    with pytest.raises(ValidationError, match="IMAGENS_TIMEOUT_TOTAL_SEGUNDOS"):
        _settings(cloudflare_image_timeout_segundos=90, imagens_timeout_total_segundos=60)


def test_timeout_total_igual_ao_por_tentativa_e_aceito() -> None:
    s = _settings(cloudflare_image_timeout_segundos=60, imagens_timeout_total_segundos=60)
    assert s.imagens_timeout_total_segundos == 60


def test_flag_aceita_booleanos_do_pydantic_e_rejeita_lixo() -> None:
    for valor in ("false", "0", "no", False):
        assert _settings(imagens_geradas_habilitadas=valor).imagens_geradas_habilitadas is False
    with pytest.raises(ValidationError):
        _settings(imagens_geradas_habilitadas="talvez")
