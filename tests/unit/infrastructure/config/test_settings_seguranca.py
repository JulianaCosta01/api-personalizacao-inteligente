from typing import Any

import pytest
from pydantic import ValidationError

from infrastructure.config.settings import Settings


def _settings(**campos: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/d",
        "service_token": "token-de-teste",
        "storage_url": "https://storage.teste.invalid",
        "storage_service_key": "chave-de-teste",
        "gemini_api_key": "chave-de-teste",
    }
    return Settings(_env_file=None, **{**base, **campos})


def test_padroes_dos_limites() -> None:
    s = _settings()
    assert s.pdf_paginas_maximas == 100
    assert s.pdf_pixels_maximos_por_imagem == 25_000_000
    assert s.corpo_json_tamanho_maximo_bytes == 1024 * 1024
    assert s.worker_prazo_maximo_job_segundos == 420.0
    assert s.worker_tentativas_maximas == 3


@pytest.mark.parametrize("valor", [0, -1, 1001])
def test_paginas_maximas_fora_do_intervalo_falham(valor: int) -> None:
    with pytest.raises(ValidationError):
        _settings(pdf_paginas_maximas=valor)


@pytest.mark.parametrize("valor", [0, 11])
def test_tentativas_maximas_fora_do_intervalo_falham(valor: int) -> None:
    with pytest.raises(ValidationError):
        _settings(worker_tentativas_maximas=valor)


@pytest.mark.parametrize("valor", [0, -5, 10 * 1024 * 1024 + 1])
def test_corpo_json_fora_do_intervalo_falha(valor: int) -> None:
    with pytest.raises(ValidationError):
        _settings(corpo_json_tamanho_maximo_bytes=valor)


def test_prazo_do_job_deve_ser_menor_que_a_idade_de_recuperacao() -> None:
    with pytest.raises(ValidationError, match="PRAZO_MAXIMO_JOB"):
        _settings(worker_prazo_maximo_job_segundos=600.0, worker_idade_maxima_presos_segundos=600.0)
    assert (
        _settings(worker_prazo_maximo_job_segundos=599.0).worker_prazo_maximo_job_segundos == 599.0
    )


def test_limites_vem_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDF_PAGINAS_MAXIMAS", "40")
    assert _settings().pdf_paginas_maximas == 40


def test_padroes_da_repeticao_por_falha_transitoria() -> None:
    s = _settings()
    assert s.worker_repeticao_atraso_base_segundos == 30.0
    assert s.worker_repeticao_atraso_maximo_segundos == 300.0


@pytest.mark.parametrize(
    "campo", ["worker_repeticao_atraso_base_segundos", "worker_repeticao_atraso_maximo_segundos"]
)
@pytest.mark.parametrize("valor", [0, -1])
def test_atraso_de_repeticao_nao_positivo_falha(campo: str, valor: float) -> None:
    with pytest.raises(ValidationError):
        _settings(**{campo: valor})


def test_atraso_maximo_menor_que_o_base_falha() -> None:
    with pytest.raises(ValidationError, match="WORKER_REPETICAO_ATRASO_MAXIMO_SEGUNDOS"):
        _settings(
            worker_repeticao_atraso_base_segundos=60.0,
            worker_repeticao_atraso_maximo_segundos=30.0,
        )
