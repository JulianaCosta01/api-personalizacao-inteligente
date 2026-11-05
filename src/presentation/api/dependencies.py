"""Autenticação servidor-a-servidor: um SERVICE_TOKEN por instalação, via Bearer token.

Sem JWT nem sessão por aluno nesta versão; autenticação fica na borda HTTP.
"""

import hmac

from fastapi import Depends, Header, HTTPException, status

from core.config import Settings, get_settings

_PREFIXO_BEARER = "Bearer "


def erro_de_autenticacao(authorization: str | None, service_token: str) -> dict[str, str] | None:
    """Devolve o `detail` do 401 ({"code", "message"}) ou None se o token for válido.

    Única regra de autenticação, usada pela dependency e pelo middleware que protege o corpo
    da requisição antes do parse.
    """
    if authorization is None or not authorization.startswith(_PREFIXO_BEARER):
        return {"code": "TOKEN_AUSENTE", "message": "Token de serviço ausente."}

    token = authorization.removeprefix(_PREFIXO_BEARER)
    # compare_digest em vez de "==": comparação em tempo constante, para não
    # vazar o tamanho de acerto do token por timing.
    if not hmac.compare_digest(token.encode(), service_token.encode()):
        return {"code": "TOKEN_INVALIDO", "message": "Token de serviço inválido."}
    return None


async def validar_token_servico(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    erro = erro_de_autenticacao(authorization, settings.service_token)
    if erro is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=erro)
