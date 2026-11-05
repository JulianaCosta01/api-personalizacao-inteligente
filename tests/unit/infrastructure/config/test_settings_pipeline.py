from typing import Any

import pytest
from pydantic import ValidationError

from infrastructure.config.settings import Settings

_NOMES = [
    "PIPELINE_TIMEOUT_EXTRACAO_SEGUNDOS",
    "PIPELINE_TIMEOUT_PDF_SEGUNDOS",
    "GEMINI_TIMEOUT_TOTAL_SEGUNDOS",
    "WORKER_PRAZO_MAXIMO_JOB_SEGUNDOS",
    "IMAGENS_GERADAS_HABILITADAS",
    "IMAGENS_PROVEDOR",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_IMAGE_MODEL",
    "IMAGENS_ORCAMENTO_TOTAL_SEGUNDOS",
]


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in _NOMES:
        monkeypatch.delenv(nome, raising=False)


# Credenciais fictícias que tornam válido ligar o recurso de imagens (nenhuma chamada de rede).
_CLOUDFLARE_COMPLETA: dict[str, Any] = {
    "cloudflare_account_id": "0123456789abcdef0123456789abcdef",
    "cloudflare_api_token": "token-de-teste",
    "cloudflare_image_model": "@cf/black-forest-labs/flux-1-schnell",
}


def _settings(**alteracoes: Any) -> Settings:
    return Settings(_env_file=None, **alteracoes)


def test_etapas_locais_tem_limites_proprios_maiores_que_o_da_chamada_ao_gemini() -> None:
    s = _settings()
    assert s.gemini_timeout_segundos == 5.0
    assert s.pipeline_timeout_extracao_segundos == 30.0
    assert s.pipeline_timeout_pdf_segundos == 60.0


@pytest.mark.parametrize(
    "campo", ["pipeline_timeout_extracao_segundos", "pipeline_timeout_pdf_segundos"]
)
@pytest.mark.parametrize("valor", [0, -1])
def test_limites_das_etapas_locais_precisam_ser_positivos(campo: str, valor: float) -> None:
    with pytest.raises(ValidationError):
        _settings(**{campo: valor})


def test_pior_caso_de_um_job_com_os_padroes_cabe_no_prazo_de_420_segundos() -> None:
    s = _settings()
    pior_caso = (
        s.pipeline_timeout_extracao_segundos
        + s.gemini_timeout_total_segundos
        + s.pipeline_timeout_pdf_segundos
    )
    assert pior_caso == 135.0
    assert pior_caso <= s.worker_prazo_maximo_job_segundos == 420.0


def test_pior_caso_com_imagens_ligadas_inclui_o_fallback_do_pdf_e_cabe_no_prazo() -> None:
    s = _settings(
        imagens_geradas_habilitadas=True,
        **_CLOUDFLARE_COMPLETA,
    )
    # 135 (base) + 150 (orçamento de imagens) + 60 (segunda montagem do PDF, só com texto)
    pior_caso = 135.0 + s.imagens_orcamento_total_segundos + s.pipeline_timeout_pdf_segundos
    assert pior_caso == 345.0 <= s.worker_prazo_maximo_job_segundos


def test_fallback_do_pdf_conta_na_soma_quando_as_imagens_estao_ligadas() -> None:
    # Sem a segunda montagem, a soma seria 30 + 2*45 (Gemini + 1 complementação) + 60 + 150 =
    # 330, que caberia em 380; com a segunda montagem (60) a soma é 390 e 380 é recusado.
    com_imagens = dict(
        imagens_geradas_habilitadas=True,
        **_CLOUDFLARE_COMPLETA,
    )
    with pytest.raises(ValidationError, match="excede"):
        _settings(worker_prazo_maximo_job_segundos=380.0, **com_imagens)
    _settings(worker_prazo_maximo_job_segundos=420.0, **com_imagens)


def test_soma_das_etapas_acima_do_prazo_do_job_e_recusada() -> None:
    with pytest.raises(ValidationError, match="excede WORKER_PRAZO_MAXIMO_JOB_SEGUNDOS"):
        _settings(pipeline_timeout_pdf_segundos=400.0)  # 60 + 45 + 400 > 420


def test_orcamento_de_imagens_so_conta_quando_o_recurso_esta_ligado() -> None:
    # Desligado, o orçamento de imagens não entra na soma: 30 + 2*45 + 60 = 180 cabe em 220.
    _settings(worker_prazo_maximo_job_segundos=220.0, imagens_orcamento_total_segundos=150.0)
    with pytest.raises(ValidationError, match="excede"):
        _settings(
            worker_prazo_maximo_job_segundos=220.0,
            imagens_geradas_habilitadas=True,
            **_CLOUDFLARE_COMPLETA,
        )


def test_segunda_extracao_so_conta_quando_as_imagens_originais_sao_anexadas() -> None:
    # Configuração do E2E real: extração de 90 s, Gemini total 90 s (+1 complementação), PDF 60 s,
    # imagens geradas ligadas (150 s + segunda montagem de 60 s), prazo de 570 s.
    base: dict[str, Any] = dict(
        pipeline_timeout_extracao_segundos=90.0,
        gemini_timeout_total_segundos=90.0,
        worker_prazo_maximo_job_segundos=570.0,
        imagens_geradas_habilitadas=True,
        **_CLOUDFLARE_COMPLETA,
    )
    # Originais desligadas (padrão): 90 + 180 + 60 + 150 + 60 = 540 <= 570.
    s = _settings(**base)
    assert s.pdf_anexar_imagens_originais is False
    # Ligadas, a segunda extração entra: 630 > 570 e a configuração é recusada.
    with pytest.raises(ValidationError, match="excede WORKER_PRAZO_MAXIMO_JOB_SEGUNDOS"):
        _settings(pdf_anexar_imagens_originais=True, **base)


def test_extracao_de_90_segundos_mantem_o_prazo_abaixo_da_recuperacao_de_jobs_presos() -> None:
    s = _settings(
        pipeline_timeout_extracao_segundos=90.0,
        gemini_timeout_total_segundos=90.0,
        worker_prazo_maximo_job_segundos=570.0,
        imagens_geradas_habilitadas=True,
        **_CLOUDFLARE_COMPLETA,
    )
    assert s.worker_prazo_maximo_job_segundos < s.worker_idade_maxima_presos_segundos == 600.0
