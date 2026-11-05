"""Logging estruturado em JSON, com correlação por requisição.

Usa apenas a biblioteca padrão: um formatter próprio é suficiente para o formato
exigido (JSON + request_id), e evita depender de structlog/python-json-logger
para um requisito deste tamanho.
"""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configurar_logging(log_level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level.upper())

    # uvicorn registra os próprios handlers (texto simples) para "uvicorn.access" e
    # "uvicorn.error"; sem isso, os logs de acesso HTTP fugiriam do formato JSON.
    for nome in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger_uvicorn = logging.getLogger(nome)
        logger_uvicorn.handlers = []
        logger_uvicorn.propagate = True
