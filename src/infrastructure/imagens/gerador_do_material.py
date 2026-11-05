import asyncio
import logging
from collections.abc import Sequence

from application.ports.gerador_imagens import (
    ConceitoVisual,
    FalhaGeracaoImagem,
    IGeradorDeImagens,
    ImagemGerada,
    MotivoFalhaImagem,
    ResultadoGeracaoImagem,
)
from infrastructure.imagens.prazo_total import MARGEM_MINIMA_PARA_INICIAR_SEGUNDOS, PrazoTotal

logger = logging.getLogger(__name__)


class GeradorDeImagensDoMaterial:
    """Gera as imagens de um material, em sequência, dentro de um prazo único.

    Devolve um resultado por conceito, na ordem recebida, e não inicia chamada sem tempo
    para ela. Logs só com identificadores, motivos e contagens.
    """

    def __init__(
        self,
        gerador: IGeradorDeImagens,
        prazo: PrazoTotal,
        maximo: int,
        timeout_por_imagem_segundos: float,
        limite_individual_segundos: float | None = None,
        margem_minima_segundos: float = MARGEM_MINIMA_PARA_INICIAR_SEGUNDOS,
    ) -> None:
        if timeout_por_imagem_segundos <= 0:
            raise ValueError("O timeout por imagem deve ser maior que zero.")
        if limite_individual_segundos is not None and limite_individual_segundos <= 0:
            raise ValueError("O limite individual deve ser maior que zero.")
        if margem_minima_segundos < 0:
            raise ValueError("A margem mínima não pode ser negativa.")
        self._gerador = gerador
        self._prazo = prazo
        self._maximo = maximo
        self._timeout_por_imagem = timeout_por_imagem_segundos
        self._limite_individual = limite_individual_segundos
        self._margem_minima = margem_minima_segundos

    async def gerar(
        self, conceitos: Sequence[ConceitoVisual]
    ) -> tuple[ResultadoGeracaoImagem, ...]:
        # O limite é aplicado aqui, antes de qualquer chamada ao provedor.
        selecionados = self._selecionar(conceitos)
        resultados: list[ResultadoGeracaoImagem] = []

        for conceito in selecionados:
            limite = self._limite_da_proxima_chamada()
            if limite is None:
                resultados.append(self._falha(conceito, MotivoFalhaImagem.ORCAMENTO_ESGOTADO))
                continue
            resultados.append(await self._gerar_uma(conceito, limite))

        self._registrar_resumo(resultados)
        return tuple(resultados)

    def _selecionar(self, conceitos: Sequence[ConceitoVisual]) -> list[ConceitoVisual]:
        if self._maximo < 1:
            return []
        vistos: set[str] = set()
        unicos: list[ConceitoVisual] = []
        for conceito in conceitos:
            if conceito.identificador in vistos:
                continue
            vistos.add(conceito.identificador)
            unicos.append(conceito)
        return unicos[: self._maximo]

    def _limite_da_proxima_chamada(self) -> float | None:
        # None = não iniciar: restam menos que a margem mínima (ou o prazo acabou).
        restante = self._prazo.restante()
        if restante <= 0 or restante < self._margem_minima:
            return None
        limite = min(restante, self._timeout_por_imagem)
        if self._limite_individual is not None:
            limite = min(limite, self._limite_individual)
        return limite

    async def _gerar_uma(self, conceito: ConceitoVisual, limite: float) -> ResultadoGeracaoImagem:
        try:
            resultado = await asyncio.wait_for(self._gerador.gerar(conceito), timeout=limite)
        except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041 - distintos antes do Python 3.11
            # Se o prazo acabou durante a chamada, a causa é o orçamento; senão, o limite da
            # própria imagem. CancelledError e erros de programação não são tratados aqui.
            motivo = (
                MotivoFalhaImagem.ORCAMENTO_ESGOTADO
                if self._prazo.esgotado()
                else MotivoFalhaImagem.TIMEOUT
            )
            return self._falha(conceito, motivo)
        if not isinstance(resultado, ImagemGerada | FalhaGeracaoImagem):
            # Violação do contrato da porta: é defeito de programação, não falha esperada.
            raise TypeError("O gerador de imagens devolveu um resultado fora do contrato.")
        return resultado

    @staticmethod
    def _falha(conceito: ConceitoVisual, motivo: MotivoFalhaImagem) -> FalhaGeracaoImagem:
        return FalhaGeracaoImagem(conceito.identificador, motivo)

    @staticmethod
    def _registrar_resumo(resultados: Sequence[ResultadoGeracaoImagem]) -> None:
        geradas = sum(isinstance(r, ImagemGerada) for r in resultados)
        falhas = [r for r in resultados if isinstance(r, FalhaGeracaoImagem)]
        if falhas:
            logger.warning(
                "Imagens do material: %d gerada(s), %d falha(s) (%s).",
                geradas,
                len(falhas),
                ", ".join(sorted({f.motivo.value for f in falhas})),
            )
        elif resultados:
            logger.info("Imagens do material: %d gerada(s).", geradas)
