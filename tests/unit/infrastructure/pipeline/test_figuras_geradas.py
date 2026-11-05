"""Ilustrações geradas por IA entram como figura com legenda, junto ao parágrafo que as explica."""

import pymupdf

from application.ports.gerador_imagens import ConceitoVisual, ImagemGerada
from infrastructure.pipeline.conceitos_visuais import marcador_de_ancora
from infrastructure.pipeline.gerador_pdf import (
    gerar_pdf_com_imagens_geradas,
    montar_documento_html_com_imagens_geradas,
)
from infrastructure.pipeline.imagens_geradas import ImagensGeradasDoMaterial

_MM = 72 / 25.4


def _png_grande() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1024, 1024), False)
    pix.clear_with(200)
    return pix.tobytes("png")


def _imagens(*pares: tuple[str, str]) -> ImagensGeradasDoMaterial:
    conceitos = tuple(ConceitoVisual(i, d, i) for i, d in pares)
    return ImagensGeradasDoMaterial(
        conceitos, tuple(ImagemGerada(_png_grande(), d) for _, d in pares)
    )


def _paragrafo(n: int, repeticoes: int = 8) -> str:
    return f"Explicação do tópico {n}. " + (
        "Detalhe didático sobre o conceito estudado. " * repeticoes
    )


def _material(topicos: int) -> str:
    partes = ["# Material de teste"]
    for n in range(1, topicos + 1):
        partes += [f"## Tópico {n}", _paragrafo(n), marcador_de_ancora(f"t{n}")]
    return "\n\n".join(partes)


def test_a_figura_fica_logo_depois_do_paragrafo_que_a_explica_e_antes_do_proximo_topico() -> None:
    imagens = _imagens(
        ("t1", "Balança com dois pratos equilibrados"), ("t2", "Duas pontes ligadas")
    )

    html = montar_documento_html_com_imagens_geradas(_material(2), imagens, incluir_capa=False)

    assert html.index("Explicação do tópico 1") < html.index("Figura 1.") < html.index("Tópico 2")
    assert html.index("Explicação do tópico 2") < html.index("Figura 2.")
    assert "<figure" in html and "<figcaption>" in html


def test_a_legenda_e_numerada_e_o_texto_vem_escapado() -> None:
    imagens = _imagens(("t1", "Cena com <b>negrito</b> & aspas"))

    html = montar_documento_html_com_imagens_geradas(_material(1), imagens, incluir_capa=False)

    assert (
        "<figcaption>Figura 1. Cena com &lt;b&gt;negrito&lt;/b&gt; &amp; aspas</figcaption>" in html
    )
    assert "<b>negrito</b>" not in html


def test_nao_existe_secao_de_imagens_originais_quando_nenhuma_e_informada() -> None:
    imagens = _imagens(("t1", "Balança com dois pratos equilibrados"))

    html = montar_documento_html_com_imagens_geradas(_material(1), imagens, incluir_capa=False)

    assert "Imagens do material original" not in html


def test_sem_imagens_geradas_nao_ha_figura_nem_legenda() -> None:
    html = montar_documento_html_com_imagens_geradas(_material(2), None, incluir_capa=False)

    assert "<figure" not in html and "Figura" not in html


def test_no_pdf_real_a_imagem_tem_tamanho_contido_e_a_legenda_acompanha_o_texto() -> None:
    imagens = _imagens(
        ("t1", "Balança com dois pratos equilibrados"),
        ("t2", "Duas pontes ligadas por uma estrada"),
        ("t3", "Três engrenagens encaixadas"),
    )

    pdf = pymupdf.open(stream=gerar_pdf_com_imagens_geradas(_material(3), imagens), filetype="pdf")

    figuras = 0
    for pagina in pdf:
        texto = pagina.get_text()
        for ref in pagina.get_images(full=True):
            for retangulo in pagina.get_image_rects(ref[0]):
                if retangulo.width > 150:  # ignora o logotipo da capa
                    figuras += 1
                    assert retangulo.width <= 106 * _MM and retangulo.height <= 86 * _MM
                    # Nunca uma página só de imagem: há texto da explicação na mesma página.
                    assert len(texto.replace("\n", " ").split()) > 40
        if "Figura " in texto:
            assert "Explicação do tópico" in texto
    assert figuras == 3
    assert sum("Figura " in p.get_text() for p in pdf) >= 3
