"""Heartbeat do Worker (Fase 11 — Documento 5 §185; Documento 4 §19).

Sem Redis: arquivo local em /tmp, escrito a cada iteração do loop (worker/loop.py) e
lido pelo healthcheck do Compose (`python -m worker.heartbeat`).

Escritor único, sem lock: o loop é sequencial, nunca concorrente. /tmp é efêmero por
container, então um restart começa sem heartbeat residual — o `start_period` do
healthcheck cobre essa janela antes da primeira iteração completar.
"""

import contextlib
import sys
import time
from pathlib import Path

from core.config import get_settings

_CAMINHO_PADRAO = Path("/tmp/worker_heartbeat")  # noqa: S108 -- efêmero de propósito, ver docstring


def atualizar_heartbeat(caminho: Path = _CAMINHO_PADRAO) -> None:
    """Grava o instante atual no arquivo de heartbeat.

    Falha ao escrever (ex.: /tmp sem espaço) não derruba o Worker — só deixa
    o heartbeat desatualizado, o que o healthcheck já trata como "não vivo".
    """
    with contextlib.suppress(OSError):
        caminho.write_text(str(time.time()))


def heartbeat_esta_valido(idade_maxima_segundos: float, caminho: Path = _CAMINHO_PADRAO) -> bool:
    """True se o arquivo existe e foi atualizado dentro do limite informado.

    Ausência do arquivo (container recém-iniciado, antes da primeira
    iteração) conta como inválido — é papel do `start_period` do healthcheck
    tolerar essa janela, não desta função fingir que já está tudo pronto.
    """
    try:
        instante = float(caminho.read_text())
    except (OSError, ValueError):
        return False
    return (time.time() - instante) <= idade_maxima_segundos


def limite_padrao_segundos() -> float:
    """Pior caso plausível de um ciclo real: polling + orçamento total de uma chamada ao
    Gemini (a etapa mais longa, gemini_timeout_total_segundos) + margem para PDF. Deriva
    de Settings já existentes, sem introduzir configuração nova.
    """
    settings = get_settings()
    margem_pipeline_segundos = 30.0
    return (
        settings.worker_intervalo_polling_segundos
        + settings.gemini_timeout_total_segundos
        + margem_pipeline_segundos
    )


if __name__ == "__main__":
    sys.exit(0 if heartbeat_esta_valido(limite_padrao_segundos()) else 1)
