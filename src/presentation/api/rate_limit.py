"""Rate limiting em memória, por token de serviço.

O contador vive no processo; com várias réplicas precisaria de um backend compartilhado.
"""

import time
from collections.abc import Awaitable, Callable
from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status

from core.config import get_settings
from presentation.api.dependencies import validar_token_servico

_PREFIXO_BEARER = "Bearer "

RelogioMonotonico = Callable[[], float]


class LimitadorDeTaxa:
    """Contador de janela fixa por chave.

    Sem lock: `permitir` não tem `await` entre ler e gravar o contador.
    """

    def __init__(
        self,
        limite: int,
        janela_segundos: float,
        relogio: RelogioMonotonico = time.monotonic,
    ) -> None:
        self._limite = limite
        self._janela_segundos = janela_segundos
        self._relogio = relogio
        # chave (token) -> (contagem na janela atual, início da janela atual)
        self._contadores: dict[str, tuple[int, float]] = {}

    def permitir(self, chave: str) -> bool:
        agora = self._relogio()
        contagem, inicio = self._contadores.get(chave, (0, agora))
        if agora - inicio >= self._janela_segundos:
            contagem, inicio = 0, agora
        contagem += 1
        self._contadores[chave] = (contagem, inicio)
        return contagem <= self._limite


@lru_cache
def _limitador_processamentos() -> LimitadorDeTaxa:
    settings = get_settings()
    return LimitadorDeTaxa(settings.rate_limit_processamentos_por_minuto, 60.0)


@lru_cache
def _limitador_materiais() -> LimitadorDeTaxa:
    settings = get_settings()
    return LimitadorDeTaxa(settings.rate_limit_materiais_por_minuto, 60.0)


@lru_cache
def _limitador_perfis() -> LimitadorDeTaxa:
    settings = get_settings()
    return LimitadorDeTaxa(settings.rate_limit_perfis_por_minuto, 60.0)


def _criar_dependencia_de_limite(
    obter_limitador: Callable[[], LimitadorDeTaxa],
) -> Callable[..., Awaitable[None]]:
    # Fábrica evita duplicar extração do token e levantamento do 429 entre as rotas
    # protegidas: cada chamada gera uma dependency FastAPI própria, com seu LimitadorDeTaxa.
    async def _verificar(
        authorization: str | None = Header(default=None),
        # Depends repetido de propósito: já roda no router, mas o FastAPI cacheia o
        # resultado na requisição: isso só garante explicitamente que o token já foi validado.
        _: None = Depends(validar_token_servico),
        limitador: LimitadorDeTaxa = Depends(obter_limitador),
    ) -> None:
        token = (authorization or "").removeprefix(_PREFIXO_BEARER)
        if not limitador.permitir(token):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "LIMITE_DE_REQUISICOES_EXCEDIDO",
                    "message": "Limite de requisições excedido. Tente novamente em instantes.",
                },
            )

    return _verificar


limitar_processamentos = _criar_dependencia_de_limite(_limitador_processamentos)
limitar_materiais = _criar_dependencia_de_limite(_limitador_materiais)
limitar_perfis = _criar_dependencia_de_limite(_limitador_perfis)
