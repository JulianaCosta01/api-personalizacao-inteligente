import base64
import html
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from application.ports.estrutura_imagem import estrutura_da_imagem_valida
from application.ports.gerador_imagens import (
    ConceitoVisual,
    FalhaGeracaoImagem,
    ImagemGerada,
    ResultadoGeracaoImagem,
)
from domain.shared.exceptions import EntradaInvalidaError
from infrastructure.pipeline.conceitos_visuais import remover_marcadores_visuais

# Linha de âncora criada por `conceitos_visuais.marcador_de_ancora`: comentário HTML sozinho na
# linha (até 3 espaços de recuo), com o identificador do conceito.
_PADRAO_LINHA_DE_ANCORA = re.compile(
    r"^ {0,3}<!--mpi-ancora:([A-Za-z0-9][A-Za-z0-9_-]{0,63})-->\s*$"
)
_RECUO_DE_CODIGO = re.compile(r"^(?: {4,}|\t)")
# Única forma de URI de imagem aceita no documento: base64 estrito de PNG ou JPEG.
_URI_DE_IMAGEM_PERMITIDA = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/]+={0,2}")


def _rejeitar(mensagem: str) -> EntradaInvalidaError:
    return EntradaInvalidaError(code="IMAGENS_GERADAS_INVALIDAS", message=mensagem)


@dataclass(frozen=True)
class ImagensGeradasDoMaterial:
    """O que o gerador de PDF recebe para posicionar imagens geradas por IA.

    `conceitos` são os conceitos identificados no texto (únicos, cada um com a sua âncora) e
    `resultados` o que o orquestrador devolveu para eles, na mesma ordem. `ImagemGerada` não
    carrega identificador: o vínculo é por posição (resultados[i] ↔ conceitos[i]), o que o
    `GeradorDeImagensDoMaterial` garante. Pode haver menos resultados que conceitos (os que
    ficaram sem resultado simplesmente não ganham imagem); mais, não. Uma falha precisa
    apontar para o conceito da própria posição. A única origem de imagem possível é o
    conteúdo em bytes de `ImagemGerada`: nunca caminho de arquivo nem URL.
    """

    conceitos: tuple[ConceitoVisual, ...]
    resultados: tuple[ResultadoGeracaoImagem, ...]

    def __post_init__(self) -> None:
        conceitos = tuple(self.conceitos)
        resultados = tuple(self.resultados)
        if not all(isinstance(c, ConceitoVisual) for c in conceitos):
            raise _rejeitar("Conceito visual inválido.")
        if not all(isinstance(r, ImagemGerada | FalhaGeracaoImagem) for r in resultados):
            raise _rejeitar("Resultado de geração de imagem inválido.")
        if len({c.identificador for c in conceitos}) != len(conceitos) or len(
            {c.ancora for c in conceitos}
        ) != len(conceitos):
            raise _rejeitar("Conceitos visuais duplicados.")
        if len(resultados) > len(conceitos):
            raise _rejeitar("Há mais resultados de imagem que conceitos visuais.")
        for conceito, resultado in zip(conceitos, resultados, strict=False):
            if (
                isinstance(resultado, FalhaGeracaoImagem)
                and resultado.identificador_do_conceito != conceito.identificador
            ):
                raise _rejeitar("Falha de imagem não corresponde ao conceito da posição.")
        object.__setattr__(self, "conceitos", conceitos)
        object.__setattr__(self, "resultados", resultados)

    def imagens_por_ancora(self) -> dict[str, ImagemGerada]:
        # Só imagens geradas, associadas a um conceito identificado; falhas não entram.
        return {
            conceito.ancora: resultado
            for conceito, resultado in zip(self.conceitos, self.resultados, strict=False)
            if isinstance(resultado, ImagemGerada)
        }


@dataclass(frozen=True)
class Posicionamento:
    # Markdown já sem marcadores e âncoras; no lugar de cada imagem a posicionar há um parágrafo
    # com um token aleatório (inexistente no conteúdo original).
    markdown: str
    # O mesmo texto sem nenhuma imagem: base da capa e do resumo.
    texto_limpo: str
    # Troca os tokens do HTML convertido pelas imagens e apaga qualquer token que sobrar.
    substituir: Callable[[str], str]
    # Quantas imagens foram preparadas para posicionamento (0 = o texto segue como está).
    preparadas: int


def _bloco_da_imagem(imagem: ImagemGerada) -> str | None:
    # Devolve o HTML da imagem ou None se ela não passar na validação. Revalida os bytes mesmo
    # com `ImagemGerada` já validada: o objeto é imutável por convenção, não por garantia.
    if not isinstance(imagem.conteudo, bytes) or not estrutura_da_imagem_valida(imagem.conteudo):
        return None
    uri = f"data:image/{imagem.extensao};base64,{base64.b64encode(imagem.conteudo).decode('ascii')}"
    if _URI_DE_IMAGEM_PERMITIDA.fullmatch(uri) is None:
        return None
    alternativo = html.escape(imagem.texto_alternativo, quote=True)
    return f'<div class="imagem-gerada"><img src="{uri}" alt="{alternativo}"></div>'


def posicionar_imagens(
    markdown: str, imagens_geradas: ImagensGeradasDoMaterial | None
) -> Posicionamento:
    """Prepara o Markdown para receber as imagens geradas nas posições das âncoras.

    Âncoras sem conceito/imagem correspondente, repetidas, mal posicionadas ou forjadas, e
    marcadores `[[IMAGEM…]]` que tenham sobrado, saem do texto sem afetar o restante.
    """
    texto_limpo = remover_marcadores_visuais(markdown)
    por_ancora = imagens_geradas.imagens_por_ancora() if imagens_geradas is not None else {}
    if not por_ancora:
        return Posicionamento(texto_limpo, texto_limpo, _sem_alteracao, 0)

    prefixo = f"MPIFIG{secrets.token_hex(8)}N"
    blocos: dict[str, str] = {}
    saida: list[str] = []
    usadas: set[str] = set()
    dentro_de_codigo = False

    for linha in markdown.split("\n"):
        if linha.lstrip().startswith(("```", "~~~")):
            dentro_de_codigo = not dentro_de_codigo
            saida.append(linha)
            continue
        correspondencia = (
            None
            if dentro_de_codigo or _RECUO_DE_CODIGO.match(linha)
            else _PADRAO_LINHA_DE_ANCORA.match(linha)
        )
        if correspondencia is not None:
            ancora = correspondencia.group(1)
            imagem = por_ancora.get(ancora)
            bloco = (
                _bloco_da_imagem(imagem) if imagem is not None and ancora not in usadas else None
            )
            if bloco is not None:
                usadas.add(ancora)
                token = f"{prefixo}{len(blocos)}"
                blocos[token] = bloco
                saida.extend(["", token, ""])
                continue
        saida.append(linha)

    if not blocos:
        return Posicionamento(texto_limpo, texto_limpo, _sem_alteracao, 0)

    # A limpeza roda depois da troca por tokens: as âncoras aceitas já não existem como
    # comentário, e todas as demais (e os marcadores) são removidas aqui.
    com_tokens = remover_marcadores_visuais("\n".join(saida))
    padrao_residual = re.compile(re.escape(prefixo) + r"\d+")

    def substituir(corpo_html: str) -> str:
        for token, bloco in blocos.items():
            corpo_html = corpo_html.replace(f"<p>{token}</p>", bloco, 1)
        # Token que não ficou em parágrafo próprio: a imagem não é posicionada e o token some.
        return padrao_residual.sub("", corpo_html)

    return Posicionamento(com_tokens, texto_limpo, substituir, len(blocos))


def _sem_alteracao(corpo_html: str) -> str:
    return corpo_html
