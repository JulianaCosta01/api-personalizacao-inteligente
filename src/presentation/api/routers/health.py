import asyncio
import logging

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import Executable, select, text

from core.config import Settings, get_settings
from infrastructure.database.connection import get_engine
from infrastructure.queue.models import MensagemFila

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Timeout curto de propósito: /ready precisa responder rápido mesmo com o banco fora do
# ar; sem isso, uma checagem travada faria o próprio endpoint de prontidão parecer travado.
_TIMEOUT_VERIFICACAO_SEGUNDOS = 3.0


class HealthResponse(BaseModel):
    status: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    queue: str


class ResultadoProntidao(BaseModel):
    banco_ok: bool
    fila_ok: bool


@router.get("/health", response_model=HealthResponse)
def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.environment)


async def _consultar(instrucao: Executable) -> None:
    # Conexão avulsa e curta do pool já existente (get_engine(), cacheado), não abre
    # engine novo nem participa da transação de nenhuma requisição.
    async with get_engine().connect() as conexao:
        await conexao.execute(instrucao)


async def _verificar_banco() -> bool:
    try:
        await asyncio.wait_for(_consultar(text("SELECT 1")), timeout=_TIMEOUT_VERIFICACAO_SEGUNDOS)
        return True
    except Exception:
        # Nunca deixamos a exceção original (que pode incluir DATABASE_URL em
        # alguns drivers) alcançar o cliente, só o log interno.
        logger.exception("Falha na verificação de prontidão do PostgreSQL.")
        return False


async def _verificar_fila() -> bool:
    try:
        await asyncio.wait_for(
            _consultar(select(MensagemFila.id).limit(1)), timeout=_TIMEOUT_VERIFICACAO_SEGUNDOS
        )
        return True
    except Exception:
        logger.exception("Falha na verificação de prontidão da fila de processamento.")
        return False


async def verificar_prontidao() -> ResultadoProntidao:
    """Dependency isolada para permitir override em testes (mesmo padrão já
    usado neste projeto para get_settings/get_db_session), sem precisar
    derrubar um Postgres real para testar o caminho de falha."""
    banco_ok = await _verificar_banco()
    # Sem sentido checar a fila se o banco já falhou: é a mesma instância de
    # Postgres, e evita reportar dois erros quando a causa raiz é uma só.
    fila_ok = await _verificar_fila() if banco_ok else False
    return ResultadoProntidao(banco_ok=banco_ok, fila_ok=fila_ok)


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(
    response: Response,
    resultado: ResultadoProntidao = Depends(verificar_prontidao),
) -> ReadinessResponse:
    if resultado.banco_ok and resultado.fila_ok:
        return ReadinessResponse(status="ready", database="ok", queue="ok")

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="not_ready",
        database="ok" if resultado.banco_ok else "error",
        queue="ok" if resultado.fila_ok else "error",
    )
