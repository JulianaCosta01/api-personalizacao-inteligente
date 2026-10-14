import base64
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from unittest.mock import patch

import pymupdf
import pytest

from infrastructure.pipeline import gerador_pdf
from infrastructure.pipeline.extrator import ImagemExtraida, extrair_imagens
from infrastructure.pipeline.gerador_pdf import gerar_pdf as _gerar_pdf

from .pdf_fixture import (
    pdf_com_duas_imagens,
    pdf_com_imagem,
    pdf_com_imagem_repetida,
    png_sintetico,
)


def gerar_pdf(conteudo_markdown: str, imagens: Sequence[ImagemExtraida] = ()) -> bytes:
    # Estes testes verificam o corpo do documento (paginação, margens, imagens, avisos) e por
    # isso usam a geração sem capa, que continua suportada; a capa tem testes próprios em
    # test_capa_pdf.py, incluindo a convivência com o corpo.
    return _gerar_pdf(conteudo_markdown, imagens, incluir_capa=False)


def test_gera_pdf_valido_a_partir_de_markdown() -> None:
    pdf = gerar_pdf("# Título\n\nParágrafo de conteúdo adaptado.")

    assert pdf.startswith(b"%PDF-")


def test_gera_pdf_com_tabela_e_codigo() -> None:
    conteudo = "| A | B |\n| - | - |\n| 1 | 2 |\n\n```\ncodigo de exemplo\n```\n"

    pdf = gerar_pdf(conteudo)

    assert pdf.startswith(b"%PDF-")


def test_gera_pdf_com_titulos_e_formulas_normalizadas() -> None:
    # Fórmulas já chegam normalizadas para Unicode (infrastructure.pipeline.normalizador) —
    # gerar_pdf só precisa continuar aceitando texto comum, sem referência a recurso externo.
    conteudo = "## Lógica proposicional\n\nSe A → B e A, então B (∴ modus ponens).\n"

    pdf = gerar_pdf(conteudo)

    assert pdf.startswith(b"%PDF-")


@contextmanager
def _bloqueia_conexoes_de_rede() -> Iterator[None]:
    # Prova mais forte que "não deu erro": se o WeasyPrint tentasse abrir uma conexão real,
    # o teste falha aqui, em vez de depender de timing ou de DNS de fato falhar.
    def _levantar(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Nenhuma conexão de rede deveria ser aberta durante a geração do PDF.")

    with patch("socket.socket.connect", side_effect=_levantar):
        yield


def test_referencia_http_externa_e_bloqueada_sem_acessar_a_rede() -> None:
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto adaptado ![imagem](http://exemplo-externo.test/x.png) depois.")

    # PDF continua sendo gerado normalmente — a imagem bloqueada só não aparece.
    assert pdf.startswith(b"%PDF-")


def test_referencia_a_localhost_e_bloqueada_sem_acessar_a_rede() -> None:
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto adaptado ![imagem](http://127.0.0.1:8000/interno) depois.")

    assert pdf.startswith(b"%PDF-")


def test_referencia_a_ip_privado_e_bloqueada_sem_acessar_a_rede() -> None:
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto adaptado ![imagem](http://10.0.0.5/interno) depois.")

    assert pdf.startswith(b"%PDF-")


def test_referencia_a_metadata_endpoint_e_bloqueada_sem_acessar_a_rede() -> None:
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto adaptado ![imagem](http://169.254.169.254/latest/meta-data/) fim.")

    assert pdf.startswith(b"%PDF-")


def test_bloqueio_de_recurso_externo_nao_levanta_excecao_nem_vaza_detalhes() -> None:
    # O bloqueio é tratado internamente pelo WeasyPrint (recurso ausente, não
    # erro fatal) — gerar_pdf não deve propagar exceção nenhuma para esse caso.
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto ![imagem](http://exemplo-externo.test/segredo?token=abc) fim.")

    assert pdf.startswith(b"%PDF-")


def _colocacoes_das_imagens(
    conteudo_pdf: bytes,
) -> list[tuple[int, tuple[float, float, float, float]]]:
    # Colocações (get_image_info), não referências de recurso: get_images lista os recursos de
    # cada página e superconta em PDFs de várias páginas (medido: 225 referências para 15
    # imagens colocadas) e subconta bytes idênticos reaproveitados.
    # Só entram colocações cuja bbox intersecta o retângulo da página. Isso NÃO garante
    # visibilidade efetiva: cobertura por outros elementos, recorte (clip) e transparência
    # total não são avaliados.
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        colocacoes: list[tuple[int, tuple[float, float, float, float]]] = []
        for numero_pagina in range(documento.page_count):
            pagina = documento[numero_pagina]
            for info in pagina.get_image_info():
                caixa = pymupdf.Rect(info["bbox"])
                if caixa.intersects(pagina.rect):
                    colocacoes.append((numero_pagina, tuple(info["bbox"])))
        return colocacoes
    finally:
        documento.close()


def _contar_imagens(conteudo_pdf: bytes) -> int:
    return len(_colocacoes_das_imagens(conteudo_pdf))


def test_gera_pdf_sem_imagens_quando_nenhuma_e_informada() -> None:
    # Comportamento anterior à Etapa 2 precisa continuar idêntico quando o
    # chamador não passa imagens (parâmetro tem valor padrão vazio).
    pdf = gerar_pdf("Texto adaptado sem imagens.")

    assert pdf.startswith(b"%PDF-")
    assert _contar_imagens(pdf) == 0


def test_preserva_uma_imagem_extraida_do_pdf_original() -> None:
    imagens = extrair_imagens(pdf_com_imagem("Conteúdo com imagem."))

    pdf = gerar_pdf("Texto adaptado.", imagens)

    assert pdf.startswith(b"%PDF-")
    assert _contar_imagens(pdf) == len(imagens) == 1


def test_preserva_multiplas_imagens_extraidas_do_pdf_original() -> None:
    imagens = extrair_imagens(pdf_com_duas_imagens("Conteúdo com duas imagens."))

    pdf = gerar_pdf("Texto adaptado.", imagens)

    assert pdf.startswith(b"%PDF-")
    assert _contar_imagens(pdf) == len(imagens) == 2


def test_conteudo_visual_da_imagem_e_preservado_na_reconstrucao() -> None:
    # Além de "existe uma imagem no PDF final", confirma que o pixel embutido
    # ainda corresponde à cor original (vermelho) — não é um placeholder vazio.
    imagens = extrair_imagens(pdf_com_imagem())

    pdf = gerar_pdf("Texto adaptado.", imagens)

    documento = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        referencias = documento[0].get_images(full=True)
        assert len(referencias) == 1
        imagem_no_resultado = documento.extract_image(referencias[0][0])
    finally:
        documento.close()

    assert len(imagem_no_resultado["image"]) > 0
    pixmap = pymupdf.Pixmap(imagem_no_resultado["image"])
    if pixmap.colorspace is not None and pixmap.colorspace.n != 3:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
    canal_r, canal_g, canal_b = pixmap.pixel(pixmap.width // 2, pixmap.height // 2)[:3]
    assert canal_r > 200
    assert canal_g < 50
    assert canal_b < 50


def test_ignora_imagem_com_extensao_nao_permitida() -> None:
    # Defesa em profundidade: extensão fora do allowlist não deve ser embutida
    # como data URI mesmo que já tenha vindo validada de extrair_imagens.
    imagem_suspeita = ImagemExtraida(
        numero_pagina=0, indice_na_pagina=0, conteudo=b"conteudo-arbitrario", extensao="svg"
    )

    pdf = gerar_pdf("Texto adaptado.", [imagem_suspeita])

    assert pdf.startswith(b"%PDF-")
    assert _contar_imagens(pdf) == 0


def test_geracao_com_imagens_reais_nao_abre_conexao_de_rede() -> None:
    # As imagens preservadas viajam como data URI (sem rede); um link externo
    # no mesmo Markdown continua bloqueado pelo URLFetcher restrito.
    imagens = extrair_imagens(pdf_com_imagem())

    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto ![imagem externa](http://exemplo-externo.test/x.png) fim.", imagens)

    assert pdf.startswith(b"%PDF-")
    assert _contar_imagens(pdf) == len(imagens) == 1


# --- Apresentação visual (folha de estilo) -----------------------------------------------------
# Margens definidas em @page (22 mm laterais, 25 mm superior/inferior). As verificações abaixo
# leem posições reais no PDF gerado, em vez de apenas confirmar que o CSS contém uma regra.

_MM = 72 / 25.4
_MARGEM_LATERAL = 22 * _MM
_MARGEM_VERTICAL = 25 * _MM
_TOLERANCIA = 2.0


def _texto_por_pagina(conteudo_pdf: bytes) -> list[str]:
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        return [documento[numero].get_text() for numero in range(documento.page_count)]
    finally:
        documento.close()


def _sem_espacos(texto: str) -> str:
    return "".join(texto.split())


def _maior_x_das_palavras(conteudo_pdf: bytes) -> tuple[float, float]:
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        largura = documento[0].rect.width
        maior = max(
            palavra[2]
            for numero in range(documento.page_count)
            for palavra in documento[numero].get_text("words")
        )
        return maior, largura
    finally:
        documento.close()


def _caixas_das_imagens(
    conteudo_pdf: bytes,
) -> list[tuple[int, tuple[float, float, float, float]]]:
    # Devolve (número da página, bbox) para não misturar páginas ao comparar posições.
    return _colocacoes_das_imagens(conteudo_pdf)


def _imagem_extraida(largura: int, altura: int) -> ImagemExtraida:
    return ImagemExtraida(
        numero_pagina=0,
        indice_na_pagina=0,
        conteudo=png_sintetico(largura, altura),
        extensao="png",
    )


def test_numeracao_de_paginas_em_pdf_com_varias_paginas() -> None:
    paragrafos = [f"Parágrafo {i}: " + "texto de preenchimento " * 18 for i in range(80)]

    pdf = gerar_pdf("# Documento longo\n\n" + "\n\n".join(paragrafos))

    textos = _texto_por_pagina(pdf)
    total = len(textos)
    assert total >= 3
    for numero, texto in enumerate(textos, start=1):
        assert f"Página {numero} de {total}" in texto


def test_linha_longa_de_codigo_permanece_completa_e_dentro_das_margens() -> None:
    linha_com_espacos = (
        "resultado = processar(" + ", ".join(f"argumento_{i:03d}" for i in range(60)) + ")"
    )
    token_sem_espacos = "TOKEN" + "0123456789abcdef" * 20
    conteudo = f"Antes do código.\n\n```\n{linha_com_espacos}\n{token_sem_espacos}\n```\n"

    pdf = gerar_pdf(conteudo)

    texto = _sem_espacos("\n".join(_texto_por_pagina(pdf)))
    assert _sem_espacos(linha_com_espacos) in texto
    assert token_sem_espacos in texto
    maior_x, largura_pagina = _maior_x_das_palavras(pdf)
    assert maior_x <= largura_pagina - _MARGEM_LATERAL + _TOLERANCIA


def test_hierarquia_de_titulos_por_tamanho_de_fonte() -> None:
    pdf = gerar_pdf("# Título Um\n\n## Título Dois\n\n### Título Três\n\nParágrafo comum.\n")

    documento = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        tamanhos: dict[str, float] = {}
        for bloco in documento[0].get_text("dict")["blocks"]:
            for linha in bloco.get("lines", []):
                for trecho in linha["spans"]:
                    tamanhos[trecho["text"].strip()] = trecho["size"]
    finally:
        documento.close()

    h1, h2, h3 = tamanhos["Título Um"], tamanhos["Título Dois"], tamanhos["Título Três"]
    corpo = tamanhos["Parágrafo comum."]
    assert h1 > h2 > h3 > corpo


def test_tabela_lista_e_citacao_preservam_o_conteudo_textual() -> None:
    conteudo = (
        "## Conceitos\n\n"
        "| Conceito | Descrição |\n| --- | --- |\n"
        "| Alfa | Primeira letra |\n| Beta | Segunda letra |\n\n"
        "- Item um\n- Item dois\n\n"
        "1. Passo A\n2. Passo B\n\n"
        "> Citação importante.\n"
    )

    pdf = gerar_pdf(conteudo)

    texto = _sem_espacos("\n".join(_texto_por_pagina(pdf)))
    for esperado in (
        "Conceito",
        "Descrição",
        "Alfa",
        "Primeiraletra",
        "Beta",
        "Segundaletra",
        "Itemum",
        "Itemdois",
        "PassoA",
        "PassoB",
        "Citaçãoimportante.",
    ):
        assert esperado in texto


def test_tabela_larga_nao_ultrapassa_as_margens() -> None:
    celula_longa = "palavralonga" * 20
    conteudo = f"| Coluna A | Coluna B |\n| - | - |\n| {celula_longa} | valor |\n"

    pdf = gerar_pdf(conteudo)

    assert celula_longa in _sem_espacos("\n".join(_texto_por_pagina(pdf)))
    maior_x, largura_pagina = _maior_x_das_palavras(pdf)
    assert maior_x <= largura_pagina - _MARGEM_LATERAL + _TOLERANCIA


def test_imagem_larga_cabe_na_area_util_sem_distorcao() -> None:
    pdf = gerar_pdf("Texto.", [_imagem_extraida(2400, 1200)])

    ((_, (x0, y0, x1, y1)),) = _caixas_das_imagens(pdf)
    largura_util = 595.28 - 2 * _MARGEM_LATERAL
    assert x0 >= _MARGEM_LATERAL - _TOLERANCIA
    assert x1 <= 595.28 - _MARGEM_LATERAL + _TOLERANCIA
    assert (x1 - x0) <= largura_util + _TOLERANCIA
    assert abs((x1 - x0) / (y1 - y0) - 2.0) < 0.04


def test_imagem_alta_cabe_na_altura_util_sem_distorcao() -> None:
    pdf = gerar_pdf("Texto.", [_imagem_extraida(600, 3000)])

    ((_, (x0, y0, x1, y1)),) = _caixas_das_imagens(pdf)
    altura_util = 841.89 - 2 * _MARGEM_VERTICAL
    assert y0 >= _MARGEM_VERTICAL - _TOLERANCIA
    assert y1 <= 841.89 - _MARGEM_VERTICAL + _TOLERANCIA
    assert (y1 - y0) <= altura_util + _TOLERANCIA
    assert abs((x1 - x0) / (y1 - y0) - 0.2) < 0.01


def test_imagem_pequena_mantem_o_tamanho_original() -> None:
    pdf = gerar_pdf("Texto.", [_imagem_extraida(40, 40)])

    ((_, (x0, y0, x1, y1)),) = _caixas_das_imagens(pdf)
    assert abs((x1 - x0) - 30.0) < _TOLERANCIA
    assert abs((y1 - y0) - 30.0) < _TOLERANCIA


# --- Contagem, repetição e ordem das colocações -------------------------------------------------


def test_contagem_por_colocacao_em_pdf_de_varias_paginas() -> None:
    # 100x600 px = 450 pt de altura: duas não cabem na área útil, então cada uma ocupa uma página.
    # Cores distintas de propósito: imagens idênticas seriam reaproveitadas pelo WeasyPrint e
    # não exercitariam a diferença entre get_images (referências) e get_image_info (colocações).
    imagens = [
        ImagemExtraida(0, indice, png_sintetico(100, 600, (40 * indice, 60, 120)), "png")
        for indice in range(5)
    ]

    pdf = gerar_pdf("Texto.", imagens)

    assert len(_texto_por_pagina(pdf)) >= 3
    assert _contar_imagens(pdf) == len(imagens) == 5


def test_ocorrencias_repetidas_chegam_todas_ao_pdf_final() -> None:
    # Mesmos bytes recebidos 3 vezes: o PDF pode reaproveitar o recurso internamente, mas as
    # três colocações precisam continuar existindo.
    imagem = _imagem_extraida(80, 80)

    pdf = gerar_pdf("Texto.", [imagem, imagem, imagem])

    assert _contar_imagens(pdf) == 3


def test_imagem_reutilizada_em_varias_paginas_do_original_mantem_todas_as_ocorrencias() -> None:
    imagens = extrair_imagens(pdf_com_imagem_repetida(paginas=3))

    assert [imagem.numero_pagina for imagem in imagens] == [0, 1, 2]
    pdf = gerar_pdf("Texto adaptado.", imagens)

    assert _contar_imagens(pdf) == 3


def test_ordem_das_colocacoes_segue_a_ordem_das_imagens_recebidas() -> None:
    # Larguras distintas identificam cada imagem: 100, 200 e 300 px = 75, 150 e 225 pt.
    imagens = [_imagem_extraida(100, 100), _imagem_extraida(200, 100), _imagem_extraida(300, 100)]

    pdf = gerar_pdf("Texto.", imagens)

    caixas = sorted(_caixas_das_imagens(pdf), key=lambda item: (item[0], item[1][1]))
    larguras = [round(x1 - x0) for (_, (x0, _, x1, _)) in caixas]
    assert larguras == [75, 150, 225]


def test_ordem_das_colocacoes_em_varias_paginas_segue_a_ordem_das_imagens_recebidas() -> None:
    # 600 px de altura = 450 pt: duas não cabem na mesma página, então cada imagem ocupa uma.
    # Ordenar só por y0 misturaria páginas; a ordem correta é (página, y0). Larguras distintas
    # (100/200/300 px = 75/150/225 pt) identificam cada imagem; imagens de mesma largura não
    # seriam distinguíveis por este teste.
    imagens = [
        ImagemExtraida(0, 0, png_sintetico(100, 600), "png"),
        ImagemExtraida(0, 1, png_sintetico(200, 600), "png"),
        ImagemExtraida(0, 2, png_sintetico(300, 600), "png"),
    ]

    pdf = gerar_pdf("Texto.", imagens)

    caixas = sorted(_caixas_das_imagens(pdf), key=lambda item: (item[0], item[1][1]))
    paginas = [pagina for pagina, _ in caixas]
    larguras = [round(x1 - x0) for (_, (x0, _, x1, _)) in caixas]
    assert len(set(paginas)) == 3
    assert larguras == [75, 150, 225]


# --- Imagens descartadas e conversão para PNG ---------------------------------------------------
# Os testes leem o PDF gerado (colocações e cor de cada imagem), não só as mensagens de log.

_VERMELHO = (200, 30, 30)
_VERDE = (30, 160, 60)
_AZUL = (20, 60, 200)


def _cores_das_colocacoes(conteudo_pdf: bytes) -> list[tuple[int, int, int]]:
    # Cor central de cada colocação no PDF final, na ordem (página, y0): identifica cada imagem
    # sólida pela cor, em vez de pela largura.
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        colocacoes: list[tuple[int, float, tuple[int, int, int]]] = []
        for numero_pagina in range(documento.page_count):
            for info in documento[numero_pagina].get_image_info(xrefs=True):
                pixmap = pymupdf.Pixmap(documento, info["xref"])
                cor = pixmap.pixel(pixmap.width // 2, pixmap.height // 2)[:3]
                colocacoes.append((numero_pagina, info["bbox"][1], (cor[0], cor[1], cor[2])))
        return [cor for _, _, cor in sorted(colocacoes)]
    finally:
        documento.close()


def _perto(cor: tuple[int, int, int], esperada: tuple[int, int, int], margem: int = 8) -> bool:
    return all(abs(a - b) <= margem for a, b in zip(cor, esperada, strict=True))


def _png(cor: tuple[int, int, int]) -> ImagemExtraida:
    return ImagemExtraida(0, 0, png_sintetico(40, 40, cor), "png")


def _pnm(cor: tuple[int, int, int], indice: int = 0) -> ImagemExtraida:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 40, 40), False)
    pixmap.set_rect(pixmap.irect, cor)
    return ImagemExtraida(0, indice, pixmap.tobytes("pnm"), "pnm")


# Amostras JPEG 2000 (8x8, sem perdas) embutidas para os testes não dependerem de uma biblioteca
# de imagem. Foram geradas uma única vez com Pillow 12.3.0 e conferidas por dois decodificadores
# independentes: Pillow (modo RGB/CMYK) e PyMuPDF (DeviceRGB e DeviceCMYK, sem alfa).
# RGB uniforme (30, 160, 60) e CMYK uniforme (0, 255, 255, 0).
_JPX_RGB_8X8_VERDE_BASE64 = (
    "AAAADGpQICANCocKAAAAFGZ0eXBqcDIgAAAAAGpwMiAAAAAtanAyaAAAABZpaGRyAAAACAAAAAgA"
    "AwcHAAAAAAAPY29scgEAAAAAABAAAACmanAyY/9P/1EALwAAAAAACAAAAAgAAAAAAAAAAAAAAAgA"
    "AAAIAAAAAAAAAAAAAwcBAQcBAQcBAf9SAAwAAAABAAMEBAAB/1wADUBASEhQSEhQSEhQ/2QAJQAB"
    "Q3JlYXRlZCBieSBPcGVuSlBFRyB2ZXJzaW9uIDIuNS40/5AACgAAAAAAJQAB/5PPtAgIn8fUAgTP"
    "tAgHL4CAgICAgICAgP/Z"
)

_JPX_CMYK_8X8_BASE64 = (
    "AAAADGpQICANCocKAAAAFGZ0eXBqcDIgAAAAAGpwMiAAAAAtanAyaAAAABZpaGRyAAAACAAAAAgA"
    "BAcHAAAAAAAPY29scgEAAAAAAAwAAACuanAyY/9P/1EAMgAAAAAACAAAAAgAAAAAAAAAAAAAAAgA"
    "AAAIAAAAAAAAAAAABAcBAQcBAQcBAQcBAf9SAAwAAAABAAMEBAAB/1wADUBASEhQSEhQSEhQ/2QA"
    "JQABQ3JlYXRlZCBieSBPcGVuSlBFRyB2ZXJzaW9uIDIuNS40/5AACgAAAAAAKgAB/5PfgAgHz7QE"
    "AM+0BADfgAgHgICAgICAgICAgICA/9k="
)


def _jpx_verde() -> ImagemExtraida:
    return ImagemExtraida(0, 0, base64.b64decode("".join(_JPX_RGB_8X8_VERDE_BASE64)), "jpx")


def _jpx_cmyk() -> ImagemExtraida:
    return ImagemExtraida(0, 0, base64.b64decode("".join(_JPX_CMYK_8X8_BASE64)), "jpx")


def _avisos(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        registro.getMessage()
        for registro in caplog.records
        if registro.name == gerador_pdf.__name__ and registro.levelno >= logging.WARNING
    ]


def test_formato_suportado_continua_incorporado_sem_aviso(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=gerador_pdf.__name__):
        pdf = gerar_pdf("Texto.", [_png(_VERMELHO)])

    cores = _cores_das_colocacoes(pdf)
    assert len(cores) == 1
    assert _perto(cores[0], _VERMELHO)
    assert _avisos(caplog) == []


@pytest.mark.parametrize("imagem", [_pnm(_VERDE), _jpx_verde()], ids=["pnm", "jpx"])
def test_formato_fora_da_lista_e_convertido_para_png_quando_a_conversao_funciona(
    imagem: ImagemExtraida, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger=gerador_pdf.__name__):
        pdf = gerar_pdf("Texto.", [imagem])

    cores = _cores_das_colocacoes(pdf)
    assert len(cores) == 1
    assert _perto(cores[0], _VERDE)
    assert _avisos(caplog) == []


def test_conversao_para_png_mantem_a_ordem_das_colocacoes() -> None:
    pdf = gerar_pdf("Texto.", [_png(_VERMELHO), _pnm(_VERDE), _png(_AZUL)])

    cores = _cores_das_colocacoes(pdf)
    assert len(cores) == 3
    assert [
        _perto(cor, esperada)
        for cor, esperada in zip(cores, (_VERMELHO, _VERDE, _AZUL), strict=True)
    ] == [True, True, True]


def test_formato_nao_validado_e_descartado_com_aviso_e_o_pdf_continua(
    caplog: pytest.LogCaptureFixture,
) -> None:
    jxr = ImagemExtraida(2, 5, b"bytes-qualquer", "jxr")

    with caplog.at_level(logging.WARNING, logger=gerador_pdf.__name__):
        pdf = gerar_pdf("Texto adaptado.", [_png(_VERMELHO), jxr, _png(_AZUL)])

    cores = _cores_das_colocacoes(pdf)
    assert len(cores) == 2
    assert _perto(cores[0], _VERMELHO)
    assert _perto(cores[1], _AZUL)
    (aviso,) = _avisos(caplog)
    assert "formato não suportado" in aviso
    assert "formato=jxr" in aviso
    assert "página=3" in aviso
    assert "índice=5" in aviso


def test_so_imagens_descartadas_nao_geram_secao_de_imagens_nem_falham() -> None:
    pdf = gerar_pdf("Texto adaptado.", [ImagemExtraida(0, 0, b"x", "jxr")])

    texto = "\n".join(_texto_por_pagina(pdf))
    assert "Texto adaptado." in texto
    assert "Imagens do material original" not in texto
    assert _contar_imagens(pdf) == 0


def test_falha_na_conversao_descarta_so_a_imagem_afetada(
    caplog: pytest.LogCaptureFixture,
) -> None:
    quebrada = ImagemExtraida(0, 1, b"isto nao e um pnm valido", "pnm")

    with caplog.at_level(logging.WARNING, logger=gerador_pdf.__name__):
        pdf = gerar_pdf("Texto.", [_png(_VERMELHO), quebrada, _png(_AZUL)])

    cores = _cores_das_colocacoes(pdf)
    assert len(cores) == 2
    assert _perto(cores[0], _VERMELHO)
    assert _perto(cores[1], _AZUL)
    (aviso,) = _avisos(caplog)
    assert "falha ao converter para PNG" in aviso
    assert "formato=pnm" in aviso
    assert "índice=1" in aviso


def test_jpx_em_cmyk_nao_e_convertido_e_so_essa_imagem_e_descartada(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Limitação conhecida: o PyMuPDF decodifica JPX CMYK, mas não o regrava como PNG
    # (ValueError). Não há suporte; a imagem é descartada com aviso e as demais seguem.
    with caplog.at_level(logging.WARNING, logger=gerador_pdf.__name__):
        pdf = gerar_pdf("Texto.", [_png(_VERMELHO), _jpx_cmyk(), _png(_AZUL)])

    cores = _cores_das_colocacoes(pdf)
    assert len(cores) == 2
    assert _perto(cores[0], _VERMELHO)
    assert _perto(cores[1], _AZUL)
    (aviso,) = _avisos(caplog)
    assert "falha ao converter para PNG" in aviso
    assert "formato=jpx" in aviso
    assert "erro=ValueError" in aviso


def test_falha_de_uma_imagem_nao_altera_o_resultado_das_demais() -> None:
    quebrada = ImagemExtraida(0, 1, b"isto nao e um pnm valido", "pnm")

    sem_falha = gerar_pdf("Texto.", [_png(_VERMELHO), _png(_AZUL)])
    com_falha = gerar_pdf("Texto.", [_png(_VERMELHO), quebrada, _png(_AZUL)])

    assert _caixas_das_imagens(com_falha) == _caixas_das_imagens(sem_falha)
    assert _cores_das_colocacoes(com_falha) == _cores_das_colocacoes(sem_falha)
    assert _texto_por_pagina(com_falha) == _texto_por_pagina(sem_falha)


def test_avisos_nao_expoem_bytes_conteudo_do_material_nem_mensagens_de_erro(
    caplog: pytest.LogCaptureFixture,
) -> None:
    segredo = b"PAYLOAD-SECRETO-DA-IMAGEM-12345"
    marcador = "TEXTO-PRIVADO-DO-MATERIAL-98765"
    imagens = [
        ImagemExtraida(0, 0, segredo, "jxr"),
        ImagemExtraida(0, 1, segredo, "pnm"),
        _png(_VERMELHO),
    ]

    with caplog.at_level(logging.DEBUG):
        pdf = gerar_pdf(f"Aluno confidencial: {marcador}.", imagens)

    assert len(_avisos(caplog)) == 2
    registro_completo = caplog.text + "".join(str(r.args) + r.getMessage() for r in caplog.records)
    assert segredo.decode() not in registro_completo
    assert marcador not in registro_completo
    assert "UEFZTE9BRC1TRUNSRVRP" not in registro_completo  # início do base64 do segredo
    assert repr(segredo) not in registro_completo
    # O comportamento real continua correto apesar das duas descartadas.
    assert marcador in _sem_espacos("\n".join(_texto_por_pagina(pdf)))
    assert _contar_imagens(pdf) == 1


def test_extensao_inesperada_nao_polui_o_log_nem_e_embutida(
    caplog: pytest.LogCaptureFixture,
) -> None:
    estranha = ImagemExtraida(0, 0, b"x", "png;base64,AAAA\nINJETADO")

    with caplog.at_level(logging.WARNING, logger=gerador_pdf.__name__):
        pdf = gerar_pdf("Texto.", [estranha, _png(_VERMELHO)])

    (aviso,) = _avisos(caplog)
    assert "formato=invalido" in aviso
    assert "INJETADO" not in aviso
    assert "\n" not in aviso
    assert _contar_imagens(pdf) == 1
