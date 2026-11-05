import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from core.logging import request_id_var


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Gera (ou repassa) um id de correlação por requisição, usado nos logs
    estruturados e devolvido ao cliente: base para reconstruir a jornada de
    uma solicitação quando a Fila/Worker entrarem em cena.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Headers de segurança aplicados a toda resposta, inclusive Swagger/ReDoc/OpenAPI.

    Strict-Transport-Security só é enviado em produção: só faz sentido sobre HTTPS,
    e o ambiente vem de Settings, nunca de lógica espalhada.
    """

    def __init__(self, app: ASGIApp, environment: str) -> None:
        super().__init__(app)
        self._environment = environment

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if self._environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
