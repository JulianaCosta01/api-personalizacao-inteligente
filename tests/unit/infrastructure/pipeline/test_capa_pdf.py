import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pymupdf
import pytest

from infrastructure.pipeline import gerador_pdf
from infrastructure.pipeline.extrator import ImagemExtraida
from infrastructure.pipeline.gerador_pdf import gerar_pdf

from .pdf_fixture import png_sintetico

_PARAGRAFO_LONGO = (
    "Este material apresenta os conceitos fundamentais de lógica proposicional, com exemplos "
    "e exercícios adaptados ao estilo de estudo."
)


def _paginas(conteudo_pdf: bytes) -> list[str]:
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        return [documento[numero].get_text() for numero in range(documento.page_count)]
    finally:
        documento.close()


def _titulo_do_pdf(conteudo_pdf: bytes) -> str:
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        return str((documento.metadata or {}).get("title", ""))
    finally:
        documento.close()


def _colocacoes_por_pagina(conteudo_pdf: bytes) -> list[int]:
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        return [len(documento[numero].get_image_info()) for numero in range(documento.page_count)]
    finally:
        documento.close()


def _larguras_das_imagens(conteudo_pdf: bytes) -> list[int]:
    # Largura (arredondada) de cada colocação, na ordem de página e de aparição.
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        return [
            round(info["bbox"][2] - info["bbox"][0])
            for numero in range(documento.page_count)
            for info in documento[numero].get_image_info()
        ]
    finally:
        documento.close()


def _sem_rodape(texto: str) -> str:
    return "\n".join(linha for linha in texto.splitlines() if not linha.startswith("Página "))


def _imagem(cor: int) -> ImagemExtraida:
    return ImagemExtraida(
        numero_pagina=0,
        indice_na_pagina=cor,
        conteudo=png_sintetico(120 + cor, 80),
        extensao="png",
    )


@contextmanager
def _bloqueia_conexoes_de_rede() -> Iterator[None]:
    def _levantar(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Nenhuma conexão de rede deveria ser aberta durante a geração do PDF.")

    with patch("socket.socket.connect", side_effect=_levantar):
        yield


# Estrutura e identificação


def test_capa_e_a_primeira_pagina_e_traz_a_identificacao_institucional() -> None:
    pdf = gerar_pdf(f"# Lógica Proposicional\n\n{_PARAGRAFO_LONGO}\n\n## Conceitos\n\nCorpo.")

    capa = _paginas(pdf)[0]

    assert "UNIVERSIDADE" in capa
    assert "FEDERAL DO" in capa
    assert "MARANHÃO" in capa
    assert "CCIA" in capa
    # O nome do curso quebra em linhas conforme a largura da coluna; compara sem as quebras.
    assert "Ciência da Computação e Inteligência Artificial | UFMA" in " ".join(capa.split())
    # O título quebra em linhas conforme o tamanho da fonte; compara sem as quebras.
    assert "Lógica Proposicional" in " ".join(capa.split())


def test_capa_ocupa_uma_pagina_e_o_corpo_comeca_na_seguinte() -> None:
    pdf = gerar_pdf("# Título\n\nCorpo curto.")

    paginas = _paginas(pdf)

    assert len(paginas) == 2
    assert "Corpo curto." not in paginas[0]
    assert "Corpo curto." in paginas[1]


def test_capa_nao_tem_rodape_de_paginacao_e_o_corpo_segue_a_pagina_fisica() -> None:
    paragrafos = [f"Parágrafo {i}: " + "texto de preenchimento " * 18 for i in range(80)]

    pdf = gerar_pdf("# Documento longo\n\n" + "\n\n".join(paragrafos))

    paginas = _paginas(pdf)
    total = len(paginas)
    assert total >= 4
    assert "Página" not in paginas[0]
    for numero, texto in enumerate(paginas[1:], start=2):
        assert f"Página {numero} de {total}" in texto


def test_capa_nao_usa_texto_de_lema_nao_confirmado() -> None:
    capa = _paginas(gerar_pdf("# Título\n\nCorpo."))[0].lower()

    assert "tecnologia que impulsiona" not in capa
    assert "baseado no seu perfil" not in capa


def test_pdf_com_capa_declara_titulo_nos_metadados() -> None:
    pdf = gerar_pdf("# Redes de Computadores\n\nCorpo.")

    assert _titulo_do_pdf(pdf) == "Redes de Computadores"


# Título e subtítulo dinâmicos


def test_sem_titulo_usa_o_fallback_seguro() -> None:
    pdf = gerar_pdf("Apenas um parágrafo, sem título algum no conteúdo.\n\n## Seção\n\nTexto.")

    assert "Material Didático" in " ".join(_paginas(pdf)[0].split())
    assert _titulo_do_pdf(pdf) == "Material Didático"


def test_titulo_dentro_de_bloco_de_codigo_e_ignorado() -> None:
    pdf = gerar_pdf("```\n# Comentário de código\n```\n\n# Título Verdadeiro\n\nTexto.")

    assert _titulo_do_pdf(pdf) == "Título Verdadeiro"


def test_titulo_remove_marcacao_markdown_e_html() -> None:
    titulo, _ = gerador_pdf._dados_da_capa(
        "# **Algoritmos** e `Dados` [guia](http://x.test/a) <b>I</b> ![i](http://x.test/i.png)\n"
    )

    assert titulo == "Algoritmos e Dados guia I"


def test_titulo_muito_longo_e_truncado_e_a_capa_continua_em_uma_pagina() -> None:
    longo = "Fundamentos de Algoritmos e Estruturas de Dados " * 6

    pdf = gerar_pdf(f"# {longo}\n\n{_PARAGRAFO_LONGO}\n\nCorpo.")

    titulo = _titulo_do_pdf(pdf)
    assert len(titulo) <= gerador_pdf._TAMANHO_MAXIMO_DO_TITULO + 1
    assert titulo.endswith("…")
    paginas = _paginas(pdf)
    assert len(paginas) == 2
    assert "CIÊNCIA DA COMPUTAÇÃO E INTELIGÊNCIA ARTIFICIAL" not in paginas[0]
    assert "CIÊNCIA DA COMPUTAÇÃO E INTELIGÊNCIA ARTIFICIAL" not in paginas[1]


def test_titulo_sem_espacos_nao_quebra_a_geracao() -> None:
    pdf = gerar_pdf("# " + "A" * 300 + "\n\nCorpo.")

    assert pdf.startswith(b"%PDF-")
    assert len(_paginas(pdf)) == 2


@pytest.mark.parametrize(
    ("titulo", "esperado"),
    [
        ("Redes", 40.0),
        ("Um título de tamanho médio para o material", 32.0),
        ("Estudos de caso em lógica para um material didático de apoio", 25.0),
        ("Um título extremamente longo " * 4, 20.0),
    ],
)
def test_tamanho_do_titulo_diminui_com_o_comprimento(titulo: str, esperado: float) -> None:
    assert (
        gerador_pdf._tamanho_do_titulo(titulo[: gerador_pdf._TAMANHO_MAXIMO_DO_TITULO]) == esperado
    )


def test_tamanho_do_titulo_respeita_a_maior_palavra_e_tem_piso() -> None:
    assert gerador_pdf._tamanho_do_titulo("Lógica Proposicional") < 40.0
    assert gerador_pdf._tamanho_do_titulo("A" * 300) == gerador_pdf._TAMANHO_MINIMO_DO_TITULO_EM_PT
    assert gerador_pdf._tamanho_do_titulo("") == 40.0


@pytest.mark.parametrize(
    "titulo",
    [
        "Lógica Proposicional",
        "Programação Orientada a Objetos",
        "Eletromagnetismo Computacional",
        "Inteligência Artificial Generativa Aplicada à Educação Superior Brasileira",
    ],
)
def test_nenhuma_palavra_do_titulo_e_quebrada_no_meio_na_capa(titulo: str) -> None:
    capa = _paginas(gerar_pdf(f"# {titulo}\n\nCorpo."))[0]

    linhas = [linha.strip() for linha in capa.splitlines()]
    for palavra in titulo.split():
        assert any(palavra in linha.split() for linha in linhas), palavra


def test_subtitulo_e_o_primeiro_paragrafo_de_texto_corrido_apos_o_titulo() -> None:
    _, subtitulo = gerador_pdf._dados_da_capa(f"# Título\n\n{_PARAGRAFO_LONGO}\n\nOutro parágrafo.")

    assert subtitulo == _PARAGRAFO_LONGO


def test_subtitulo_aparece_na_capa() -> None:
    pdf = gerar_pdf(f"# Título\n\n{_PARAGRAFO_LONGO}\n")

    capa = " ".join(_paginas(pdf)[0].split())
    assert "fundamentais de lógica proposicional" in capa


def test_subtitulo_longo_e_truncado_em_palavra_com_reticencias() -> None:
    texto = "palavra " * 60

    _, subtitulo = gerador_pdf._dados_da_capa(f"# Título\n\n{texto}\n")

    assert subtitulo is not None
    assert subtitulo.endswith("…")
    assert len(subtitulo) <= gerador_pdf._TAMANHO_MAXIMO_DO_SUBTITULO + 1


@pytest.mark.parametrize(
    "corpo",
    [
        "Curto demais.",
        "- item de lista que é longo o bastante para passar do mínimo de caracteres exigido",
        "| coluna A | coluna B |\n| --- | --- |\n| um valor longo o bastante | outro valor |",
        "> citação em bloco que é longa o bastante para passar do mínimo de caracteres exigido",
        "## Subtítulo de seção que é longo o bastante para passar do mínimo de caracteres",
        "```\ncódigo que é longo o bastante para passar do mínimo de caracteres exigido\n```",
        "![figura](http://x.test/i.png)",
    ],
)
def test_sem_paragrafo_adequado_a_capa_fica_sem_subtitulo(corpo: str) -> None:
    _, subtitulo = gerador_pdf._dados_da_capa(f"# Título\n\n{corpo}\n")

    assert subtitulo is None


def test_subtitulo_pula_blocos_nao_textuais_e_usa_o_primeiro_paragrafo_adequado() -> None:
    markdown = f"# Título\n\n- lista\n\nCurto.\n\n{_PARAGRAFO_LONGO}\n"

    _, subtitulo = gerador_pdf._dados_da_capa(markdown)

    assert subtitulo == _PARAGRAFO_LONGO


# Segurança


def test_texto_dinamico_da_capa_e_escapado_e_nao_vira_marcacao() -> None:
    hostil = '# <img src="x" onerror="1"> & "<i>Título</i>" <script>alert(1)</script>\n'

    capa_html = gerador_pdf._renderizar_capa(*gerador_pdf._dados_da_capa(hostil + "\nTexto.\n"))

    assert "<script" not in capa_html
    assert "<img" not in capa_html.replace('<img class="', "")
    assert "onerror" not in capa_html


def test_titulo_e_subtitulo_com_caracteres_especiais_sao_escapados_no_html() -> None:
    capa_html = gerador_pdf._renderizar_capa('A & B "C"', "Fórmula x < y && y > z, ok mesmo assim")

    assert "A &amp; B &quot;C&quot;" in capa_html
    assert "x &lt; y &amp;&amp; y &gt; z" in capa_html


def test_geracao_com_capa_nao_abre_conexao_de_rede() -> None:
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf(
            f"# Título\n\n{_PARAGRAFO_LONGO}\n\n![x](http://exemplo-externo.test/x.png)\n",
            [_imagem(0)],
        )

    assert pdf.startswith(b"%PDF-")


def test_titulo_com_script_gera_pdf_sem_executar_nem_propagar_marcacao() -> None:
    pdf = gerar_pdf("# <script>alert(1)</script> Título\n\nTexto.")

    assert "<script" not in _paginas(pdf)[0]
    assert pdf.startswith(b"%PDF-")


# Preservação do conteúdo e das imagens


def test_corpo_com_capa_tem_o_mesmo_texto_que_sem_capa() -> None:
    markdown = (
        "# Título\n\n"
        + _PARAGRAFO_LONGO
        + "\n\n## Tabela\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n- Item um\n- Item dois\n\n"
        "> Citação importante.\n\n```\ncódigo de exemplo\n```\n"
    )

    com_capa = _paginas(gerar_pdf(markdown))
    sem_capa = _paginas(gerar_pdf(markdown, incluir_capa=False))

    corpo_com_capa = "\n".join(_sem_rodape(texto) for texto in com_capa[1:])
    corpo_sem_capa = "\n".join(_sem_rodape(texto) for texto in sem_capa)
    assert corpo_com_capa == corpo_sem_capa


def test_geracao_sem_capa_continua_suportada_e_nao_traz_elementos_da_capa() -> None:
    pdf = gerar_pdf("# Título\n\nCorpo curto.", incluir_capa=False)

    paginas = _paginas(pdf)
    assert len(paginas) == 1
    assert "UNIVERSIDADE" not in paginas[0]
    assert "Página 1 de 1" in paginas[0]


def test_capa_e_ligada_por_padrao() -> None:
    assert "UNIVERSIDADE" in _paginas(gerar_pdf("# Título\n\nCorpo."))[0]


def test_unica_imagem_da_capa_e_a_logo_e_o_corpo_nao_tem_imagens() -> None:
    # O fundo da capa é SVG (vetorial, não conta como imagem); a única colocação rasterizada é a
    # logo oficial da UFMA.
    pdf = gerar_pdf("# Título\n\nCorpo sem imagens.")

    assert _colocacoes_por_pagina(pdf) == [1, 0]


def test_imagens_originais_sao_preservadas_com_capa_na_mesma_quantidade_e_ordem() -> None:
    imagens = [_imagem(0), _imagem(1), _imagem(2)]

    com_capa = gerar_pdf("# Título\n\nCorpo.", imagens)
    sem_capa = gerar_pdf("# Título\n\nCorpo.", imagens, incluir_capa=False)

    por_pagina = _colocacoes_por_pagina(com_capa)
    assert por_pagina[0] == 1  # só a logo da UFMA
    assert sum(por_pagina[1:]) == 3 == sum(_colocacoes_por_pagina(sem_capa))
    # A primeira colocação do PDF com capa é a logo; as demais são as imagens originais.
    assert _larguras_das_imagens(com_capa)[1:] == _larguras_das_imagens(sem_capa)


def test_conteudo_vazio_ainda_gera_pdf_valido_com_capa() -> None:
    pdf = gerar_pdf("")

    paginas = _paginas(pdf)
    assert pdf.startswith(b"%PDF-")
    assert "Material Didático" in " ".join(paginas[0].split())


def test_nao_vaza_conteudo_pessoal_na_capa_por_padrao() -> None:
    # A capa só recebe o Markdown adaptado; nenhum campo de aluno ou perfil é aceito por
    # gerar_pdf, então nada além do título/subtítulo derivados do texto pode aparecer.
    pdf = gerar_pdf("# Título\n\nCorpo.")

    capa = _paginas(pdf)[0].lower()
    assert "aluno" not in capa
    assert "perfil" not in capa


# Logo oficial da UFMA

# SHA-256 do arquivo da logo versionado no repositório (recorte circular do arquivo enviado pelo
# projeto). Se a logo for substituída (por exemplo, pelo arquivo vetorial oficial), atualizar aqui
# de propósito: o teste existe para que a logo nunca mude por acidente.
_SHA256_DA_LOGO = "e7fd952073fc76a4643889f3657f4a7badb0a8f61b16a420d1f8fa34e4009acd"


@pytest.fixture
def _sem_cache_da_logo() -> Iterator[None]:
    gerador_pdf._logo_ufma_data_uri.cache_clear()
    yield
    gerador_pdf._logo_ufma_data_uri.cache_clear()


def _colocacoes_da_primeira_pagina(conteudo_pdf: bytes) -> list[dict[str, Any]]:
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        return list(documento[0].get_image_info())
    finally:
        documento.close()


def test_arquivo_da_logo_e_o_oficial_versionado_e_nao_foi_alterado() -> None:
    conteudo = gerador_pdf._CAMINHO_DA_LOGO_UFMA.read_bytes()

    assert conteudo.startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(conteudo).hexdigest() == _SHA256_DA_LOGO


def test_logo_esta_na_regiao_superior_da_capa_com_proporcao_original() -> None:
    (logo,) = _colocacoes_da_primeira_pagina(gerar_pdf("# Título\n\nCorpo."))

    caixa = pymupdf.Rect(logo["bbox"])
    assert abs(caixa.width - caixa.height) < 0.5  # logo quadrada (604x604): sem distorção
    assert logo["width"] == logo["height"] == 604  # resolução original, sem reamostrar
    assert caixa.y0 < 25 * _MM_EM_PT  # região superior
    assert caixa.x0 >= 15 * _MM_EM_PT
    assert 25 * _MM_EM_PT <= caixa.width <= 40 * _MM_EM_PT  # tamanho adequado, não dominante


_MM_EM_PT = 72 / 25.4


def test_logo_nao_aparece_nas_paginas_do_corpo() -> None:
    pdf = gerar_pdf("# Título\n\nCorpo.")

    assert _colocacoes_por_pagina(pdf)[1:] == [0]


def test_sem_o_arquivo_da_logo_a_capa_sai_so_com_texto_e_registra_aviso(
    _sem_cache_da_logo: None, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    with (
        patch.object(gerador_pdf, "_CAMINHO_DA_LOGO_UFMA", tmp_path / "inexistente.png"),
        caplog.at_level(logging.WARNING, logger=gerador_pdf.__name__),
    ):
        pdf = gerar_pdf("# Título\n\nCorpo.")

    capa = _paginas(pdf)[0]
    assert pdf.startswith(b"%PDF-")
    assert "UNIVERSIDADE" in capa
    assert _colocacoes_por_pagina(pdf)[0] == 0
    avisos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Logo da UFMA" in aviso for aviso in avisos)
    assert str(tmp_path) not in " ".join(avisos)


def test_arquivo_da_logo_que_nao_e_png_e_ignorado(_sem_cache_da_logo: None, tmp_path: Path) -> None:
    falso = tmp_path / "logo.png"
    falso.write_bytes(b"<svg onload=alert(1)></svg>")

    with patch.object(gerador_pdf, "_CAMINHO_DA_LOGO_UFMA", falso):
        pdf = gerar_pdf("# Título\n\nCorpo.")

    assert _colocacoes_por_pagina(pdf)[0] == 0


# Identidade visual no corpo


def _rgb(cor: int) -> tuple[int, int, int]:
    return (cor >> 16) & 255, (cor >> 8) & 255, cor & 255


def _hex_para_rgb(valor: str) -> tuple[int, int, int]:
    return int(valor[1:3], 16), int(valor[3:5], 16), int(valor[5:7], 16)


def _cores_dos_textos(conteudo_pdf: bytes, pagina: int) -> dict[str, tuple[int, int, int]]:
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        cores: dict[str, tuple[int, int, int]] = {}
        for bloco in documento[pagina].get_text("dict")["blocks"]:
            for linha in bloco.get("lines", []):
                for trecho in linha["spans"]:
                    cores[trecho["text"].strip()] = _rgb(trecho["color"])
        return cores
    finally:
        documento.close()


def _cores_desenhadas(conteudo_pdf: bytes, pagina: int) -> set[tuple[int, int, int]]:
    documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    try:
        cores: set[tuple[int, int, int]] = set()
        for desenho in documento[pagina].get_drawings():
            for chave in ("fill", "color"):
                valor = desenho.get(chave)
                if valor and len(valor) == 3:
                    cores.add(tuple(round(c * 255) for c in valor))
        return cores
    finally:
        documento.close()


_CORPO_ESTILIZADO = (
    "# Título Um\n\n## Título Dois\n\n### Título Três\n\n#### Rótulo Quatro\n\n"
    "Parágrafo comum de texto corrido.\n\n> Observação importante.\n\n"
    "| A | B |\n| - | - |\n| 1 | 2 |\n\n---\n\n```\ncodigo\n```\n"
)


def test_titulos_usam_vinho_e_texto_corrido_usa_grafite() -> None:
    pdf = gerar_pdf(_CORPO_ESTILIZADO)

    cores = _cores_dos_textos(pdf, 1)
    vinho = _hex_para_rgb(gerador_pdf._COR_VINHO)
    for titulo in ("Título Um", "Título Dois", "Título Três"):
        assert cores[titulo] == vinho, titulo
    assert cores["Parágrafo comum de texto corrido."] == _hex_para_rgb(gerador_pdf._COR_GRAFITE)
    assert cores["Rótulo Quatro"] == _hex_para_rgb(gerador_pdf._COR_TURQUESA_TEXTO)


def test_caixa_de_observacao_e_cabecalho_de_tabela_usam_fundo_creme() -> None:
    pdf = gerar_pdf(_CORPO_ESTILIZADO)

    assert _hex_para_rgb(gerador_pdf._COR_CREME) in _cores_desenhadas(pdf, 1)


def test_divisores_usam_dourado_e_detalhes_de_codigo_usam_turquesa() -> None:
    cores = _cores_desenhadas(gerar_pdf(_CORPO_ESTILIZADO), 1)

    assert _hex_para_rgb(gerador_pdf._COR_DOURADO) in cores
    assert _hex_para_rgb(gerador_pdf._COR_TURQUESA) in cores


def test_corpo_nao_usa_mais_a_paleta_azul_anterior() -> None:
    pdf = gerar_pdf(_CORPO_ESTILIZADO)

    todas = _cores_desenhadas(pdf, 1) | set(_cores_dos_textos(pdf, 1).values())
    assert _hex_para_rgb("#1b3a5c") not in todas
    assert _hex_para_rgb("#e4ebf2") not in todas


def test_cabecalho_institucional_nao_aparece_em_nenhuma_pagina() -> None:
    pdf = gerar_pdf("# Título\n\nCorpo.")

    documento = pymupdf.open(stream=pdf, filetype="pdf")
    try:

        def no_cabecalho(numero: int) -> bool:
            return any(
                "UFMA · CCIA" in palavra[4] or palavra[4] == "UFMA"
                for palavra in documento[numero].get_text("words")
                if palavra[1] < 20 * _MM_EM_PT
            )

        assert not no_cabecalho(1)
        assert not no_cabecalho(0)
    finally:
        documento.close()


def test_capa_nao_tem_rodape_institucional_repetido() -> None:
    pdf = gerar_pdf("# Título\n\nCorpo.")

    capa = _paginas(pdf)[0]
    assert "UFMA · CCIA" not in capa
    assert "capa-rodape" not in gerador_pdf._FOLHA_DE_ESTILO_CAPA


def test_texto_do_corpo_e_justificado_e_o_da_capa_nao() -> None:
    assert "text-align: justify" in gerador_pdf._FOLHA_DE_ESTILO
    assert ".capa p { text-align: left" in gerador_pdf._FOLHA_DE_ESTILO_CAPA


def _luminancia(cor: tuple[int, int, int]) -> float:
    def canal(valor: int) -> float:
        c = valor / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = cor
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def _contraste(frente: str, fundo: str) -> float:
    claro, escuro = sorted((_luminancia(_hex_para_rgb(frente)), _luminancia(_hex_para_rgb(fundo))))[
        ::-1
    ]
    return (claro + 0.05) / (escuro + 0.05)


@pytest.mark.parametrize(
    ("texto", "fundo"),
    [
        (gerador_pdf._COR_GRAFITE, "#FFFFFF"),
        (gerador_pdf._COR_GRAFITE, gerador_pdf._COR_CREME),
        (gerador_pdf._COR_VINHO, "#FFFFFF"),
        (gerador_pdf._COR_VINHO, gerador_pdf._COR_CREME),
        (gerador_pdf._COR_TURQUESA_TEXTO, "#FFFFFF"),
        (gerador_pdf._COR_TURQUESA_TEXTO, gerador_pdf._COR_CREME),
        (gerador_pdf._COR_RODAPE, "#FFFFFF"),
    ],
)
def test_pares_de_cores_de_texto_tem_contraste_wcag_aa(texto: str, fundo: str) -> None:
    assert _contraste(texto, fundo) >= 4.5


def test_dourado_e_turquesa_decorativos_nao_sao_usados_como_cor_de_texto() -> None:
    cores_de_texto = set(_cores_dos_textos(gerar_pdf(_CORPO_ESTILIZADO), 1).values())

    assert _hex_para_rgb(gerador_pdf._COR_DOURADO) not in cores_de_texto
    assert _hex_para_rgb(gerador_pdf._COR_TURQUESA) not in cores_de_texto
