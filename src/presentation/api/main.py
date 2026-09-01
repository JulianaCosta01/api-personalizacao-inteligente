from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.exceptions import registrar_exception_handlers
from core.logging import configurar_logging
from presentation.api.middleware import RequestIDMiddleware, SecurityHeadersMiddleware
from presentation.api.routers import api_router


def create_app() -> FastAPI:
    settings = get_settings()
    configurar_logging(settings.log_level)

    app = FastAPI(
        title="MPI — Personalização Inteligente de Materiais Didáticos",
        version="0.1.0",
    )
    # CORSMiddleware vai primeiro (mais interno): num preflight interceptado, a resposta ainda passa por RequestIDMiddleware e SecurityHeadersMiddleware, que sempre pós-processam via BaseHTTPMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_efetivas,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)
    registrar_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
