import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from core.logging import request_id_var


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Gera (ou repassa) um id de correlação por requisição, usado nos logs
    estruturados e devolvido ao cliente — base para reconstruir a jornada de
    uma solicitação quando a Fila/Worker entrarem em cena (Documento 4, §14).
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
    """Headers de segurança exigidos pelo Documento 4, §13.7 — aplicados a
    toda resposta, inclusive Swagger/ReDoc/OpenAPI, já que o próprio §13.7
    não abre exceção para eles.

    X-Content-Type-Options e X-Frame-Options não têm variação por ambiente no
    texto do §13.7. Strict-Transport-Security é a exceção: só faz sentido
    logicamente sobre HTTPS (um navegador ignora o header recebido em HTTP
    puro), mas em produção real, atrás de TLS, precisa estar presente — por
    isso é condicionado a `environment == "production"`, seguindo o padrão já
    estabelecido no Documento 4 §12 de que diferenças de comportamento por
    ambiente passam pelo único ponto de configuração (Settings), nunca por
    lógica espalhada.
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
