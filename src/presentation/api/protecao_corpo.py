import json
from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.config import Settings, get_settings
from presentation.api.dependencies import erro_de_autenticacao

Escopo = MutableMapping[str, Any]

# Folga do multipart (limites, cabeçalhos das partes e campos de texto) sobre o tamanho do arquivo.
FOLGA_DO_MULTIPART_BYTES = 256 * 1024
_PREFIXO_DA_API = "/api/"
_CAMINHO_DE_UPLOAD = "/api/v1/materiais"


class ProtecaoDeCorpoMiddleware:
    """Autentica e limita o corpo das requisições da API antes de qualquer parse.

    O FastAPI lê o corpo antes das dependências; sem isto, um cliente sem token faria o
    servidor alocar um corpo enorme. Sem token: 401 sem ler nada. Com token: leitura em blocos
    com teto (413). Slow body fica a cargo do proxy de borda.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not scope["path"].startswith(_PREFIXO_DA_API)
            or scope["method"] == "OPTIONS"
        ):
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        cabecalhos = _cabecalhos(scope)

        erro = erro_de_autenticacao(
            _texto(cabecalhos.get(b"authorization")), settings.service_token
        )
        if erro is not None:
            await _responder(send, 401, erro["code"], erro["message"])
            return

        limite = _limite_do_corpo(scope, settings)
        declarado = _texto(cabecalhos.get(b"content-length"))
        if (
            declarado is not None
            and declarado.isascii()
            and declarado.isdigit()
            and int(declarado) > limite
        ):
            await _responder_corpo_grande(send, limite)
            return

        corpo = bytearray()
        while True:
            mensagem = await receive()
            if mensagem["type"] == "http.disconnect":
                return
            corpo.extend(mensagem.get("body", b""))
            if len(corpo) > limite:
                await _responder_corpo_grande(send, limite)
                return
            if not mensagem.get("more_body", False):
                break

        entregue = False

        async def receive_com_corpo_limitado() -> Message:
            nonlocal entregue
            if not entregue:
                entregue = True
                return {"type": "http.request", "body": bytes(corpo), "more_body": False}
            # Depois do corpo, o que resta é a detecção de desconexão do cliente, como no servidor.
            return await receive()

        await self.app(scope, receive_com_corpo_limitado, send)


def _limite_do_corpo(scope: Escopo, settings: Settings) -> int:
    if scope["method"] == "POST" and scope["path"].rstrip("/") == _CAMINHO_DE_UPLOAD:
        return settings.material_tamanho_maximo_bytes + FOLGA_DO_MULTIPART_BYTES
    return settings.corpo_json_tamanho_maximo_bytes


def _cabecalhos(scope: Escopo) -> dict[bytes, bytes]:
    # Primeira ocorrência de cada cabeçalho, como o Starlette faz em Headers.get.
    resultado: dict[bytes, bytes] = {}
    for nome, valor in scope.get("headers", []):
        resultado.setdefault(bytes(nome).lower(), bytes(valor))
    return resultado


def _texto(valor: bytes | None) -> str | None:
    return None if valor is None else valor.decode("latin-1")


async def _responder_corpo_grande(send: Send, limite: int) -> None:
    await _responder(
        send,
        413,
        "CORPO_MUITO_GRANDE",
        f"O corpo da requisição excede o limite de {limite} bytes.",
    )


async def _responder(send: Send, status: int, code: str, message: str) -> None:
    # Mesmo envelope de core/exceptions.py.
    corpo = json.dumps(
        {"error": {"code": code, "message": message, "details": {}}}, ensure_ascii=False
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(corpo)).encode()),
                # Fecha a conexão: o corpo não lido (se houver) não deve ser reaproveitado.
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": corpo})
