import inspect
import re
from typing import Any
from unittest.mock import patch

import pymupdf
import pytest

from application.ports.gerador_imagens import (
    ConceitoVisual,
    FalhaGeracaoImagem,
    ImagemGerada,
    MotivoFalhaImagem,
)
from domain.shared.exceptions import EntradaInvalidaError
from infrastructure.pipeline import gerador_pdf
from infrastructure.pipeline.conceitos_visuais import marcador_de_ancora
from infrastructure.pipeline.erros import ErroDePipeline
from infrastructure.pipeline.extrator import ImagemExtraida
from infrastructure.pipeline.gerador_pdf import (
    gerar_pdf,
    gerar_pdf_com_imagens_geradas,
    montar_documento_html,
    montar_documento_html_com_imagens_geradas,
)
from infrastructure.pipeline.imagens_geradas import (
    _PADRAO_LINHA_DE_ANCORA,
    ImagensGeradasDoMaterial,
    posicionar_imagens,
)
from tests.unit.application.ports.imagens_fixture import jpeg_valido, png_valido

from .pdf_fixture import png_sintetico

_ALT = "Grafo com três nós"


def _conceito(identificador: str, descricao: str = "Grafo com três nós ligados") -> ConceitoVisual:
    return ConceitoVisual(identificador, descricao, identificador)


def _png(alt: str = _ALT) -> ImagemGerada:
    return ImagemGerada(png_valido(), alt)


def _jpeg(alt: str = _ALT) -> ImagemGerada:
    return ImagemGerada(jpeg_valido(), alt)


def _ancora(identificador: str) -> str:
    return marcador_de_ancora(identificador)


def _material(*partes: str) -> str:
    return "\n\n".join(("# Título do material", *partes))


def _imagens(conceitos: list[ConceitoVisual], resultados: list[Any]) -> ImagensGeradasDoMaterial:
    return ImagensGeradasDoMaterial(tuple(conceitos), tuple(resultados))


def _html(markdown: str, imagens: ImagensGeradasDoMaterial | None, **kw: Any) -> str:
    return montar_documento_html_com_imagens_geradas(markdown, imagens, incluir_capa=False, **kw)


def _srcs(html: str) -> list[str]:
    return re.findall(r'src="([^"]*)"', html)


def _imagem_real(formato: str) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
    pix.clear_with(180)
    return pix.tobytes(formato)


def _texto_do_pdf(pdf: bytes) -> str:
    documento = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        return " ".join(documento[i].get_text() for i in range(documento.page_count))
    finally:
        documento.close()


def _n_imagens_no_pdf(pdf: bytes) -> int:
    documento = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        return sum(len(documento[i].get_images()) for i in range(documento.page_count))
    finally:
        documento.close()


# Posicionamento


def test_png_e_jpeg_ficam_na_ancora_correta() -> None:
    md = _material("Antes.", _ancora("a"), "Meio.", _ancora("b"), "Depois.")
    imagens = _imagens([_conceito("a"), _conceito("b")], [_png("Alt PNG"), _jpeg("Alt JPEG")])

    html = _html(md, imagens)

    assert html.count("<img") == 2
    i_antes, i_png, i_meio = html.index("Antes."), html.index("data:image/png"), html.index("Meio.")
    i_jpeg, i_depois = html.index("data:image/jpeg"), html.index("Depois.")
    assert i_antes < i_png < i_meio < i_jpeg < i_depois
    assert 'alt="Alt PNG"' in html and 'alt="Alt JPEG"' in html


def test_varias_imagens_em_pontos_distintos_mantem_a_ordem_do_texto() -> None:
    md = _material("P1.", _ancora("c"), "P2.", _ancora("a"), "P3.", _ancora("b"), "P4.")
    imagens = _imagens(
        [_conceito("a"), _conceito("b"), _conceito("c")],
        [_png("alt-a"), _jpeg("alt-b"), _png("alt-c")],
    )

    html = _html(md, imagens)

    posicoes = [html.index(f'alt="alt-{x}"') for x in "cab"]  # ordem das âncoras no texto
    assert posicoes == sorted(posicoes)
    assert html.index("P1.") < posicoes[0] < html.index("P2.") < posicoes[1]
    assert posicoes[1] < html.index("P3.") < posicoes[2] < html.index("P4.")


def test_a_imagem_de_cada_conceito_vai_para_a_propria_ancora() -> None:
    md = _material(_ancora("b"), "Texto.", _ancora("a"))
    imagens = _imagens([_conceito("a"), _conceito("b")], [_png("alt-a"), _jpeg("alt-b")])

    html = _html(md, imagens)

    assert html.index('alt="alt-b"') < html.index("Texto.") < html.index('alt="alt-a"')


def test_conceito_sem_imagem_gerada_mantem_o_texto_e_remove_a_ancora() -> None:
    md = _material("Antes.", _ancora("a"), "Depois.")
    falha = FalhaGeracaoImagem("a", MotivoFalhaImagem.TIMEOUT)

    for resultados in ([falha], []):
        html = _html(md, _imagens([_conceito("a")], resultados))
        assert "<img" not in html and "mpi-ancora" not in html
        assert html.index("Antes.") < html.index("Depois.")


def test_imagem_gerada_sem_ancora_correspondente_nao_aparece() -> None:
    md = _material("Só texto.")
    html = _html(md, _imagens([_conceito("a")], [_png()]))
    assert "<img" not in html and "data:image" not in html
    assert "Só texto." in html


def test_ancora_desconhecida_e_removida() -> None:
    md = _material("Antes.", _ancora("zzz"), "Depois.")
    html = _html(md, _imagens([_conceito("a")], [_png()]))
    assert "mpi-ancora" not in html and "<img" not in html
    assert "Antes." in html and "Depois." in html


def test_ancora_duplicada_recebe_a_imagem_uma_unica_vez() -> None:
    md = _material("Antes.", _ancora("a"), "Meio.", _ancora("a"), "Depois.")
    html = _html(md, _imagens([_conceito("a")], [_png("unica")]))
    assert html.count("<img") == 1
    assert html.index("Antes.") < html.index("unica") < html.index("Meio.")
    assert "mpi-ancora" not in html


def test_ancora_em_codigo_nao_recebe_imagem() -> None:
    md = _material("```", _ancora("a"), "```", "Depois.")
    html = _html(md, _imagens([_conceito("a")], [_png()]))
    assert "<img" not in html
    assert "Depois." in html


def test_ancora_fora_de_linha_propria_nao_recebe_imagem_e_some() -> None:
    md = _material(f"Texto {_ancora('a')} no meio.")
    html = _html(md, _imagens([_conceito("a")], [_png()]))
    assert "<img" not in html and "mpi-ancora" not in html
    assert "Texto" in html and "no meio." in html


def test_ancora_recuada_dentro_de_lista_nao_deixa_token_e_nao_quebra() -> None:
    md = _material("- item um", f"  {_ancora('a')}", "Depois.")
    html = _html(md, _imagens([_conceito("a")], [_png()]))
    assert "MPIFIG" not in html and "mpi-ancora" not in html
    assert "item um" in html and "Depois." in html


# Segurança


def test_texto_alternativo_com_html_e_escapado() -> None:
    alt = "<script>alert(1)</script> \"x\" & 'y' <img src=//evil.test/a.png>"
    html = _html(_material(_ancora("a")), _imagens([_conceito("a")], [_png(alt)]))

    assert "<script>" not in html and "evil.test" not in html.replace("&lt;img src=//evil.test", "")
    assert "&lt;script&gt;" in html and "&quot;x&quot;" in html and "&amp;" in html
    assert html.count("<img") == 1  # só a imagem montada pelo módulo


def test_bytes_invalidos_nao_viram_imagem_e_o_texto_fica() -> None:
    imagem = _png()
    object.__setattr__(imagem, "conteudo", b"\x89PNG\r\n\x1a\nlixo-sem-estrutura")
    html = _html(_material("Antes.", _ancora("a"), "Depois."), _imagens([_conceito("a")], [imagem]))
    assert "<img" not in html and "data:image" not in html
    assert "Antes." in html and "Depois." in html and "mpi-ancora" not in html


def test_conteudo_que_nao_e_bytes_nao_vira_imagem() -> None:
    imagem = _png()
    object.__setattr__(imagem, "conteudo", "/etc/passwd")
    html = _html(_material(_ancora("a")), _imagens([_conceito("a")], [imagem]))
    assert "<img" not in html and "passwd" not in html


def test_descricao_do_conceito_nunca_chega_ao_documento() -> None:
    hostil = '<img src="http://evil.test/x.png" onerror=alert(1)> http://evil.test/'
    conceito = ConceitoVisual("a", hostil, "a")
    html = _html(_material(_ancora("a")), _imagens([conceito], [_png()]))
    assert "evil.test" not in html and "onerror" not in html


def test_marcador_com_html_ou_url_na_descricao_e_removido_sem_virar_imagem() -> None:
    md = _material(
        "Antes.",
        "[[IMAGEM:x1|<img src=http://evil.test/a.png onerror=alert(1)>]]",
        "[[IMAGEM:x2|veja http://evil.test/a.png agora]]",
        "Depois.",
    )
    html = _html(md, _imagens([_conceito("a")], [_png()]))
    assert "evil.test" not in html and "IMAGEM" not in html and "<img" not in html
    assert "Antes." in html and "Depois." in html


def test_unica_origem_de_imagem_sao_uris_data_png_ou_jpeg() -> None:
    md = _material(_ancora("a"), _ancora("b"), "[[IMAGEM:c|Qualquer descrição aqui]]")
    imagens = _imagens([_conceito("a"), _conceito("b")], [_png(), _jpeg()])

    srcs = _srcs(_html(md, imagens))

    assert len(srcs) == 2
    assert all(re.fullmatch(r"data:image/(png|jpeg);base64,[A-Za-z0-9+/]+={0,2}", s) for s in srcs)


def test_conteudo_original_nao_consegue_forjar_a_imagem_de_outro_conceito() -> None:
    # Uma âncora forjada com o identificador de um conceito com imagem só marca uma posição: a
    # imagem sempre vem do resultado do conceito, nunca do texto.
    md = _material("Texto com <!--mpi-ancora:a--> forjada.", "Fim.")
    html = _html(md, _imagens([_conceito("a")], [_png()]))
    assert "<img" not in html and "mpi-ancora" not in html


def test_conteudo_com_o_prefixo_do_token_nao_e_afetado() -> None:
    md = _material("Texto MPIFIG0123456789abcdefN0 comum.", _ancora("a"))
    html = _html(md, _imagens([_conceito("a")], [_png()]))
    assert "MPIFIG0123456789abcdefN0" in html
    assert html.count("<img") == 1


def test_tokens_mudam_a_cada_chamada() -> None:
    md = _material(_ancora("a"))
    imagens = _imagens([_conceito("a")], [_png()])
    a = posicionar_imagens(md, imagens).markdown
    b = posicionar_imagens(md, imagens).markdown
    assert a != b


# Marcadores e âncoras fora do resultado final


def test_nenhum_marcador_ou_ancora_no_html_final() -> None:
    md = _material(
        "[[IMAGEM:m1|Descrição válida de uma cena]]",
        _ancora("a"),
        "Texto [[IMAGEM:m2|inline]] e <!--mpi-ancora:q--> fim.",
        _ancora("fantasma"),
        "[[IMAGEM:aberto",
    )
    html = _html(md, _imagens([_conceito("a")], [_png()]))
    for proibido in ("IMAGEM", "mpi-ancora", "MPIFIG", "[["):
        assert proibido not in html
    assert html.count("<img") == 1


def test_nenhum_marcador_ou_ancora_no_pdf_final() -> None:
    md = _material(
        "Primeiro.",
        _ancora("a"),
        "[[IMAGEM:m1|Descrição válida de uma cena]]",
        _ancora("fantasma"),
        "Último.",
    )
    imagens = _imagens([_conceito("a")], [ImagemGerada(_imagem_real("png"), _ALT)])

    pdf = gerar_pdf_com_imagens_geradas(md, imagens)
    texto = _texto_do_pdf(pdf)

    assert pdf.startswith(b"%PDF-")
    for proibido in ("IMAGEM", "mpi-ancora", "MPIFIG", "[["):
        assert proibido not in texto
    assert "Primeiro." in texto and "Último." in texto


# PDF real


def test_pdf_real_embute_png_e_jpeg_gerados() -> None:
    md = _material("Antes.", _ancora("a"), "Meio.", _ancora("b"), "Depois.")
    png = ImagemGerada(_imagem_real("png"), "p")
    jpeg = ImagemGerada(_imagem_real("jpeg"), "j")

    sem = _n_imagens_no_pdf(gerar_pdf_com_imagens_geradas(md, None))
    so_png = _n_imagens_no_pdf(gerar_pdf_com_imagens_geradas(md, _imagens([_conceito("a")], [png])))
    ambas = _n_imagens_no_pdf(
        gerar_pdf_com_imagens_geradas(md, _imagens([_conceito("a"), _conceito("b")], [png, jpeg]))
    )

    # cada imagem acrescenta objetos de imagem ao PDF (a logo da capa já existe nos três);
    # PNG e JPEG são desenhados, e o acréscimo cresce com a quantidade de imagens
    assert so_png > sem
    assert ambas > so_png


def test_pdf_preserva_capa_logo_e_imagens_originais_junto_das_geradas() -> None:
    md = _material("Antes.", _ancora("a"), "Depois.")
    originais = [ImagemExtraida(0, 0, png_sintetico(40, 30), "png")]
    imagens = _imagens([_conceito("a")], [ImagemGerada(_imagem_real("png"), "g")])

    html = montar_documento_html_com_imagens_geradas(md, imagens, originais)
    pdf = gerar_pdf_com_imagens_geradas(md, imagens, originais)

    assert 'class="capa"' in html and 'class="capa-logo"' in html
    assert "Imagens do material original" in html
    assert html.count("data:image/png;base64,") == 3  # logo + gerada + original
    assert html.index("Antes.") < html.index('alt="g"') < html.index("Depois.")
    assert html.index('alt="g"') < html.index("Imagens do material original")
    sem_geradas = gerar_pdf_com_imagens_geradas(md, None, originais)
    assert _n_imagens_no_pdf(pdf) > _n_imagens_no_pdf(sem_geradas)


def test_a_capa_nao_usa_os_tokens_nem_as_imagens() -> None:
    md = _material(
        "Parágrafo de corpo suficientemente longo para virar subtítulo da capa.", _ancora("a")
    )
    imagens = _imagens([_conceito("a")], [_png()])
    com = montar_documento_html_com_imagens_geradas(md, imagens)
    sem = montar_documento_html_com_imagens_geradas(md, None)
    capa_com = com[: com.index("</section>")]
    capa_sem = sem[: sem.index("</section>")]
    assert capa_com == capa_sem and "MPIFIG" not in capa_com


def test_gerar_pdf_com_imagens_geradas_usa_o_mesmo_fetcher_so_data() -> None:
    capturado: dict[str, object] = {}

    class HTMLFalso:
        def __init__(self, string: str, url_fetcher: object) -> None:
            capturado["html"] = string
            capturado["fetcher"] = url_fetcher

        def write_pdf(self, stylesheets: list[object]) -> bytes:
            capturado["n_folhas"] = len(stylesheets)
            return b"%PDF-falso"

    imagens = _imagens([_conceito("a")], [_png()])
    md = _material(_ancora("a"))
    with (
        patch.object(gerador_pdf, "HTML", HTMLFalso),
        patch.object(gerador_pdf, "CSS", lambda string, url_fetcher: string),
    ):
        resultado = gerar_pdf_com_imagens_geradas(md, imagens)

    assert resultado == b"%PDF-falso"
    assert capturado["fetcher"] is gerador_pdf._url_fetcher_sem_rede
    assert capturado["n_folhas"] == len(gerador_pdf.folhas_de_estilo_pdf())
    assert 'class="imagem-gerada"' in str(capturado["html"])


def test_falha_do_weasyprint_vira_erro_de_pipeline_sem_vazar_detalhes() -> None:
    class HTMLQuebrado:
        def __init__(self, string: str, url_fetcher: object) -> None:
            pass

        def write_pdf(self, stylesheets: list[object]) -> bytes:
            raise RuntimeError("segredo interno")

    with patch.object(gerador_pdf, "HTML", HTMLQuebrado), pytest.raises(ErroDePipeline) as erro:
        gerar_pdf_com_imagens_geradas(_material("x"), None)
    assert "segredo" not in str(erro.value)


# Comportamento anterior preservado


def test_assinaturas_publicas_anteriores_nao_mudaram() -> None:
    sig = inspect.signature(gerar_pdf)
    assert [(p.name, p.kind, p.default) for p in sig.parameters.values()] == [
        ("conteudo_markdown", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("imagens", inspect.Parameter.POSITIONAL_OR_KEYWORD, ()),
        ("incluir_capa", inspect.Parameter.KEYWORD_ONLY, True),
    ]
    assert sig.return_annotation in (bytes, "bytes")
    sig_html = inspect.signature(montar_documento_html)
    assert list(sig_html.parameters) == ["conteudo_markdown", "imagens", "incluir_capa"]


@pytest.mark.parametrize("incluir_capa", [True, False])
def test_sem_imagens_geradas_o_html_e_o_de_antes(incluir_capa: bool) -> None:
    md = "# T\n\nParágrafo de corpo suficientemente longo para virar subtítulo da capa.\n"
    originais = [ImagemExtraida(0, 0, png_sintetico(40, 30), "png")]
    esperado = montar_documento_html(md, originais, incluir_capa=incluir_capa)

    assert (
        montar_documento_html_com_imagens_geradas(md, None, originais, incluir_capa=incluir_capa)
        == esperado
    )
    vazio = ImagensGeradasDoMaterial((), ())
    assert (
        montar_documento_html_com_imagens_geradas(md, vazio, originais, incluir_capa=incluir_capa)
        == esperado
    )


def test_so_falhas_geram_o_mesmo_html_do_texto_limpo() -> None:
    md = _material("Antes.", _ancora("a"), "Depois.")
    falha = FalhaGeracaoImagem("a", MotivoFalhaImagem.INDISPONIVEL)
    com_falha = montar_documento_html_com_imagens_geradas(md, _imagens([_conceito("a")], [falha]))
    limpo = montar_documento_html(_material("Antes.", "Depois."))
    assert re.sub(r"\n+", "\n", com_falha) == re.sub(r"\n+", "\n", limpo)


def test_pdf_sem_imagens_geradas_equivale_ao_gerar_pdf_antigo() -> None:
    md = _material("Um parágrafo qualquer do material adaptado.", "Outro parágrafo.")
    novo = gerar_pdf_com_imagens_geradas(md, None)
    antigo = gerar_pdf(md)
    assert _texto_do_pdf(novo) == _texto_do_pdf(antigo)
    assert _n_imagens_no_pdf(novo) == _n_imagens_no_pdf(antigo)


def test_gerar_pdf_antigo_continua_entregando_o_mesmo_html_ao_weasyprint() -> None:
    capturado: dict[str, object] = {}

    class HTMLFalso:
        def __init__(self, string: str, url_fetcher: object) -> None:
            capturado["html"] = string

        def write_pdf(self, stylesheets: list[object]) -> bytes:
            return b"%PDF-falso"

    md = _material("Texto.")
    with (
        patch.object(gerador_pdf, "HTML", HTMLFalso),
        patch.object(gerador_pdf, "CSS", lambda string, url_fetcher: string),
    ):
        gerar_pdf(md)

    assert capturado["html"] == montar_documento_html(md)


# Contrato ImagensGeradasDoMaterial


def test_contrato_aceita_menos_resultados_que_conceitos() -> None:
    contrato = _imagens([_conceito("a"), _conceito("b")], [_png()])
    assert list(contrato.imagens_por_ancora()) == ["a"]


def test_contrato_so_expoe_imagens_geradas_nunca_falhas() -> None:
    falha = FalhaGeracaoImagem("a", MotivoFalhaImagem.TIMEOUT)
    contrato = _imagens([_conceito("a"), _conceito("b")], [falha, _jpeg()])
    assert list(contrato.imagens_por_ancora()) == ["b"]


@pytest.mark.parametrize(
    "conceitos, resultados",
    [
        ([_conceito("a"), _conceito("a")], []),  # conceitos duplicados
        ([_conceito("a")], [_png(), _png()]),  # mais resultados que conceitos
        ([_conceito("a"), _conceito("b")], [FalhaGeracaoImagem("b", MotivoFalhaImagem.TIMEOUT)]),
        ([_conceito("a")], ["/etc/passwd"]),  # resultado que não é do contrato
        (["a"], []),  # conceito que não é do contrato
    ],
)
def test_contrato_invalido_e_rejeitado(conceitos: list[Any], resultados: list[Any]) -> None:
    with pytest.raises(EntradaInvalidaError) as erro:
        ImagensGeradasDoMaterial(tuple(conceitos), tuple(resultados))
    assert erro.value.code == "IMAGENS_GERADAS_INVALIDAS"


def test_contrato_aceita_listas_e_as_normaliza_para_tuplas() -> None:
    contrato = ImagensGeradasDoMaterial([_conceito("a")], [_png()])  # type: ignore[arg-type]
    assert isinstance(contrato.conceitos, tuple) and isinstance(contrato.resultados, tuple)


def test_o_padrao_de_ancora_reconhece_exatamente_o_que_o_extrator_produz() -> None:
    for identificador in ("a", "grafo-1", "G_2", "x" * 64):
        encontrada = _PADRAO_LINHA_DE_ANCORA.match(marcador_de_ancora(identificador))
        assert encontrada is not None and encontrada.group(1) == identificador
    assert _PADRAO_LINHA_DE_ANCORA.match(marcador_de_ancora("x" * 65)) is None
