from unittest.mock import patch

import pytest

from infrastructure.pipeline import gerador_pdf
from infrastructure.pipeline.extrator import ImagemExtraida
from infrastructure.pipeline.gerador_pdf import (
    folhas_de_estilo_pdf,
    gerar_pdf,
    montar_documento_html,
)

from .pdf_fixture import png_sintetico

_MARKDOWN = "# Título\n\nParágrafo de corpo suficientemente longo para virar subtítulo da capa.\n"


def _imagens() -> list[ImagemExtraida]:
    return [ImagemExtraida(0, 0, png_sintetico(40, 30), "png")]


def test_sem_capa_devolve_apenas_o_fragmento_do_corpo() -> None:
    html = montar_documento_html(_MARKDOWN, incluir_capa=False)
    assert html.startswith("<h1>Título</h1>")
    assert "<html" not in html
    assert 'class="capa"' not in html


def test_com_capa_devolve_documento_completo_com_a_capa_antes_do_corpo() -> None:
    html = montar_documento_html(_MARKDOWN)
    assert html.startswith('<!DOCTYPE html><html lang="pt-BR">')
    assert html.index('class="capa"') < html.index("<h1>Título</h1>")
    assert "<title>Título</title>" in html


def test_capa_e_ligada_por_padrao() -> None:
    assert montar_documento_html(_MARKDOWN) == montar_documento_html(_MARKDOWN, incluir_capa=True)


def test_imagens_sao_embutidas_como_data_uri_ao_final_do_corpo() -> None:
    html = montar_documento_html(_MARKDOWN, _imagens(), incluir_capa=False)
    assert "Imagens do material original" in html
    assert html.count("data:image/png;base64,") == 1
    assert html.index("<h1>Título</h1>") < html.index("Imagens do material original")


def test_capa_usa_o_markdown_sem_as_imagens_anexadas() -> None:
    com = montar_documento_html(_MARKDOWN, _imagens())
    sem = montar_documento_html(_MARKDOWN)
    assert "<title>Título</title>" in com
    assert com.count('class="capa-titulo"') == sem.count('class="capa-titulo"') == 1


def test_folhas_de_estilo_com_e_sem_capa_na_ordem_atual() -> None:
    assert folhas_de_estilo_pdf(incluir_capa=False) == [gerador_pdf._FOLHA_DE_ESTILO]
    assert folhas_de_estilo_pdf() == [
        gerador_pdf._FOLHA_DE_ESTILO,
        gerador_pdf._FOLHA_DE_ESTILO_CAPA,
    ]


def test_folhas_de_estilo_nao_estao_embutidas_no_html() -> None:
    assert "<style" not in montar_documento_html(_MARKDOWN)


@pytest.mark.parametrize("incluir_capa", [True, False])
def test_gerar_pdf_entrega_ao_weasyprint_exatamente_o_html_e_as_folhas_montados(
    incluir_capa: bool,
) -> None:
    imagens = _imagens()
    esperado_html = montar_documento_html(_MARKDOWN, imagens, incluir_capa=incluir_capa)
    esperado_folhas = folhas_de_estilo_pdf(incluir_capa=incluir_capa)
    capturado: dict[str, object] = {}

    class HTMLFalso:
        def __init__(self, string: str, url_fetcher: object) -> None:
            capturado["html"] = string
            capturado["fetcher"] = url_fetcher

        def write_pdf(self, stylesheets: list[object]) -> bytes:
            capturado["n_folhas"] = len(stylesheets)
            return b"%PDF-falso"

    with (
        patch.object(gerador_pdf, "HTML", HTMLFalso),
        patch.object(gerador_pdf, "CSS", lambda string, url_fetcher: string),
    ):
        resultado = gerar_pdf(_MARKDOWN, imagens, incluir_capa=incluir_capa)

    assert resultado == b"%PDF-falso"
    assert capturado["html"] == esperado_html
    assert capturado["fetcher"] is gerador_pdf._url_fetcher_sem_rede
    assert capturado["n_folhas"] == len(esperado_folhas)


def test_html_bruto_no_markdown_nao_e_sanitizado_aqui() -> None:
    # Documenta o limite desta função: ela NÃO sanitiza. Servir ao navegador exige sanitização.
    html = montar_documento_html("<script>alert(1)</script>\n", incluir_capa=False)
    assert "<script>alert(1)</script>" in html
