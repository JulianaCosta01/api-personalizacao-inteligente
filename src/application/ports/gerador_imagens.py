import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from application.ports.estrutura_imagem import estrutura_da_imagem_valida
from domain.shared.exceptions import EntradaInvalidaError

_PADRAO_IDENTIFICADOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
TAMANHO_MAXIMO_DA_DESCRICAO = 300
TAMANHO_MAXIMO_DO_TEXTO_ALTERNATIVO = 300
TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES = 10 * 1024 * 1024

_ASSINATURA_PNG = b"\x89PNG\r\n\x1a\n"
_ASSINATURA_JPEG = b"\xff\xd8\xff"


def _identificador_valido(valor: str) -> bool:
    return isinstance(valor, str) and _PADRAO_IDENTIFICADOR.fullmatch(valor) is not None


def _texto_curto_valido(valor: str, tamanho_maximo: int) -> bool:
    # Uma linha, sem espaços nas pontas e sem caracteres de controle: o texto vem de conteúdo
    # gerado por modelo (não confiável) e pode acabar em prompt, log ou HTML mais adiante.
    return (
        isinstance(valor, str)
        and 0 < len(valor) <= tamanho_maximo
        and valor == valor.strip()
        and valor.isprintable()
    )


def _rejeitar(code: str, message: str) -> EntradaInvalidaError:
    return EntradaInvalidaError(code=code, message=message)


class OrigemImagem(StrEnum):
    GERADA = "gerada"


class MotivoFalhaImagem(StrEnum):
    # Motivos genéricos e fechados, sem texto livre: a mensagem de uma exceção de terceiros
    # pode carregar detalhes da requisição que não devem sair do adaptador.
    TIMEOUT = "timeout"
    INDISPONIVEL = "indisponivel"
    LIMITE_EXCEDIDO = "limite_excedido"
    CONTEUDO_RECUSADO = "conteudo_recusado"
    RESPOSTA_INVALIDA = "resposta_invalida"
    # O prazo total da fase de imagens do material acabou antes (ou durante) esta geração.
    ORCAMENTO_ESGOTADO = "orcamento_esgotado"


@dataclass(frozen=True)
class ConceitoVisual:
    """Ideia a ser ilustrada, identificada no conteúdo já adaptado.

    `ancora` identifica o ponto do texto onde a imagem entra (por exemplo, o marcador que
    o código insere no Markdown); não é HTML nem um trecho do texto.
    """

    identificador: str
    descricao: str
    ancora: str

    def __post_init__(self) -> None:
        if not _identificador_valido(self.identificador):
            raise _rejeitar("CONCEITO_VISUAL_INVALIDO", "Identificador do conceito inválido.")
        if not _identificador_valido(self.ancora):
            raise _rejeitar("CONCEITO_VISUAL_INVALIDO", "Âncora do conceito inválida.")
        if not _texto_curto_valido(self.descricao, TAMANHO_MAXIMO_DA_DESCRICAO):
            raise _rejeitar("CONCEITO_VISUAL_INVALIDO", "Descrição visual do conceito inválida.")


@dataclass(frozen=True)
class ImagemGerada:
    conteudo: bytes
    texto_alternativo: str
    origem: OrigemImagem = OrigemImagem.GERADA

    def __post_init__(self) -> None:
        if not isinstance(self.conteudo, bytes) or not self.conteudo:
            raise _rejeitar("IMAGEM_GERADA_INVALIDA", "A imagem gerada está vazia.")
        if len(self.conteudo) > TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES:
            raise _rejeitar("IMAGEM_GERADA_INVALIDA", "A imagem gerada excede o tamanho máximo.")
        if not (
            self.conteudo.startswith(_ASSINATURA_PNG) or self.conteudo.startswith(_ASSINATURA_JPEG)
        ):
            # A assinatura nos bytes é a única confirmação do formato; só PNG e JPEG são
            # aceitos (nunca SVG, que pode carregar script).
            raise _rejeitar("IMAGEM_GERADA_INVALIDA", "Formato de imagem não suportado.")
        if not estrutura_da_imagem_valida(self.conteudo):
            # Assinatura correta não basta: arquivo truncado, corrompido, com dados anexados ou
            # com dimensões absurdas também é recusado.
            raise _rejeitar("IMAGEM_GERADA_INVALIDA", "Estrutura da imagem inválida.")
        if not _texto_curto_valido(self.texto_alternativo, TAMANHO_MAXIMO_DO_TEXTO_ALTERNATIVO):
            raise _rejeitar("IMAGEM_GERADA_INVALIDA", "Texto alternativo da imagem inválido.")
        if self.origem is not OrigemImagem.GERADA:
            raise _rejeitar("IMAGEM_GERADA_INVALIDA", "Origem da imagem inválida.")

    @property
    def extensao(self) -> str:
        return "png" if self.conteudo.startswith(_ASSINATURA_PNG) else "jpeg"


@dataclass(frozen=True)
class FalhaGeracaoImagem:
    """Resultado de uma geração que não produziu imagem; não interrompe o processamento."""

    identificador_do_conceito: str
    motivo: MotivoFalhaImagem

    def __post_init__(self) -> None:
        if not _identificador_valido(self.identificador_do_conceito):
            raise _rejeitar("FALHA_DE_IMAGEM_INVALIDA", "Identificador do conceito inválido.")
        if not isinstance(self.motivo, MotivoFalhaImagem):
            raise _rejeitar("FALHA_DE_IMAGEM_INVALIDA", "Motivo da falha inválido.")


ResultadoGeracaoImagem = ImagemGerada | FalhaGeracaoImagem


class IGeradorDeImagens(Protocol):
    async def gerar(self, conceito: ConceitoVisual) -> ResultadoGeracaoImagem:
        """Gera uma imagem para o conceito.

        Falhas previstas (tempo esgotado, serviço indisponível, conteúdo recusado, resposta
        inválida, limite excedido) são devolvidas como `FalhaGeracaoImagem`, nunca lançadas:
        uma imagem a menos não deve derrubar a personalização do material. Implementações
        não devem registrar nem propagar o prompt, o conteúdo recebido nem a exceção original
        do provedor.
        """
        ...
