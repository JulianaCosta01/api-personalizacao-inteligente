"""Tratamento central de exceções (Documento 4, Seção 15).

Traduz a hierarquia de domínio para o código HTTP e o envelope de erro
padronizados no Documento 3 (§2.4 e §6). Qualquer exceção não mapeada é
tratada como 500, com detalhes internos apenas no log — nunca no corpo
da resposta.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from domain.shared.exceptions import (
    ConflitoDeEstadoError,
    DomainError,
    EntradaInvalidaError,
    RecursoNaoEncontradoError,
    RegraDeNegocioVioladaError,
)

logger = logging.getLogger(__name__)

_STATUS_POR_EXCECAO: dict[type[DomainError], int] = {
    EntradaInvalidaError: status.HTTP_400_BAD_REQUEST,
    RecursoNaoEncontradoError: status.HTTP_404_NOT_FOUND,
    # 422 fica como literal: o nome da constante muda entre versões do starlette,
    # e o número é exatamente o que o Documento 3 (§6) especifica.
    RegraDeNegocioVioladaError: 422,
    ConflitoDeEstadoError: status.HTTP_409_CONFLICT,
}


def _envelope(code: str, message: str, details: dict[str, Any] | None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _erro_json(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=_envelope(code, message, details))


async def _tratar_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    status_code = _STATUS_POR_EXCECAO.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _erro_json(status_code, exc.code, exc.message, exc.details)


async def _tratar_validacao(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return _erro_json(
        status.HTTP_400_BAD_REQUEST,
        "REQUISICAO_INVALIDA",
        "Corpo da requisição malformado ou campo obrigatório ausente.",
        {"erros": jsonable_encoder(exc.errors())},
    )


async def _tratar_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # HTTPException cobre erros que não vêm do domínio (ex.: token ausente/inválido,
    # já com detail em {"code", "message"}) ou vêm do próprio Starlette (ex.: rota inexistente).
    if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
        return _erro_json(exc.status_code, exc.detail["code"], exc.detail["message"])
    return _erro_json(exc.status_code, "ERRO_HTTP", str(exc.detail))


async def _tratar_erro_interno(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Erro não tratado em %s %s", request.method, request.url.path)
    return _erro_json(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "ERRO_INTERNO",
        "Ocorreu um erro inesperado. Tente novamente mais tarde.",
    )


def registrar_exception_handlers(app: FastAPI) -> None:
    # add_exception_handler é tipado para receber handlers de Exception genérica;
    # o Starlette despacha pelo tipo registrado na chave, então isso é seguro em runtime.
    app.add_exception_handler(DomainError, _tratar_domain_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _tratar_validacao)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _tratar_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _tratar_erro_interno)
