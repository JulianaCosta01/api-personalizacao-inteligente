from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.exceptions import registrar_exception_handlers
from core.logging import configurar_logging
from presentation.api.middleware import RequestIDMiddleware, SecurityHeadersMiddleware
from presentation.api.protecao_corpo import ProtecaoDeCorpoMiddleware
from presentation.api.routers import api_router


def create_app() -> FastAPI:
    settings = get_settings()
    configurar_logging(settings.log_level)

    # Documentação interativa e esquema OpenAPI só em desenvolvimento: fora dele, publicar o mapa
    # completo da API (e a página de testes) sem autenticação ajuda só quem a ataca.
    documentacao_ativa = settings.environment == "development"
    app = FastAPI(
        title="MPI — Personalização Inteligente de Materiais Didáticos",
        version="0.1.0",
        docs_url="/docs" if documentacao_ativa else None,
        redoc_url="/redoc" if documentacao_ativa else None,
        openapi_url="/openapi.json" if documentacao_ativa else None,
    )
    # CORS fica mais interno: mesmo num preflight interceptado, a resposta ainda passa pelos
    # middlewares de request id e de security headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_efetivas,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    # Fica fora do CORS e dentro dos dois seguintes: 401/413 já saem com X-Request-ID e headers de
    # segurança, e nenhum corpo é lido pelo FastAPI antes da autenticação e do limite de tamanho.
    app.add_middleware(ProtecaoDeCorpoMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)
    registrar_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
