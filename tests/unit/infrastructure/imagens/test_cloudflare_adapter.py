import asyncio
import base64
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from application.ports.gerador_imagens import (
    TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES,
    ConceitoVisual,
    FalhaGeracaoImagem,
    ImagemGerada,
    MotivoFalhaImagem,
)
from infrastructure.config.settings import Settings
from infrastructure.imagens import cloudflare_adapter
from infrastructure.imagens.cloudflare_adapter import (
    TAMANHO_MAXIMO_DO_PROMPT,
    CloudflareImageAdapter,
    ErroDeConfiguracaoDeImagensCloudflare,
)
from tests.unit.application.ports.imagens_fixture import jpeg_valido, png_valido

_PNG = png_valido()
_JPEG = jpeg_valido()
_TOKEN = "cf-token-de-teste-que-nao-pode-vazar"
_CONTA = "0123456789abcdef0123456789abcdef"
_MODELO = "@cf/black-forest-labs/flux-1-schnell"
_DESCRICAO = "Grafo com três nós ligados por arestas"
_CAMINHO = f"/client/v4/accounts/{_CONTA}/ai/run/{_MODELO}"


def _conceito(descricao: str = _DESCRICAO) -> ConceitoVisual:
    return ConceitoVisual("c1", descricao, "ancora-1")


def _ok(conteudo: bytes = _JPEG) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "result": {"image": base64.b64encode(conteudo).decode()},
            "success": True,
            "errors": [],
            "messages": [],
        },
    )


class _Espera:
    def __init__(self) -> None:
        self.valores: list[float] = []

    async def __call__(self, segundos: float) -> None:
        self.valores.append(segundos)


def _adaptador(
    handler: Callable[[httpx.Request], httpx.Response],
    espera: _Espera | None = None,
    timeout_total: float = 30.0,
    passos: int = 4,
) -> CloudflareImageAdapter:
    cliente = httpx.AsyncClient(
        base_url="https://api.cloudflare.com/client/v4",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        transport=httpx.MockTransport(handler),
    )
    return CloudflareImageAdapter(
        cliente,
        id_da_conta=_CONTA,
        modelo=_MODELO,
        passos=passos,
        timeout_segundos=10.0,
        timeout_total_segundos=timeout_total,
        dormir=espera or _Espera(),
    )


def _motivo(resultado: object) -> MotivoFalhaImagem:
    assert isinstance(resultado, FalhaGeracaoImagem)
    return resultado.motivo


def _settings(**alteracoes: Any) -> Settings:
    return Settings(_env_file=None, **alteracoes)


def _settings_cloudflare(**alteracoes: Any) -> Settings:
    base: dict[str, Any] = {
        "imagens_geradas_habilitadas": True,
        "imagens_provedor": "cloudflare",
        "cloudflare_account_id": _CONTA,
        "cloudflare_api_token": _TOKEN,
        "cloudflare_image_model": _MODELO,
    }
    base.update(alteracoes)
    return _settings(**base)


# Sucesso e formato da requisição


async def test_sucesso_devolve_imagem_gerada_jpeg() -> None:
    resultado = await _adaptador(lambda r: _ok()).gerar(_conceito())
    assert isinstance(resultado, ImagemGerada)
    assert resultado.conteudo == _JPEG
    assert resultado.extensao == "jpeg"
    assert resultado.texto_alternativo == _DESCRICAO


async def test_aceita_png_devolvido_pelo_provedor() -> None:
    resultado = await _adaptador(lambda r: _ok(_PNG)).gerar(_conceito())
    assert isinstance(resultado, ImagemGerada)
    assert resultado.extensao == "png"


async def test_requisicao_usa_endpoint_metodo_e_parametros_esperados() -> None:
    capturadas: list[httpx.Request] = []

    def handler(requisicao: httpx.Request) -> httpx.Response:
        capturadas.append(requisicao)
        return _ok()

    await _adaptador(handler, passos=6).gerar(_conceito())

    assert len(capturadas) == 1
    requisicao = capturadas[0]
    assert requisicao.method == "POST"
    assert requisicao.url.host == "api.cloudflare.com"
    assert requisicao.url.path == _CAMINHO
    assert requisicao.headers["authorization"] == f"Bearer {_TOKEN}"
    corpo = json.loads(requisicao.content)
    assert set(corpo) == {"prompt", "steps"}
    assert corpo["steps"] == 6


async def test_prompt_leva_so_o_molde_e_a_descricao_do_conceito() -> None:
    capturadas: list[dict[str, Any]] = []

    def handler(requisicao: httpx.Request) -> httpx.Response:
        capturadas.append(json.loads(requisicao.content))
        return _ok()

    await _adaptador(handler).gerar(_conceito())

    prompt = capturadas[0]["prompt"]
    assert _DESCRICAO in prompt
    assert "no text" in prompt
    for proibido in (_TOKEN, _CONTA, _MODELO):
        assert proibido not in prompt


def test_prompt_mais_longo_possivel_cabe_no_limite_do_modelo() -> None:
    descricao_maxima = "x" * 300
    prompt = cloudflare_adapter._MOLDE_DO_PROMPT.format(descricao=descricao_maxima)
    assert len(prompt) <= TAMANHO_MAXIMO_DO_PROMPT


# Tempo e tentativas


async def test_read_timeout_vira_falha_de_timeout_sem_repetir() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        raise httpx.ReadTimeout("lento", request=requisicao)

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.TIMEOUT
    assert chamadas == 1


async def test_connect_timeout_repete_uma_vez_e_depois_falha_com_timeout() -> None:
    chamadas = 0
    espera = _Espera()

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        raise httpx.ConnectTimeout("sem conexao", request=requisicao)

    resultado = await _adaptador(handler, espera).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.TIMEOUT
    assert chamadas == 2
    assert len(espera.valores) == 1


async def test_erro_de_conexao_repete_uma_vez_e_depois_falha_como_indisponivel() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        raise httpx.ConnectError("recusada", request=requisicao)

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert chamadas == 2


async def test_outro_erro_de_transporte_nao_repete() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        raise httpx.RemoteProtocolError("quebrou", request=requisicao)

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert chamadas == 1


async def test_orcamento_total_esgotado_vira_timeout() -> None:
    async def lento(requisicao: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return _ok()

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(lento))
    adaptador = CloudflareImageAdapter(cliente, _CONTA, _MODELO, 4, 10.0, 0.05)
    assert _motivo(await adaptador.gerar(_conceito())) is MotivoFalhaImagem.TIMEOUT


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_5xx_repete_uma_vez_e_recupera(status: int) -> None:
    respostas = [httpx.Response(status), _ok()]
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return respostas.pop(0)

    resultado = await _adaptador(handler).gerar(_conceito())
    assert isinstance(resultado, ImagemGerada)
    assert chamadas == 2


async def test_5xx_persistente_para_depois_de_uma_repeticao() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(503)

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert chamadas == 2


async def test_espera_pedida_pelo_provedor_e_limitada() -> None:
    espera = _Espera()
    respostas = [httpx.Response(503, headers={"retry-after": "3600"}), _ok()]
    await _adaptador(lambda r: respostas.pop(0), espera).gerar(_conceito())
    assert len(espera.valores) == 1
    assert espera.valores[0] <= (
        cloudflare_adapter._ESPERA_MAXIMA_ENTRE_TENTATIVAS_SEGUNDOS
        + cloudflare_adapter._JITTER_MAXIMO_SEGUNDOS
    )


async def test_retry_after_invalido_usa_a_espera_padrao() -> None:
    espera = _Espera()
    respostas = [httpx.Response(503, headers={"retry-after": "amanha"}), _ok()]
    await _adaptador(lambda r: respostas.pop(0), espera).gerar(_conceito())
    padrao = cloudflare_adapter._ESPERA_PADRAO_ENTRE_TENTATIVAS_SEGUNDOS
    assert padrao <= espera.valores[0] <= padrao + cloudflare_adapter._JITTER_MAXIMO_SEGUNDOS


# Erros que NUNCA repetem (cota diária, configuração)


@pytest.mark.parametrize(
    "corpo",
    [
        {"errors": [{"code": 4006, "message": "daily free allocation used"}], "success": False},
        {"errors": [], "success": False},
    ],
)
async def test_429_nao_repete_e_vira_limite_excedido(corpo: dict[str, Any]) -> None:
    chamadas = 0
    espera = _Espera()

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(429, json=corpo, headers={"retry-after": "1"})

    resultado = await _adaptador(handler, espera).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.LIMITE_EXCEDIDO
    assert chamadas == 1
    assert espera.valores == []


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_4xx_de_configuracao_nao_repete(status: int) -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(status, json={"success": False, "errors": [{"code": 1}]})

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert chamadas == 1


async def test_corpo_de_erro_que_nao_e_json_nao_quebra() -> None:
    resultado = await _adaptador(lambda r: httpx.Response(400, text="<html>erro</html>")).gerar(
        _conceito()
    )
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL


# Resposta inválida


@pytest.mark.parametrize(
    "resposta",
    [
        httpx.Response(200, text="não é json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"result": {}}),
        httpx.Response(200, json={"result": None}),
        httpx.Response(200, json={"result": "texto"}),
        httpx.Response(200, json={"result": {"image": ""}}),
        httpx.Response(200, json={"result": {"image": 123}}),
        httpx.Response(200, json={"success": False, "result": {"image": "AAAA"}}),
    ],
)
async def test_resposta_malformada_vira_resposta_invalida(resposta: httpx.Response) -> None:
    resultado = await _adaptador(lambda r: resposta).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


@pytest.mark.parametrize("b64", ["não-é-base64!!", "AAAA===", "abc"])
async def test_base64_corrompido_vira_resposta_invalida(b64: str) -> None:
    resposta = httpx.Response(200, json={"result": {"image": b64}, "success": True})
    resultado = await _adaptador(lambda r: resposta).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


async def test_base64_com_quebras_de_linha_e_tolerado() -> None:
    codificado = base64.encodebytes(_JPEG).decode()
    assert "\n" in codificado
    resposta = httpx.Response(200, json={"result": {"image": codificado}, "success": True})
    resultado = await _adaptador(lambda r: resposta).gerar(_conceito())
    assert isinstance(resultado, ImagemGerada)
    assert resultado.conteudo == _JPEG


@pytest.mark.parametrize("conteudo", [b"GIF89a...", b"<svg></svg>", b"%PDF-1.4", b"x" * 50])
async def test_imagem_de_formato_nao_suportado_vira_resposta_invalida(conteudo: bytes) -> None:
    resultado = await _adaptador(lambda r: _ok(conteudo)).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


async def test_imagem_acima_do_limite_vira_resposta_invalida() -> None:
    grande = _JPEG + b"\x00" * TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES
    resultado = await _adaptador(lambda r: _ok(grande)).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


async def test_base64_gigante_e_recusado_antes_de_decodificar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def nao_deve_decodificar(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("não deveria decodificar")

    monkeypatch.setattr(cloudflare_adapter.base64, "b64decode", nao_deve_decodificar)
    enorme = "A" * (cloudflare_adapter._TAMANHO_MAXIMO_DO_BASE64 + 1)
    resposta = httpx.Response(200, json={"result": {"image": enorme}, "success": True})
    resultado = await _adaptador(lambda r: resposta).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


async def test_falha_devolvida_guarda_o_identificador_do_conceito() -> None:
    resultado = await _adaptador(lambda r: httpx.Response(401)).gerar(_conceito())
    assert isinstance(resultado, FalhaGeracaoImagem)
    assert resultado.identificador_do_conceito == "c1"


# Configuração


def _sem_rede(requisicao: httpx.Request) -> httpx.Response:
    raise AssertionError("nenhuma chamada de rede era esperada")


def test_desativada_recusa_a_criacao_sem_rede() -> None:
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_sem_rede))
    settings = _settings(imagens_provedor="cloudflare")
    with pytest.raises(ErroDeConfiguracaoDeImagensCloudflare, match="desativada"):
        CloudflareImageAdapter.a_partir_de_settings(settings, cliente)


@pytest.mark.parametrize(
    ("campo", "trecho"),
    [
        ("cloudflare_account_id", "conta"),
        ("cloudflare_api_token", "Token"),
        ("cloudflare_image_model", "Modelo"),
    ],
)
def test_faltando_credencial_ou_modelo_a_criacao_e_recusada(campo: str, trecho: str) -> None:
    settings = _settings_cloudflare()
    setattr(settings, campo, None)
    with pytest.raises(ErroDeConfiguracaoDeImagensCloudflare, match=trecho):
        CloudflareImageAdapter.a_partir_de_settings(settings)


@pytest.mark.parametrize(
    "conta",
    ["", "123", "0123456789abcdef0123456789abcde", "0123456789abcdef0123456789abcdefg"]
    + ["../../../etc/passwd", "0123456789abcdef0123456789abcde/", "z" * 32],
)
def test_id_de_conta_fora_do_formato_e_recusado_no_construtor(conta: str) -> None:
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_sem_rede))
    with pytest.raises(ErroDeConfiguracaoDeImagensCloudflare):
        CloudflareImageAdapter(cliente, conta, _MODELO, 4, 10.0, 30.0)


@pytest.mark.parametrize(
    "modelo",
    ["", "flux", "@cf/x", "@cf/a/b/c", "cf/a/b", "@cf/../etc/passwd", "@cf/a/b?x=1", "@cf/a/b c"],
)
def test_modelo_fora_do_formato_e_recusado_no_construtor(modelo: str) -> None:
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_sem_rede))
    with pytest.raises(ErroDeConfiguracaoDeImagensCloudflare):
        CloudflareImageAdapter(cliente, _CONTA, modelo, 4, 10.0, 30.0)


def test_mensagens_de_configuracao_nao_trazem_valores() -> None:
    settings = _settings_cloudflare()
    settings.cloudflare_image_model = None
    with pytest.raises(ErroDeConfiguracaoDeImagensCloudflare) as erro:
        CloudflareImageAdapter.a_partir_de_settings(settings)
    for valor in (_TOKEN, _CONTA):
        assert valor not in str(erro.value)

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_sem_rede))
    with pytest.raises(ErroDeConfiguracaoDeImagensCloudflare) as erro_conta:
        CloudflareImageAdapter(cliente, "conta-invalida-secreta", _MODELO, 4, 10.0, 30.0)
    assert "conta-invalida-secreta" not in str(erro_conta.value)


async def test_configuracao_completa_cria_adaptador_com_valores_das_settings() -> None:
    capturadas: list[httpx.Request] = []

    def handler(requisicao: httpx.Request) -> httpx.Response:
        capturadas.append(requisicao)
        return _ok()

    settings = _settings_cloudflare(cloudflare_image_steps=7)
    cliente = httpx.AsyncClient(
        base_url="https://api.cloudflare.com/client/v4", transport=httpx.MockTransport(handler)
    )
    adaptador = CloudflareImageAdapter.a_partir_de_settings(settings, cliente)
    resultado = await adaptador.gerar(_conceito())

    assert isinstance(resultado, ImagemGerada)
    assert capturadas[0].url.path == _CAMINHO
    assert json.loads(capturadas[0].content)["steps"] == 7


def test_cliente_padrao_aponta_para_host_fixo_com_timeout_e_sem_redirecionamento() -> None:
    settings = _settings_cloudflare(cloudflare_image_timeout_segundos=42.0)
    adaptador = CloudflareImageAdapter.a_partir_de_settings(settings)
    cliente = adaptador._cliente
    assert str(cliente.base_url).rstrip("/") == "https://api.cloudflare.com/client/v4"
    assert cliente.follow_redirects is False
    assert cliente.timeout.read == 42.0
    assert cliente.timeout.connect == cloudflare_adapter._TIMEOUT_DE_CONEXAO_SEGUNDOS
    assert cliente.headers["authorization"] == f"Bearer {_TOKEN}"


def test_filtro_nao_e_duplicado_ao_criar_varios_adaptadores() -> None:
    _adaptador(lambda r: _ok())
    _adaptador(lambda r: _ok())
    filtros = [
        f
        for f in logging.getLogger("httpx").filters
        if isinstance(f, cloudflare_adapter._OcultaIdDaContaNosLogsDoHttpx)
    ]
    assert len(filtros) == 1


async def test_log_de_requisicao_do_httpx_nao_mostra_o_id_da_conta(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="httpx"):
        await _adaptador(lambda r: _ok()).gerar(_conceito())
    texto = "\n".join(registro.getMessage() for registro in caplog.records)
    assert "HTTP Request" in texto
    assert _CONTA not in texto
    assert "/accounts/<conta>/ai/run/" in texto


def test_token_nao_aparece_na_representacao_das_settings() -> None:
    settings = _settings_cloudflare()
    assert _TOKEN not in repr(settings)
    assert _TOKEN not in str(settings)


# Logs


async def test_logs_nao_contem_prompt_token_conta_corpo_nem_texto_da_excecao(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler_429(requisicao: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"errors": [{"code": 4006, "message": "SEGREDO-NO-CORPO"}], "success": False}
        )

    def handler_com_excecao(requisicao: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError(
            f"falha com {_TOKEN}, {_CONTA} e {_DESCRICAO}", request=requisicao
        )

    with caplog.at_level(logging.DEBUG):
        await _adaptador(handler_429).gerar(_conceito())
        await _adaptador(handler_com_excecao).gerar(_conceito())
        await _adaptador(lambda r: httpx.Response(200, text="SEGREDO-NO-CORPO")).gerar(_conceito())

    texto = "\n".join(registro.getMessage() for registro in caplog.records)
    assert texto
    for proibido in (_TOKEN, _CONTA, _DESCRICAO, "SEGREDO-NO-CORPO", "Bearer", "prompt"):
        assert proibido not in texto
    assert "c1" in texto


async def test_excecao_inesperada_vira_falha_e_nao_propaga(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(requisicao: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"bug interno com {_TOKEN}")

    with caplog.at_level(logging.DEBUG):
        resultado = await _adaptador(handler).gerar(_conceito())

    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert _TOKEN not in "\n".join(registro.getMessage() for registro in caplog.records)
