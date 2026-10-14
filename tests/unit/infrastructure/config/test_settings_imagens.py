from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from infrastructure.config.settings import Settings

_NOMES_DO_RECURSO = [
    "IMAGENS_GERADAS_HABILITADAS",
    "OPENAI_API_KEY",
    "OPENAI_IMAGE_MODEL",
    "OPENAI_IMAGE_QUALITY",
    "OPENAI_IMAGE_SIZE",
    "OPENAI_IMAGE_TIMEOUT_SEGUNDOS",
    "IMAGENS_TIMEOUT_TOTAL_SEGUNDOS",
    "IMAGENS_MAX_POR_MATERIAL",
]


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
    assert s.openai_image_quality == "low"
    assert s.openai_image_size == "1024x1024"
    assert s.openai_image_timeout_segundos == 60.0
    assert s.imagens_timeout_total_segundos == 120.0


def test_nenhum_modelo_nem_chave_sao_presumidos() -> None:
    s = _settings()
    assert s.openai_api_key is None
    assert s.openai_image_model is None


def test_sem_chave_o_projeto_sobe_normalmente_com_o_recurso_desligado() -> None:
    assert _settings(imagens_geradas_habilitadas=False).openai_api_key is None


def test_ligar_sem_chave_falha_na_inicializacao() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        _settings(imagens_geradas_habilitadas=True, openai_image_model="modelo-x")


def test_ligar_sem_modelo_falha_na_inicializacao() -> None:
    with pytest.raises(ValidationError, match="OPENAI_IMAGE_MODEL"):
        _settings(imagens_geradas_habilitadas=True, openai_api_key="chave-de-teste")


@pytest.mark.parametrize("vazio", ["", "   "])
def test_chave_e_modelo_vazios_valem_como_ausentes(vazio: str) -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        _settings(
            imagens_geradas_habilitadas=True, openai_api_key=vazio, openai_image_model="modelo-x"
        )
    with pytest.raises(ValidationError, match="OPENAI_IMAGE_MODEL"):
        _settings(
            imagens_geradas_habilitadas=True,
            openai_api_key="chave-de-teste",
            openai_image_model=vazio,
        )
    assert _settings(openai_api_key=vazio, openai_image_model=vazio).openai_api_key is None


def test_configuracao_completa_liga_o_recurso() -> None:
    s = _settings(
        imagens_geradas_habilitadas=True,
        openai_api_key="chave-de-teste",
        openai_image_model="modelo-x",
    )
    assert s.imagens_geradas_habilitadas is True
    assert s.openai_image_model == "modelo-x"
    assert isinstance(s.openai_api_key, SecretStr)
    assert s.openai_api_key.get_secret_value() == "chave-de-teste"


def test_chave_nao_aparece_em_repr_nem_em_str() -> None:
    s = _settings(openai_api_key="segredo-que-nao-pode-vazar")
    assert "segredo-que-nao-pode-vazar" not in repr(s)
    assert "segredo-que-nao-pode-vazar" not in str(s)


def test_variaveis_de_ambiente_sao_lidas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAGENS_GERADAS_HABILITADAS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "chave-de-teste")
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "modelo-x")
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
def test_timeout_por_imagem_invalido_e_rejeitado(valor: Any) -> None:
    with pytest.raises(ValidationError):
        _settings(openai_image_timeout_segundos=valor)


@pytest.mark.parametrize("valor", [0, -5, 600.1])
def test_timeout_total_invalido_e_rejeitado(valor: float) -> None:
    with pytest.raises(ValidationError):
        _settings(imagens_timeout_total_segundos=valor)


def test_timeout_total_menor_que_o_por_imagem_e_rejeitado() -> None:
    with pytest.raises(ValidationError, match="IMAGENS_TIMEOUT_TOTAL_SEGUNDOS"):
        _settings(openai_image_timeout_segundos=90, imagens_timeout_total_segundos=60)


def test_timeout_total_igual_ao_por_imagem_e_aceito() -> None:
    s = _settings(openai_image_timeout_segundos=60, imagens_timeout_total_segundos=60)
    assert s.imagens_timeout_total_segundos == 60


@pytest.mark.parametrize("qualidade", ["auto", "low", "medium", "high"])
def test_qualidades_conhecidas_sao_aceitas(qualidade: str) -> None:
    assert _settings(openai_image_quality=qualidade).openai_image_quality == qualidade


@pytest.mark.parametrize("qualidade", ["", "ultra", "HIGH", "standard"])
def test_qualidade_desconhecida_e_rejeitada(qualidade: str) -> None:
    with pytest.raises(ValidationError):
        _settings(openai_image_quality=qualidade)


@pytest.mark.parametrize("tamanho", ["auto", "1024x1024", "1536x1024", "1024x1536", "2048x2048"])
def test_tamanhos_com_formato_valido_sao_aceitos(tamanho: str) -> None:
    assert _settings(openai_image_size=tamanho).openai_image_size == tamanho


@pytest.mark.parametrize(
    "tamanho",
    ["", "1024", "1024X1024", "0x0", "10x10", "1024x", "x1024", "1024x1024; rm", " 1024x1024"],
)
def test_tamanho_com_formato_invalido_e_rejeitado(tamanho: str) -> None:
    with pytest.raises(ValidationError):
        _settings(openai_image_size=tamanho)


def test_flag_aceita_booleanos_do_pydantic_e_rejeita_lixo() -> None:
    for valor in ("false", "0", "no", False):
        assert _settings(imagens_geradas_habilitadas=valor).imagens_geradas_habilitadas is False
    with pytest.raises(ValidationError):
        _settings(imagens_geradas_habilitadas="talvez")
