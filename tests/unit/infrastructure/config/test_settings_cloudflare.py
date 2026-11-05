from typing import Any

import pytest
from pydantic import ValidationError

from infrastructure.config.settings import Settings

_NOMES_DO_RECURSO = [
    "IMAGENS_GERADAS_HABILITADAS",
    "IMAGENS_PROVEDOR",
    "IMAGENS_TIMEOUT_TOTAL_SEGUNDOS",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_IMAGE_MODEL",
    "CLOUDFLARE_IMAGE_STEPS",
    "CLOUDFLARE_IMAGE_TIMEOUT_SEGUNDOS",
]
_CONTA = "0123456789abcdef0123456789abcdef"
_TOKEN = "cf-token-de-teste-que-nao-pode-vazar"
_MODELO = "@cf/black-forest-labs/flux-1-schnell"


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isola os testes de qualquer variável do ambiente real e do .env (_env_file=None abaixo).
    for nome in _NOMES_DO_RECURSO:
        monkeypatch.delenv(nome, raising=False)


def _settings(**alteracoes: Any) -> Settings:
    return Settings(_env_file=None, **alteracoes)


def _completo(**alteracoes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "imagens_geradas_habilitadas": True,
        "imagens_provedor": "cloudflare",
        "cloudflare_account_id": _CONTA,
        "cloudflare_api_token": _TOKEN,
        "cloudflare_image_model": _MODELO,
    }
    base.update(alteracoes)
    return base


def test_provedor_padrao_e_cloudflare_e_nada_e_presumido() -> None:
    s = _settings()
    assert s.imagens_provedor == "cloudflare"
    assert s.cloudflare_account_id is None
    assert s.cloudflare_api_token is None
    assert s.cloudflare_image_model is None
    assert s.imagens_geradas_habilitadas is False


def test_valores_padrao_da_cloudflare_sao_conservadores() -> None:
    s = _settings()
    assert s.cloudflare_image_steps == 4
    assert s.cloudflare_image_timeout_segundos == 60.0


@pytest.mark.parametrize("provedor", ["outro", "openai", "OpenAI", "", "cloudflare "])
def test_provedor_diferente_de_cloudflare_falha_na_inicializacao(provedor: str) -> None:
    with pytest.raises(ValidationError):
        _settings(imagens_provedor=provedor)


def test_configuracao_completa_com_o_recurso_ligado_e_aceita() -> None:
    s = _settings(**_completo())
    assert s.cloudflare_account_id == _CONTA
    assert s.cloudflare_api_token is not None
    assert s.cloudflare_api_token.get_secret_value() == _TOKEN
    assert s.cloudflare_image_model == _MODELO


def test_cloudflare_configurada_mas_recurso_desligado_sobe_normalmente() -> None:
    s = _settings(**_completo(imagens_geradas_habilitadas=False, cloudflare_account_id="curto"))
    assert s.imagens_geradas_habilitadas is False


@pytest.mark.parametrize(
    "campo", ["cloudflare_account_id", "cloudflare_api_token", "cloudflare_image_model"]
)
def test_ligar_sem_credencial_ou_modelo_falha_na_inicializacao(campo: str) -> None:
    dados = _completo()
    del dados[campo]
    with pytest.raises(ValidationError, match="CLOUDFLARE_"):
        _settings(**dados)


@pytest.mark.parametrize("campo", ["cloudflare_account_id", "cloudflare_api_token"])
@pytest.mark.parametrize("vazio", ["", "   "])
def test_valor_vazio_equivale_a_ausente(campo: str, vazio: str) -> None:
    with pytest.raises(ValidationError, match="CLOUDFLARE_"):
        _settings(**_completo(**{campo: vazio}))


@pytest.mark.parametrize(
    "conta",
    [
        "0123456789abcdef0123456789abc",  # 29 caracteres: cópia incompleta
        "0123456789abcdef0123456789abcdef0",
        "0123456789abcdef0123456789abcdeg",
        "0123456789abcdef0123456789abcde ",
        '"0123456789abcdef0123456789abcdef"',
        "../0123456789abcdef0123456789abc",
    ],
)
def test_id_de_conta_fora_do_formato_falha_sem_revelar_o_valor(conta: str) -> None:
    with pytest.raises(ValidationError) as erro:
        _settings(**_completo(cloudflare_account_id=conta))
    assert "32 caracteres" in str(erro.value)
    assert conta.strip() not in str(erro.value).replace("input_value", "")
    assert _TOKEN not in str(erro.value)


@pytest.mark.parametrize(
    "modelo", ["flux-1-schnell", "@cf/x", "@cf/a/b/c", "@cf/a/b c", "@cf/../x", "@CF/a/b"]
)
def test_modelo_fora_do_formato_falha_na_inicializacao(modelo: str) -> None:
    with pytest.raises(ValidationError, match="CLOUDFLARE_IMAGE_MODEL"):
        _settings(**_completo(cloudflare_image_model=modelo))


@pytest.mark.parametrize("passos", [1, 4, 8])
def test_passos_dentro_do_intervalo_sao_aceitos(passos: int) -> None:
    assert _settings(cloudflare_image_steps=passos).cloudflare_image_steps == passos


@pytest.mark.parametrize("passos", [0, -1, 9, 100])
def test_passos_fora_do_intervalo_falham(passos: int) -> None:
    with pytest.raises(ValidationError):
        _settings(cloudflare_image_steps=passos)


def test_timeout_total_nao_pode_ser_menor_que_o_de_uma_tentativa_da_cloudflare() -> None:
    with pytest.raises(ValidationError, match="IMAGENS_TIMEOUT_TOTAL_SEGUNDOS"):
        _settings(
            imagens_provedor="cloudflare",
            cloudflare_image_timeout_segundos=100.0,
            imagens_timeout_total_segundos=90.0,
        )


def test_variaveis_de_credencial_de_outros_provedores_sao_ignoradas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Nenhum campo de outro provedor existe: variáveis residuais no ambiente não têm efeito.
    monkeypatch.setenv("OPENAI_API_KEY", "valor-residual-que-nao-pode-ser-usado")
    s = _settings(**_completo())
    assert not [campo for campo in Settings.model_fields if "openai" in campo.lower()]
    assert "valor-residual" not in repr(s) + s.model_dump_json()


def test_variaveis_de_ambiente_sao_lidas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAGENS_PROVEDOR", "cloudflare")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", _CONTA)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", _TOKEN)
    monkeypatch.setenv("CLOUDFLARE_IMAGE_MODEL", _MODELO)
    monkeypatch.setenv("CLOUDFLARE_IMAGE_STEPS", "6")
    s = _settings()
    assert (s.imagens_provedor, s.cloudflare_image_steps) == ("cloudflare", 6)
    assert s.imagens_geradas_habilitadas is False


def test_token_e_secretstr_e_nao_aparece_em_repr_nem_str() -> None:
    s = _settings(**_completo())
    assert _TOKEN not in repr(s)
    assert _TOKEN not in str(s)
    assert _TOKEN not in s.model_dump_json()
