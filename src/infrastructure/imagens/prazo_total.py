import math
import time
from collections.abc import Callable

# Menos que isso restando, não vale iniciar uma geração: ela não teria tempo de terminar.
MARGEM_MINIMA_PARA_INICIAR_SEGUNDOS = 10.0


class PrazoTotal:
    """Prazo único e compartilhado de uma fase inteira (todas as imagens de um material).

    O relógio é lido uma só vez, na criação; depois o prazo só consome tempo, nunca reinicia.
    Usa `time.monotonic` (imune a ajustes do relógio do sistema); o relógio é injetável para
    testes. Um relógio que ande para trás não devolve tempo: o restante nunca passa do total.
    """

    def __init__(self, segundos: float, relogio: Callable[[], float] = time.monotonic) -> None:
        if isinstance(segundos, bool) or not isinstance(segundos, (int, float)):
            raise TypeError("O prazo deve ser numérico.")
        if not math.isfinite(segundos) or segundos <= 0:
            raise ValueError("O prazo deve ser um número finito maior que zero.")
        self._total = float(segundos)
        self._relogio = relogio
        self._inicio = relogio()

    @property
    def total(self) -> float:
        return self._total

    def restante(self) -> float:
        """Segundos que sobram, entre 0 e o total; 0 quando esgotado."""
        decorrido = max(0.0, self._relogio() - self._inicio)
        return min(self._total, max(0.0, self._total - decorrido))

    def esgotado(self) -> bool:
        return self.restante() <= 0.0
