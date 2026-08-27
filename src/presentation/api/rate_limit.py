"""Rate limiting em memória, por token de serviço (Fase 9 Task 1; Documento 4, §13.4).

Implementação própria e mínima, sem dependência nova — mesmo raciocínio já
aplicado ao JsonFormatter de core/logging.py: janela fixa, processo único,
duas rotas protegidas não justificam trazer uma biblioteca externa (ex.
slowapi) e sua árvore de dependências para um requisito deste tamanho.

Chave do limite: o próprio SERVICE_TOKEN (Documento 4, §13.4 — "aplicado por
token de serviço nesta versão, já que não há identidade individual do aluno
na própria API"), nunca IP ou identidade de aluno, que não existem como
conceito confiável nesta camada.

LIMITAÇÃO CONHECIDA — memória de processo único: o estado de cada
LimitadorDeTaxa vive num dict em memória do próprio processo Python. Isso é
correto e suficiente hoje: a API roda como um único processo (sem
`--workers`, sem múltiplas réplicas, sem orquestrador configurado — ver
Documento 4, §19, que trata isso como evolução futura). Se/quando a API
passar a rodar com múltiplos processos ou réplicas atrás de um balanceador de
carga, este mecanismo deixa de refletir um limite agregado real (cada
processo contaria de forma independente, multiplicando o limite efetivo pelo
número de réplicas) e deve ser substituído por um backend compartilhado (ex.:
Redis) antes disso acontecer. Antecipar essa infraestrutura agora, sem
necessidade arquitetural comprovada, seria prematuro.
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
    """Contador de janela fixa (fixed window) por chave.

    Janela fixa, não sliding window/token bucket: simples de auditar e
    suficiente para o critério da Fase 9 (Documento 5) — não é um requisito
    de precisão fina, é uma proteção contra abuso de custo. Uma instância por
    rota protegida, para que o limite de /processamentos nunca compita com o
    de /materiais.

    Sem asyncio.Lock: o corpo de `permitir` não tem nenhum `await` entre a
    leitura e a escrita do contador, então não há ponto de interrupção onde
    outra corrotina possa interpor uma leitura/escrita concorrente dentro do
    mesmo processo — um lock aqui seria proteção contra um risco que não
    existe no modelo de concorrência do asyncio de thread única.
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


def _criar_dependencia_de_limite(
    obter_limitador: Callable[[], LimitadorDeTaxa],
) -> Callable[..., Awaitable[None]]:
    # Fábrica para não duplicar a extração do token e o levantamento do 429
    # entre as duas rotas protegidas — cada chamada gera uma dependency FastAPI
    # independente, ligada a um LimitadorDeTaxa (e portanto um contador) próprio.
    async def _verificar(
        authorization: str | None = Header(default=None),
        # Depends repetido de propósito: já roda no router (aluno_id/token
        # ausente nunca chega aqui), mas o FastAPI cacheia o resultado da
        # mesma dependency dentro da requisição — isso só garante, de forma
        # explícita, que o token já foi validado antes de usá-lo como chave.
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
