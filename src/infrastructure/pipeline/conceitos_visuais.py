import re
from dataclasses import dataclass

from application.ports.gerador_imagens import TAMANHO_MAXIMO_DA_DESCRICAO, ConceitoVisual
from domain.shared.exceptions import EntradaInvalidaError

# Marcador, sempre em linha própria e fora de bloco de código:
#     [[IMAGEM:identificador|descrição visual curta]]
# A posição da linha é a âncora. Marcador malformado é removido sem interromper a geração.
MAXIMO_PADRAO_DE_CONCEITOS = 1
TAMANHO_MINIMO_DA_DESCRICAO = 10

_PREFIXO_DA_ANCORA = "mpi-ancora:"

_LINHA_DE_MARCADOR = re.compile(r"^ {0,3}\[\[IMAGEM:([^\[\]|\r\n]*)\|([^\[\]|\r\n]*)\]\]\s*$")
_MARCADOR_EM_LINHA = re.compile(r"\[\[\s*IMAGEM[^\]\r\n]*\]\]", re.IGNORECASE)
_INICIO_DE_MARCADOR = re.compile(r"^\s{0,3}\[\[\s*IMAGEM", re.IGNORECASE)
# Âncoras que já venham no texto (do modelo ou de conteúdo hostil) são removidas: só as criadas
# aqui, para os conceitos aceitos, podem existir.
_ANCORA_PREEXISTENTE = re.compile(r"<!--\s*mpi-ancora:[^\r\n]*?-->", re.IGNORECASE)
_RECUO_DE_CODIGO = re.compile(r"^(?: {4,}|\t)")

# Letras (inclusive acentuadas), dígitos, espaço e pontuação comum de uma frase. Sem marcação
# (< > [ ] { } ` \ | * _ # ~ &), nada que permita HTML, Markdown, link ou instrução estruturada.
_DESCRICAO_PERMITIDA = re.compile(r"^[^\W_](?:[^\W_]|[ .,;:!?()'\"%+\-–/=])*$")
_FRAGMENTOS_PROIBIDOS = ("://", "www.", "javascript:", "data:", "mailto:")


@dataclass(frozen=True)
class ExtracaoDeConceitos:
    markdown: str
    conceitos: tuple[ConceitoVisual, ...]
    descartados: int


def marcador_de_ancora(identificador: str) -> str:
    # Substituto neutro de um marcador aceito: um comentário HTML não aparece no PDF (hoje) e
    # será trocado pela imagem na etapa de integração. Quem consumir deve procurar exatamente
    # este texto, para os identificadores dos conceitos devolvidos.
    return f"<!--{_PREFIXO_DA_ANCORA}{identificador}-->"


def extrair_conceitos_visuais(
    markdown: str, maximo: int = MAXIMO_PADRAO_DE_CONCEITOS
) -> ExtracaoDeConceitos:
    """Separa os conceitos visuais válidos do Markdown adaptado.

    Cada marcador aceito vira uma âncora e um `ConceitoVisual`; os demais são removidos.
    Sem nada a tratar, devolve o texto intacto. Nunca lança exceção por conteúdo.
    """
    conceitos: list[ConceitoVisual] = []
    vistos: set[str] = set()
    descartados = 0
    saida: list[str] = []
    dentro_de_codigo = False
    alterado = False

    for linha in markdown.split("\n"):
        if linha.lstrip().startswith(("```", "~~~")):
            dentro_de_codigo = not dentro_de_codigo
            saida.append(linha)
            continue
        if dentro_de_codigo or _RECUO_DE_CODIGO.match(linha):
            saida.append(linha)
            continue

        correspondencia = _LINHA_DE_MARCADOR.match(linha)
        if correspondencia is not None:
            alterado = True
            conceito = _conceito_valido(correspondencia.group(1), correspondencia.group(2))
            if conceito is None or conceito.identificador in vistos or len(conceitos) >= maximo:
                descartados += 1
                continue
            vistos.add(conceito.identificador)
            conceitos.append(conceito)
            saida.extend(["", marcador_de_ancora(conceito.identificador), ""])
            continue

        nova, quantidade = _MARCADOR_EM_LINHA.subn("", linha)
        nova, falsas = _ANCORA_PREEXISTENTE.subn("", nova)
        quantidade += falsas
        if quantidade:
            alterado = True
            descartados += quantidade
            if not nova.strip():
                continue
            linha = nova.rstrip()
        if _INICIO_DE_MARCADOR.match(linha):
            # Começa como marcador mas não fecha: some a linha inteira em vez de aparecer no texto.
            alterado = True
            descartados += 1
            continue
        saida.append(linha)

    if not alterado:
        return ExtracaoDeConceitos(markdown, (), 0)
    return ExtracaoDeConceitos("\n".join(saida), tuple(conceitos), descartados)


def remover_marcadores_visuais(markdown: str) -> str:
    # Para quando a geração de imagens está desligada: nenhum marcador pode chegar ao material.
    return extrair_conceitos_visuais(markdown, 0).markdown


def _conceito_valido(identificador: str, descricao: str) -> ConceitoVisual | None:
    identificador = identificador.strip()
    descricao = " ".join(descricao.split())
    minuscula = descricao.lower()
    if not TAMANHO_MINIMO_DA_DESCRICAO <= len(descricao) <= TAMANHO_MAXIMO_DA_DESCRICAO:
        return None
    if _DESCRICAO_PERMITIDA.match(descricao) is None:
        return None
    if any(fragmento in minuscula for fragmento in _FRAGMENTOS_PROIBIDOS):
        return None
    try:
        return ConceitoVisual(identificador, descricao, identificador)
    except EntradaInvalidaError:
        return None
