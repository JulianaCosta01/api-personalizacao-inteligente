import base64
import html
import logging
import re
from collections.abc import Iterator, Sequence
from functools import lru_cache
from pathlib import Path
from string import Template

import markdown
import pymupdf
from weasyprint import CSS, HTML, URLFetcher

from infrastructure.pipeline.erros import ErroDePipeline
from infrastructure.pipeline.extrator import ImagemExtraida

logger = logging.getLogger(__name__)

_EXTENSOES_MARKDOWN = ["tables", "fenced_code"]

# HTML vem de Markdown gerado pelo Gemini, não confiável para busca de recursos externos
# pelo WeasyPrint; só o esquema "data" é aceito, usado para embutir as imagens preservadas.
_url_fetcher_sem_rede = URLFetcher(allowed_protocols=["data"])

# Extensões que o PyMuPDF pode reportar e que fazem sentido como data URI de imagem;
# qualquer coisa fora daqui é descartada em vez de embutida sem verificação.
_EXTENSOES_DE_IMAGEM_PERMITIDAS = {"png", "jpeg", "jpg", "gif", "bmp", "tiff", "webp"}

# Formatos fora da lista acima que o PyMuPDF decodifica e regrava como PNG, validados
# experimentalmente (JPX em RGB, RGBA com alfa e cinza; PNM em RGB e cinza). Qualquer outro
# formato (jxr, n/a...) continua descartado, agora com aviso, por não estar validado. JPX/PNM em
# CMYK não foram validados: se a regravação falhar, a imagem é descartada.
_EXTENSOES_CONVERTIVEIS_PARA_PNG = frozenset({"jpx", "pnm"})

_TAMANHO_MAXIMO_DO_ROTULO_DE_FORMATO = 10


def _rotulo_do_formato(extensao: str) -> str:
    # A extensão vai para o log; só entra se tiver a forma de um nome de formato, para que um
    # valor inesperado (extensão longa ou com caracteres de controle) não polua os logs.
    if (
        extensao.isascii()
        and extensao.isalnum()
        and len(extensao) <= _TAMANHO_MAXIMO_DO_ROTULO_DE_FORMATO
    ):
        return extensao
    return "invalido"


# Paleta PROVISÓRIA, inspirada no mockup de capa aprovado. Não são cores oficiais certificadas
# da UFMA nem do CCIA: trocar aqui quando houver manual de identidade visual. Dourado e turquesa
# (#E8B22E, #1E8F8A) não têm contraste suficiente para texto sobre fundo claro; ficam só em
# filetes, marcadores e formas. Texto em turquesa usa a variante escurecida.
_COR_VINHO = "#6B1230"
_COR_DOURADO = "#E8B22E"
_COR_TURQUESA = "#1E8F8A"
_COR_TURQUESA_TEXTO = "#17706C"
_COR_CREME = "#F5F1EA"
_COR_GRAFITE = "#2D3036"
_COR_LINHA = "#E3DCCD"
_COR_RODAPE = "#5B616B"

# Estilo acadêmico com a identidade institucional, embutido (sem recurso externo). Fontes: só
# DejaVu (a que o container da imagem de execução traz) com fallback para famílias genéricas;
# nada de fonte baixada. Cabeçalho e rodapé ficam nas margens da página, sem tocar no conteúdo.
_FOLHA_DE_ESTILO = Template(
    """
@page {
  size: A4;
  margin: 25mm 22mm 25mm 22mm;
  @top-left {
    content: "UFMA · CCIA";
    font-family: "DejaVu Sans", sans-serif;
    font-size: 7.5pt;
    color: $vinho;
  }
  @bottom-center {
    content: "Página " counter(page) " de " counter(pages);
    font-family: "DejaVu Sans", sans-serif;
    font-size: 8.5pt;
    color: $rodape;
  }
}
html {
  font-family: "DejaVu Sans", sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
  color: $grafite;
}
body { margin: 0; overflow-wrap: break-word; }
h1, h2, h3, h4 {
  color: $vinho;
  line-height: 1.25;
  break-after: avoid;
  break-inside: avoid;
}
h1 { font-size: 20pt; margin: 0 0 12pt; padding-bottom: 6pt; border-bottom: 2pt solid $dourado; }
h2 { font-size: 15pt; margin: 20pt 0 8pt; padding-left: 8pt; border-left: 3.5pt solid $dourado; }
h3 { font-size: 12.5pt; margin: 16pt 0 6pt; }
h4 { font-size: 11pt; margin: 12pt 0 4pt; color: $turquesa_texto; }
p { margin: 0 0 8pt; orphans: 3; widows: 3; }
a { color: $vinho; }
ul, ol { margin: 0 0 8pt; padding-left: 20pt; }
li { margin-bottom: 3pt; }
li::marker { color: $turquesa; }
blockquote {
  margin: 10pt 0;
  padding: 8pt 14pt;
  border-left: 3pt solid $dourado;
  background: $creme;
  color: $grafite;
  break-inside: avoid;
}
blockquote p:last-child { margin-bottom: 0; }
table { width: 100%; border-collapse: collapse; margin: 10pt 0 12pt; font-size: 9.5pt; }
thead { display: table-header-group; }
th, td {
  border: 0.75pt solid $linha;
  padding: 5pt 7pt;
  text-align: left;
  vertical-align: top;
  /* "anywhere" (e não "break-word") entra no cálculo da largura mínima da coluna; com
     "break-word" uma palavra longa alarga a tabela além da página e o excesso é cortado. */
  overflow-wrap: anywhere;
}
th { background: $creme; color: $vinho; font-weight: bold; border-bottom: 1.5pt solid $vinho; }
tr { break-inside: avoid; }
pre {
  font-family: "DejaVu Sans Mono", monospace;
  font-size: 8.5pt;
  line-height: 1.4;
  background: $creme;
  border: 0.75pt solid $linha;
  border-left: 3pt solid $turquesa;
  padding: 8pt 10pt;
  margin: 8pt 0 12pt;
  white-space: pre-wrap;
  overflow-wrap: break-word;
}
code {
  font-family: "DejaVu Sans Mono", monospace;
  font-size: 9pt;
  background: $creme;
  color: $vinho;
}
pre code { background: none; color: inherit; font-size: inherit; }
img {
  display: block;
  max-width: 100%;
  max-height: 230mm;
  height: auto;
  margin: 10pt auto;
  break-inside: avoid;
}
hr { border: 0; border-top: 1pt solid $dourado; margin: 14pt 0; }
"""
).substitute(
    vinho=_COR_VINHO,
    dourado=_COR_DOURADO,
    turquesa=_COR_TURQUESA,
    turquesa_texto=_COR_TURQUESA_TEXTO,
    creme=_COR_CREME,
    grafite=_COR_GRAFITE,
    linha=_COR_LINHA,
    rodape=_COR_RODAPE,
)


def _preparar_imagem(imagem: ImagemExtraida) -> tuple[bytes, str] | None:
    # Devolve (conteúdo, extensão) pronto para embutir, ou None se a imagem for descartada.
    # Os avisos trazem só página, índice, formato e o nome da classe da exceção: nunca bytes,
    # texto do material nem a mensagem da exceção.
    if imagem.extensao in _EXTENSOES_DE_IMAGEM_PERMITIDAS:
        return imagem.conteudo, imagem.extensao

    formato = _rotulo_do_formato(imagem.extensao)
    if imagem.extensao not in _EXTENSOES_CONVERTIVEIS_PARA_PNG:
        logger.warning(
            "Imagem descartada: formato não suportado (formato=%s, página=%d, índice=%d).",
            formato,
            imagem.numero_pagina + 1,
            imagem.indice_na_pagina,
        )
        return None

    try:
        return pymupdf.Pixmap(imagem.conteudo).tobytes("png"), "png"
    except Exception as exc:
        logger.warning(
            "Imagem descartada: falha ao converter para PNG "
            "(formato=%s, página=%d, índice=%d, erro=%s).",
            formato,
            imagem.numero_pagina + 1,
            imagem.indice_na_pagina,
            type(exc).__name__,
        )
        return None


def _construir_secao_de_imagens(imagens: Sequence[ImagemExtraida]) -> str:
    preparadas = [
        (imagem, resultado)
        for imagem in imagens
        if (resultado := _preparar_imagem(imagem)) is not None
    ]
    if not preparadas:
        return ""

    blocos = ["\n\n## Imagens do material original\n"]
    for imagem, (conteudo, extensao) in preparadas:
        codificado = base64.b64encode(conteudo).decode("ascii")
        blocos.append(
            f"\n![Imagem da página {imagem.numero_pagina + 1}]"
            f"(data:image/{extensao};base64,{codificado})\n"
        )
    return "".join(blocos)


# --- Capa institucional ---------------------------------------------------------------------
_TITULO_PADRAO = "Material Didático"
_TAMANHO_MAXIMO_DO_TITULO = 120
_TAMANHO_MINIMO_DO_SUBTITULO = 40
_TAMANHO_MAXIMO_DO_SUBTITULO = 200
_BLOCOS_EXAMINADOS_PARA_SUBTITULO = 10
_LIMITE_TITULO_CURTO = 24
_LIMITE_TITULO_MEDIO = 48
_LIMITE_TITULO_LONGO = 80
_LARGURA_DA_COLUNA_DO_TITULO_EM_PT = 400.0
_TAMANHO_MINIMO_DO_TITULO_EM_PT = 12.0
_PADRAO_QUEBRA_DE_PALAVRA = re.compile(r"[\s\-–—/]+")

_PADRAO_TITULO_H1 = re.compile(r"^ {0,3}#[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_PADRAO_IMAGEM_MARKDOWN = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_PADRAO_LINK_MARKDOWN = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_PADRAO_TAG_HTML = re.compile(r"<[^>]*>")
_PADRAO_ENFASE = re.compile(r"[*_`]")
# Blocos que não são texto corrido: títulos, citações, tabelas, listas, imagens, HTML, código,
# fórmulas em bloco, réguas e marcações de sugestão.
_PADRAO_BLOCO_ESPECIAL = re.compile(
    r"^(#{1,6}[ \t]|>|\||[-*+][ \t]|\d+[.)][ \t]|!\[|<|`|~|\$\$|\[)"
)
_PADRAO_SUBLINHADO_SETEXT = re.compile(r"^\s*(=+|-{3,})\s*$")

# Logo oficial da UFMA, fornecida pelo projeto. O arquivo foi recortado ao círculo (604x604 px) a
# partir da imagem enviada, sem redimensionar, recolorir nem redesenhar, e com o fundo externo ao
# círculo transparente. Entra como imagem rasterizada (data URI); é a única colocação de imagem da
# capa. Se o arquivo faltar ou não for PNG, a capa sai só com a identificação textual.
_CAMINHO_DA_LOGO_UFMA = Path(__file__).parent / "assets" / "ufma_logo.png"
_ASSINATURA_PNG = b"\x89PNG\r\n\x1a\n"
_TAMANHO_MAXIMO_DA_LOGO_EM_BYTES = 2 * 1024 * 1024


@lru_cache(maxsize=1)
def _logo_ufma_data_uri() -> str | None:
    try:
        conteudo = _CAMINHO_DA_LOGO_UFMA.read_bytes()
    except OSError as exc:
        logger.warning(
            "Logo da UFMA indisponível; capa só com texto (erro=%s).", type(exc).__name__
        )
        return None
    if not conteudo.startswith(_ASSINATURA_PNG) or len(conteudo) > _TAMANHO_MAXIMO_DA_LOGO_EM_BYTES:
        logger.warning("Arquivo da logo da UFMA inválido; capa só com texto.")
        return None
    return "data:image/png;base64," + base64.b64encode(conteudo).decode("ascii")


# Geometria em milímetros (viewBox = página A4). Formas e ilustração originais e simplificadas:
# faixa diagonal, cunhas, perfil com trilhas de circuito e uma rede discreta de nós ligados.
_SVG_CAPA = Template(
    """<svg class="capa-fundo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 210 297"
     width="210mm" height="297mm" preserveAspectRatio="none">
  <polygon points="188,0 210,0 210,22 180,22" fill="$turquesa"/>
  <polygon points="164,50 184,22 196,22 176,50" fill="$dourado"/>
  <polygon points="192,22 210,22 210,186 162,212 134,131 192,70" fill="$vinho"/>
  <polyline points="148,106 210,44" fill="none" stroke="$dourado" stroke-width="0.45"/>
  <polyline points="166,224 210,194" fill="none" stroke="$dourado" stroke-width="0.45"/>
  <g fill="none" stroke="$dourado" stroke-linecap="round" stroke-linejoin="round">
    <path stroke-width="0.9" d="M178,98 C166,104 158,114 157,126 L156,131 L147,143 L153,146
      L152,150 L149,153 L153,156 L152,162 C152,168 155,171 160,172 L168,174
      C170,180 170,190 170,206"/>
    <path stroke-width="0.9" d="M178,98 C190,94 206,98 210,108"/>
    <g stroke-width="0.5" opacity="0.9">
      <path d="M176,112 L188,112 L192,118 L192,128"/>
      <path d="M172,126 L182,126 L186,132 L200,132"/>
      <path d="M166,140 L178,140 L182,146 L196,146 L200,152"/>
      <path d="M164,156 L174,156 L178,162 L190,162"/>
      <path d="M180,172 L190,172 L194,178 L206,178"/>
    </g>
  </g>
  <g>
    <circle cx="192" cy="128" r="2.2" fill="$turquesa"/>
    <circle cx="200" cy="132" r="2.2" fill="$dourado"/>
    <circle cx="200" cy="152" r="2.2" fill="$dourado"/>
    <circle cx="190" cy="162" r="2.2" fill="$turquesa"/>
    <circle cx="206" cy="178" r="2.2" fill="$dourado"/>
    <circle cx="176" cy="112" r="1.6" fill="$dourado"/>
  </g>
  <polygon points="140,262 160,236 170,236 150,262" fill="$dourado"/>
  <polygon points="152,282 176,252 184,252 160,282" fill="$turquesa"/>
  <g fill="none" stroke="$vinho" stroke-width="0.35" opacity="0.28">
    <polyline points="12,262 32,246 50,252 68,230 92,236 114,212"/>
    <polyline points="32,246 38,230 56,222"/>
    <polyline points="68,230 76,214"/>
  </g>
  <g fill="$vinho" opacity="0.32">
    <circle cx="12" cy="262" r="1.5"/><circle cx="32" cy="246" r="1.5"/>
    <circle cx="50" cy="252" r="1.5"/><circle cx="68" cy="230" r="1.5"/>
    <circle cx="92" cy="236" r="1.5"/><circle cx="114" cy="212" r="1.5"/>
    <circle cx="56" cy="222" r="1.5"/><circle cx="76" cy="214" r="1.5"/>
  </g>
  <g opacity="0.55">
    <circle cx="38" cy="230" r="1.6" fill="$turquesa"/>
    <circle cx="114" cy="212" r="1.6" fill="$dourado"/>
  </g>
</svg>"""
).substitute(vinho=_COR_VINHO, dourado=_COR_DOURADO, turquesa=_COR_TURQUESA)

# Página nomeada "capa": sem margem e sem rodapé de paginação, fundo claro em sangria total.
# O título cai em <p> (não <h1>) para não duplicar o marcador de título do corpo.
_FOLHA_DE_ESTILO_CAPA = Template(
    """
@page capa {
  size: A4;
  margin: 0;
  background: $fundo;
  @top-left { content: none; }
  @bottom-center { content: none; }
}
.capa {
  page: capa;
  position: relative;
  width: 210mm;
  height: 296mm;
  overflow: hidden;
  break-after: page;
  font-family: "DejaVu Sans", sans-serif;
  color: $texto;
}
.capa p { margin: 0; orphans: 1; widows: 1; }
.capa-fundo { position: absolute; left: 0; top: 0; width: 210mm; height: 297mm; }
.capa .capa-logo {
  position: absolute; left: 22mm; top: 16mm; width: 32mm; height: 32mm;
  margin: 0; max-width: none; max-height: none;
}
.capa-id-ufma {
  position: absolute; left: 60mm; top: 27mm; width: 38mm;
  font-size: 8.5pt; font-weight: bold; line-height: 1.35; letter-spacing: 1.2pt;
  color: $vinho;
}
.capa-id-ccia {
  position: absolute; left: 102mm; top: 25mm; width: 60mm;
  padding-left: 5mm; border-left: 0.4mm solid $vinho;
}
.capa-id-ccia .sigla { font-size: 21pt; font-weight: bold; line-height: 1.1; color: $vinho; }
.capa-id-ccia .nome { font-size: 8pt; line-height: 1.35; color: $vinho; }
.capa-texto { position: absolute; left: 22mm; top: 76mm; width: 106mm; }
.capa .capa-rotulo { font-size: 8.5pt; letter-spacing: 2.2pt; color: $vinho; }
.capa-filete { width: 14mm; height: 0.9mm; margin-top: 4mm; background: $dourado; }
.capa .capa-titulo {
  margin-top: 9mm; font-weight: bold; color: $vinho; line-height: 1.12;
  overflow-wrap: anywhere;
}
.capa .capa-subtitulo {
  margin-top: 8mm; font-size: 11pt; line-height: 1.5; overflow-wrap: anywhere;
}
.capa-rodape {
  position: absolute; left: 22mm; bottom: 17mm; width: 120mm;
  padding-left: 5mm; border-left: 0.9mm solid $dourado;
}
.capa-rodape .linha1 { font-size: 8pt; font-weight: bold; letter-spacing: 1.6pt; color: $vinho; }
.capa-rodape .linha2 { font-size: 6.5pt; letter-spacing: 0.8pt; color: $texto; }
"""
).substitute(vinho=_COR_VINHO, dourado=_COR_DOURADO, fundo=_COR_CREME, texto=_COR_GRAFITE)


def _texto_simples(texto: str) -> str:
    # Remove marcação Markdown/HTML e caracteres de controle de um trecho vindo do modelo.
    texto = _PADRAO_IMAGEM_MARKDOWN.sub("", texto)
    texto = _PADRAO_LINK_MARKDOWN.sub(r"\1", texto)
    texto = _PADRAO_TAG_HTML.sub("", texto)
    texto = _PADRAO_ENFASE.sub("", texto)
    texto = "".join(
        caractere for caractere in texto if caractere.isprintable() or caractere.isspace()
    )
    return " ".join(texto.split())


def _truncar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    if " " in corte:
        corte = corte.rsplit(" ", 1)[0]
    return corte.rstrip(" ,;:.-–—") + "…"


def _linhas_fora_de_codigo(linhas: Sequence[str], inicio: int = 0) -> Iterator[tuple[int, str]]:
    # Ignora blocos de código cercados (``` ou ~~~): o que está lá dentro não é título nem texto.
    dentro_de_codigo = False
    for indice in range(inicio, len(linhas)):
        linha = linhas[indice]
        if linha.lstrip().startswith(("```", "~~~")):
            dentro_de_codigo = not dentro_de_codigo
            continue
        if not dentro_de_codigo:
            yield indice, linha


def _extrair_titulo(linhas: Sequence[str]) -> tuple[str | None, int]:
    # Primeiro título de nível 1 (ATX). Devolve (título limpo, índice da linha) ou (None, -1).
    # Títulos no estilo "Setext" (sublinhados) não são considerados.
    for indice, linha in _linhas_fora_de_codigo(linhas):
        encontrado = _PADRAO_TITULO_H1.match(linha)
        if encontrado is None:
            continue
        titulo = _texto_simples(encontrado.group(1))
        if titulo:
            return _truncar(titulo, _TAMANHO_MAXIMO_DO_TITULO), indice
    return None, -1


def _candidato_a_subtitulo(bloco: Sequence[str]) -> str | None:
    if _PADRAO_BLOCO_ESPECIAL.match(bloco[0].lstrip()):
        return None
    if any("|" in linha or _PADRAO_SUBLINHADO_SETEXT.match(linha) for linha in bloco):
        return None
    texto = _texto_simples(" ".join(bloco))
    if len(texto) < _TAMANHO_MINIMO_DO_SUBTITULO:
        return None
    return _truncar(texto, _TAMANHO_MAXIMO_DO_SUBTITULO)


def _extrair_subtitulo(linhas: Sequence[str], inicio: int) -> str | None:
    # Primeiro parágrafo de texto corrido (e longo o bastante) depois do título, só entre os
    # primeiros blocos; sem parágrafo adequado a capa fica sem subtítulo.
    bloco: list[str] = []
    examinados = 0

    def avaliar() -> str | None:
        nonlocal examinados, bloco
        if not bloco:
            return None
        examinados += 1
        candidato = _candidato_a_subtitulo(bloco)
        bloco = []
        return candidato

    for _indice, linha in _linhas_fora_de_codigo(linhas, inicio):
        if linha.strip():
            bloco.append(linha)
            continue
        candidato = avaliar()
        if candidato is not None:
            return candidato
        if examinados >= _BLOCOS_EXAMINADOS_PARA_SUBTITULO:
            return None
    return avaliar() if examinados < _BLOCOS_EXAMINADOS_PARA_SUBTITULO else None


def _tamanho_do_titulo(titulo: str) -> float:
    # Corpo da fonte do título, em pt. Dois limites: o comprimento total (menos linhas para
    # títulos curtos) e a maior palavra, que precisa caber na largura da coluna de texto da capa
    # (106 mm ≈ 300 pt, com ~0,75 em por caractere em DejaVu Sans Bold, medido com folga) para
    # não ser quebrada no meio. Palavras ligadas por hífen ou barra podem quebrar ali.
    total = len(titulo)
    if total <= _LIMITE_TITULO_CURTO:
        por_comprimento = 40.0
    elif total <= _LIMITE_TITULO_MEDIO:
        por_comprimento = 32.0
    elif total <= _LIMITE_TITULO_LONGO:
        por_comprimento = 25.0
    else:
        por_comprimento = 20.0
    maior_palavra = max(
        (len(parte) for parte in _PADRAO_QUEBRA_DE_PALAVRA.split(titulo)), default=1
    )
    por_palavra = _LARGURA_DA_COLUNA_DO_TITULO_EM_PT / max(maior_palavra, 1)
    return round(max(min(por_comprimento, por_palavra), _TAMANHO_MINIMO_DO_TITULO_EM_PT), 1)


def _dados_da_capa(conteudo_markdown: str) -> tuple[str, str | None]:
    linhas = conteudo_markdown.splitlines()
    titulo, posicao = _extrair_titulo(linhas)
    subtitulo = _extrair_subtitulo(linhas, posicao + 1)
    return titulo or _TITULO_PADRAO, subtitulo


def _renderizar_capa(titulo: str, subtitulo: str | None) -> str:
    # Todo texto dinâmico passa por html.escape: título e subtítulo vêm de conteúdo gerado
    # por modelo, não confiável. A logo da UFMA vem do arquivo oficial fornecido; a identificação
    # do CCIA é só texto, pois não há arquivo de marca do CCIA e nada foi desenhado para imitá-lo.
    bloco_subtitulo = f'<p class="capa-subtitulo">{html.escape(subtitulo)}</p>' if subtitulo else ""
    logo = _logo_ufma_data_uri()
    bloco_logo = (
        f'<img class="capa-logo" src="{logo}" alt="Logo da Universidade Federal do Maranhão">'
        if logo
        else ""
    )
    return (
        '<section class="capa">'
        f"{_SVG_CAPA}"
        f"{bloco_logo}"
        '<div class="capa-id-ufma">UNIVERSIDADE<br>FEDERAL DO<br>MARANHÃO</div>'
        '<div class="capa-id-ccia">'
        '<p class="sigla">CCIA</p>'
        '<p class="nome">Ciência da Computação e Inteligência Artificial | UFMA</p>'
        "</div>"
        '<div class="capa-texto">'
        '<p class="capa-rotulo">MATERIAL DIDÁTICO PERSONALIZADO</p>'
        '<div class="capa-filete"></div>'
        f'<p class="capa-titulo" style="font-size: {_tamanho_do_titulo(titulo)}pt">'
        f"{html.escape(titulo)}</p>"
        f"{bloco_subtitulo}"
        "</div>"
        '<div class="capa-rodape">'
        '<p class="linha1">UFMA · CCIA</p>'
        '<p class="linha2">CIÊNCIA DA COMPUTAÇÃO E INTELIGÊNCIA ARTIFICIAL</p>'
        "</div>"
        "</section>"
    )


def _montar_documento_com_capa(capa_html: str, corpo_html: str, titulo: str) -> str:
    return (
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
        f"<title>{html.escape(titulo)}</title></head>"
        f"<body>{capa_html}{corpo_html}</body></html>"
    )


def gerar_pdf(
    conteudo_markdown: str,
    imagens: Sequence[ImagemExtraida] = (),
    *,
    incluir_capa: bool = True,
) -> bytes:
    # incluir_capa=False reproduz a geração anterior (só o corpo, sem invólucro HTML nem capa).
    # Com capa, ela é a página 1 (sem rodapé) e o corpo segue numerado pela página física.
    try:
        conteudo_completo = conteudo_markdown + _construir_secao_de_imagens(imagens)
        corpo_html = markdown.markdown(conteudo_completo, extensions=_EXTENSOES_MARKDOWN)
        folhas = [CSS(string=_FOLHA_DE_ESTILO, url_fetcher=_url_fetcher_sem_rede)]
        if incluir_capa:
            # Título e subtítulo saem do Markdown original, sem as imagens anexadas, e a capa
            # entra só no HTML: o corpo (e o resumo calculado fora daqui) não muda.
            titulo, subtitulo = _dados_da_capa(conteudo_markdown)
            documento_html = _montar_documento_com_capa(
                _renderizar_capa(titulo, subtitulo), corpo_html, titulo
            )
            folhas.append(CSS(string=_FOLHA_DE_ESTILO_CAPA, url_fetcher=_url_fetcher_sem_rede))
        else:
            documento_html = corpo_html
        return HTML(string=documento_html, url_fetcher=_url_fetcher_sem_rede).write_pdf(
            stylesheets=folhas
        )
    except Exception as exc:
        raise ErroDePipeline("Falha ao gerar o PDF personalizado.") from exc
