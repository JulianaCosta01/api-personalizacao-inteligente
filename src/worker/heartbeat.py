"""Heartbeat do Worker.

Arquivo em /tmp escrito a cada iteração do loop e lido pelo healthcheck do Compose.
Escritor único, então não precisa de lock.
"""

import contextlib
import sys
import time
from pathlib import Path

from core.config import get_settings

_CAMINHO_PADRAO = Path("/tmp/worker_heartbeat")  # noqa: S108 -- efêmero de propósito, ver docstring


def atualizar_heartbeat(caminho: Path = _CAMINHO_PADRAO) -> None:
    """Grava o instante atual no arquivo de heartbeat.

    Falha ao escrever (ex.: /tmp sem espaço) não derruba o Worker, só deixa
    o heartbeat desatualizado, o que o healthcheck já trata como "não vivo".
    """
    with contextlib.suppress(OSError):
        caminho.write_text(str(time.time()))


def heartbeat_esta_valido(idade_maxima_segundos: float, caminho: Path = _CAMINHO_PADRAO) -> bool:
    """True se o arquivo existe e foi atualizado dentro do limite informado.

    Ausência do arquivo (container recém-iniciado, antes da primeira
    iteração) conta como inválido: é papel do `start_period` do healthcheck
    tolerar essa janela, não desta função fingir que já está tudo pronto.
    """
    try:
        instante = float(caminho.read_text())
    except (OSError, ValueError):
        return False
    return (time.time() - instante) <= idade_maxima_segundos


def limite_padrao_segundos() -> float:
    """Pior caso de um ciclo real: polling + o prazo máximo de UM job (worker_prazo_maximo_job_
    segundos, que já engloba as chamadas ao Gemini, as extras de complementação, as imagens e o
    PDF) + margem. O heartbeat só é gravado entre ciclos, então durante um job longo ele envelhece
    até esse limite. Deriva de Settings já existentes, sem introduzir configuração nova.
    """
    settings = get_settings()
    margem_segundos = 30.0
    return (
        settings.worker_intervalo_polling_segundos
        + settings.worker_prazo_maximo_job_segundos
        + margem_segundos
    )


if __name__ == "__main__":
    sys.exit(0 if heartbeat_esta_valido(limite_padrao_segundos()) else 1)
