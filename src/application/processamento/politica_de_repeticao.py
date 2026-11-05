import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class PoliticaDeRepeticao:
    """Quando e por quanto tempo um Processamento com falha transitória volta para a fila.

    `tentativas_maximas` conta reivindicações, não repetições. O atraso é exponencial e limitado
    por `atraso_maximo_segundos`; o jitter só reduz, então o pior caso continua previsível.
    """

    tentativas_maximas: int
    atraso_base_segundos: float = 30.0
    atraso_maximo_segundos: float = 300.0
    jitter_proporcional: float = 0.2

    def __post_init__(self) -> None:
        if self.tentativas_maximas < 1:
            raise ValueError("tentativas_maximas deve ser pelo menos 1.")
        if self.atraso_base_segundos <= 0:
            raise ValueError("atraso_base_segundos deve ser maior que zero.")
        if self.atraso_maximo_segundos < self.atraso_base_segundos:
            raise ValueError("atraso_maximo_segundos não pode ser menor que o atraso-base.")
        if not 0 <= self.jitter_proporcional < 1:
            raise ValueError("jitter_proporcional deve estar em [0, 1).")

    def permite_nova_tentativa(self, tentativas_realizadas: int) -> bool:
        return tentativas_realizadas < self.tentativas_maximas

    def atraso_apos(
        self, tentativas_realizadas: int, aleatorio: Callable[[], float] = random.random
    ) -> timedelta:
        """Espera antes da próxima reivindicação, depois de `tentativas_realizadas` falhas."""
        expoente = max(tentativas_realizadas - 1, 0)
        bruto = min(self.atraso_maximo_segundos, self.atraso_base_segundos * 2**expoente)
        return timedelta(seconds=bruto * (1 - self.jitter_proporcional * aleatorio()))

    def atraso_maximo_total(self) -> timedelta:
        """Soma dos atrasos no pior caso (sem redução por jitter), para dimensionar prazos."""
        total = sum(
            min(self.atraso_maximo_segundos, self.atraso_base_segundos * 2**n)
            for n in range(self.tentativas_maximas - 1)
        )
        return timedelta(seconds=total)
