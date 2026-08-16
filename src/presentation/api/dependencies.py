"""Dependências de autenticação da camada Presentation.

Modelo de autenticação servidor-a-servidor: um único SERVICE_TOKEN por
instalação, enviado como Bearer token (Documento 3, §2.2; Documento 4, §13.1).
Não há JWT, OAuth ou sessão por aluno nesta versão (Documento 4, §13.3) — é
uma dependency direta do FastAPI, sem porta/abstração de domínio, por decisão
já tomada no diagnóstico da Fase 3.
"""

import hmac

from fastapi import Depends, Header, HTTPException, status

from core.config import Settings, get_settings

_PREFIXO_BEARER = "Bearer "


async def validar_token_servico(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if authorization is None or not authorization.startswith(_PREFIXO_BEARER):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_AUSENTE", "message": "Token de serviço ausente."},
        )

    token = authorization.removeprefix(_PREFIXO_BEARER)
    # compare_digest em vez de "==": comparação em tempo constante, para não
    # vazar o tamanho de acerto do token por timing (Documento 4, §13.1).
    if not hmac.compare_digest(token, settings.service_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_INVALIDO", "message": "Token de serviço inválido."},
        )
