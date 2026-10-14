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
from infrastructure.imagens import openai_adapter
from infrastructure.imagens.openai_adapter import ErroDeConfiguracaoDeImagens, OpenAIImageAdapter
from tests.unit.application.ports.imagens_fixture import jpeg_valido, png_valido

_PNG = png_valido()
_JPEG = jpeg_valido()
_CHAVE = "sk-chave-de-teste-que-nao-pode-vazar"
_DESCRICAO = "Grafo com três nós ligados por arestas"


def _conceito() -> ConceitoVisual:
    return ConceitoVisual("c1", _DESCRICAO, "ancora-1")


def _ok(conteudo: bytes = _PNG) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(conteudo).decode()}]})


class _Espera:
    def __init__(self) -> None:
        self.valores: list[float] = []

    async def __call__(self, segundos: float) -> None:
        self.valores.append(segundos)


def _adaptador(
    handler: Callable[[httpx.Request], httpx.Response],
    espera: _Espera | None = None,
    timeout_total: float = 30.0,
) -> OpenAIImageAdapter:
    cliente = httpx.AsyncClient(
        base_url="https://api.openai.teste/v1",
        headers={"Authorization": f"Bearer {_CHAVE}"},
        transport=httpx.MockTransport(handler),
    )
    return OpenAIImageAdapter(
        cliente,
        modelo="modelo-x",
        qualidade="low",
        tamanho="1024x1024",
        timeout_segundos=10.0,
        timeout_total_segundos=timeout_total,
        dormir=espera or _Espera(),
    )


def _motivo(resultado: object) -> MotivoFalhaImagem:
    assert isinstance(resultado, FalhaGeracaoImagem)
    return resultado.motivo


# --- sucesso e formato da requisição ---------------------------------------------------------


async def test_sucesso_devolve_imagem_gerada_png() -> None:
    resultado = await _adaptador(lambda r: _ok()).gerar(_conceito())
    assert isinstance(resultado, ImagemGerada)
    assert resultado.conteudo == _PNG
    assert resultado.extensao == "png"
    assert resultado.texto_alternativo == _DESCRICAO


async def test_aceita_jpeg_devolvido_pelo_provedor() -> None:
    resultado = await _adaptador(lambda r: _ok(_JPEG)).gerar(_conceito())
    assert isinstance(resultado, ImagemGerada)
    assert resultado.extensao == "jpeg"


async def test_requisicao_usa_endpoint_metodo_e_parametros_esperados() -> None:
    capturadas: list[httpx.Request] = []

    def handler(requisicao: httpx.Request) -> httpx.Response:
        capturadas.append(requisicao)
        return _ok()

    await _adaptador(handler).gerar(_conceito())

    assert len(capturadas) == 1
    requisicao = capturadas[0]
    assert requisicao.method == "POST"
    assert requisicao.url.path == "/v1/images/generations"
    assert requisicao.headers["authorization"] == f"Bearer {_CHAVE}"
    corpo = json.loads(requisicao.content)
    assert corpo["model"] == "modelo-x"
    assert corpo["size"] == "1024x1024"
    assert corpo["quality"] == "low"
    assert corpo["n"] == 1
    assert corpo["output_format"] == "png"
    assert "response_format" not in corpo


async def test_prompt_leva_so_o_molde_e_a_descricao_do_conceito() -> None:
    capturadas: list[dict[str, Any]] = []

    def handler(requisicao: httpx.Request) -> httpx.Response:
        capturadas.append(json.loads(requisicao.content))
        return _ok()

    await _adaptador(handler).gerar(_conceito())

    assert _DESCRICAO in capturadas[0]["prompt"]
    assert set(capturadas[0]) == {"model", "prompt", "n", "size", "quality", "output_format"}
    assert "ancora-1" not in capturadas[0]["prompt"]
    assert len(capturadas[0]["prompt"]) < 1000


# --- timeouts e transporte -------------------------------------------------------------------


async def test_read_timeout_vira_falha_de_timeout_sem_repetir() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        raise httpx.ReadTimeout("detalhe interno com a chave " + _CHAVE, request=requisicao)

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.TIMEOUT
    assert chamadas == 1


async def test_connect_timeout_repete_uma_vez_e_depois_falha_com_timeout() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        raise httpx.ConnectTimeout("x", request=requisicao)

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.TIMEOUT
    assert chamadas == 2


async def test_erro_de_conexao_repete_uma_vez_e_depois_falha_como_indisponivel() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        raise httpx.ConnectError("x", request=requisicao)

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert chamadas == 2


async def test_outro_erro_de_transporte_nao_repete() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        raise httpx.RemoteProtocolError("x", request=requisicao)

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert chamadas == 1


async def test_orcamento_total_esgotado_vira_timeout() -> None:
    async def lenta(segundos: float) -> None:
        await asyncio.sleep(5)

    def handler(requisicao: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    adaptador = _adaptador(handler, timeout_total=0.05)
    adaptador._dormir = lenta
    resultado = await adaptador.gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.TIMEOUT


# --- 429 e 5xx --------------------------------------------------------------------------------


async def test_429_de_rate_limit_repete_uma_vez_respeitando_retry_after() -> None:
    respostas = [
        httpx.Response(429, headers={"Retry-After": "3"}, json={"error": {"code": "rate_limit"}}),
        _ok(),
    ]
    espera = _Espera()
    resultado = await _adaptador(lambda r: respostas.pop(0), espera).gerar(_conceito())
    assert isinstance(resultado, ImagemGerada)
    assert len(espera.valores) == 1
    assert 3.0 <= espera.valores[0] <= 3.0 + openai_adapter._JITTER_MAXIMO_SEGUNDOS


async def test_429_persistente_para_depois_de_uma_repeticao_com_limite_excedido() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}})

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.LIMITE_EXCEDIDO
    assert chamadas == 2


@pytest.mark.parametrize(
    "codigo",
    [
        "insufficient_quota",
        "credit_balance_exhausted",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
    ],
)
async def test_429_de_cota_ou_gasto_nao_repete(codigo: str) -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(429, json={"error": {"code": codigo}})

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.LIMITE_EXCEDIDO
    assert chamadas == 1


async def test_espera_pedida_pelo_provedor_e_limitada() -> None:
    respostas = [httpx.Response(429, headers={"Retry-After": "9999"}), _ok()]
    espera = _Espera()
    await _adaptador(lambda r: respostas.pop(0), espera).gerar(_conceito())
    maximo = openai_adapter._ESPERA_MAXIMA_ENTRE_TENTATIVAS_SEGUNDOS
    assert espera.valores[0] <= maximo + openai_adapter._JITTER_MAXIMO_SEGUNDOS


async def test_retry_after_invalido_usa_a_espera_padrao() -> None:
    respostas = [httpx.Response(503, headers={"Retry-After": "tomorrow"}), _ok()]
    espera = _Espera()
    await _adaptador(lambda r: respostas.pop(0), espera).gerar(_conceito())
    padrao = openai_adapter._ESPERA_PADRAO_ENTRE_TENTATIVAS_SEGUNDOS
    assert padrao <= espera.valores[0] <= padrao + openai_adapter._JITTER_MAXIMO_SEGUNDOS


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_5xx_repete_uma_vez_e_recupera(status: int) -> None:
    respostas = [httpx.Response(status), _ok()]
    resultado = await _adaptador(lambda r: respostas.pop(0)).gerar(_conceito())
    assert isinstance(resultado, ImagemGerada)


async def test_5xx_persistente_para_depois_de_uma_repeticao() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(503, json={"error": {"code": "server_is_overloaded"}})

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert chamadas == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_4xx_de_configuracao_nao_repete(status: int) -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(status, json={"error": {"code": "invalid_api_key"}})

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert chamadas == 1


async def test_recusa_de_moderacao_vira_conteudo_recusado_sem_repetir() -> None:
    chamadas = 0

    def handler(requisicao: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(400, json={"error": {"code": "moderation_blocked"}})

    resultado = await _adaptador(handler).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.CONTEUDO_RECUSADO
    assert chamadas == 1


async def test_corpo_de_erro_que_nao_e_json_nao_quebra() -> None:
    resultado = await _adaptador(lambda r: httpx.Response(400, text="<html>erro</html>")).gerar(
        _conceito()
    )
    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL


# --- resposta inválida -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "resposta",
    [
        httpx.Response(200, text="não é json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json={"data": [{}]}),
        httpx.Response(200, json={"data": [{"b64_json": None}]}),
        httpx.Response(200, json={"data": [{"b64_json": ""}]}),
        httpx.Response(200, json={"data": [{"b64_json": 123}]}),
        httpx.Response(200, json={"data": ["texto"]}),
        httpx.Response(200, json={"data": [{"url": "https://exemplo.teste/x.png"}]}),
    ],
)
async def test_resposta_malformada_vira_resposta_invalida(resposta: httpx.Response) -> None:
    resultado = await _adaptador(lambda r: resposta).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


@pytest.mark.parametrize("b64", ["isso não é base64!!", "abc", "====", "YWJj\nZGVm", "é"])
async def test_base64_corrompido_vira_resposta_invalida(b64: str) -> None:
    resposta = httpx.Response(200, json={"data": [{"b64_json": b64}]})
    resultado = await _adaptador(lambda r: resposta).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


@pytest.mark.parametrize(
    "conteudo",
    [b"GIF89a....", b"<svg onload=alert(1)></svg>", b"%PDF-1.7", b"RIFF....WEBP", b"texto"],
)
async def test_imagem_de_formato_nao_suportado_vira_resposta_invalida(conteudo: bytes) -> None:
    resultado = await _adaptador(lambda r: _ok(conteudo)).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


async def test_imagem_acima_do_limite_vira_resposta_invalida() -> None:
    grande = _PNG + b"0" * TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES
    resultado = await _adaptador(lambda r: _ok(grande)).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


async def test_base64_gigante_e_recusado_antes_de_decodificar() -> None:
    enorme = "A" * (openai_adapter._TAMANHO_MAXIMO_DO_BASE64 + 4)
    resposta = httpx.Response(200, json={"data": [{"b64_json": enorme}]})
    resultado = await _adaptador(lambda r: resposta).gerar(_conceito())
    assert _motivo(resultado) is MotivoFalhaImagem.RESPOSTA_INVALIDA


async def test_falha_devolvida_guarda_o_identificador_do_conceito() -> None:
    resultado = await _adaptador(lambda r: httpx.Response(401)).gerar(_conceito())
    assert isinstance(resultado, FalhaGeracaoImagem)
    assert resultado.identificador_do_conceito == "c1"


# --- configuração e recusa de execução -------------------------------------------------------


def _settings(**alteracoes: Any) -> Settings:
    return Settings(_env_file=None, **alteracoes)


def _sem_rede(requisicao: httpx.Request) -> httpx.Response:
    raise AssertionError("nenhuma chamada de rede era esperada")


def test_desativada_recusa_a_criacao_sem_rede() -> None:
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_sem_rede))
    with pytest.raises(ErroDeConfiguracaoDeImagens, match="desativada"):
        OpenAIImageAdapter.a_partir_de_settings(_settings(), cliente)


def test_sem_chave_recusa_a_criacao() -> None:
    settings = _settings()
    settings.imagens_geradas_habilitadas = True
    settings.openai_image_model = "modelo-x"
    with pytest.raises(ErroDeConfiguracaoDeImagens, match="Chave"):
        OpenAIImageAdapter.a_partir_de_settings(settings)


def test_sem_modelo_recusa_a_criacao_e_nao_inventa_padrao() -> None:
    settings = _settings()
    settings.imagens_geradas_habilitadas = True
    settings.openai_api_key = _settings(openai_api_key=_CHAVE).openai_api_key
    with pytest.raises(ErroDeConfiguracaoDeImagens, match="Modelo"):
        OpenAIImageAdapter.a_partir_de_settings(settings)


def test_modelo_em_branco_no_construtor_e_recusado() -> None:
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_sem_rede))
    with pytest.raises(ErroDeConfiguracaoDeImagens):
        OpenAIImageAdapter(cliente, "  ", "low", "1024x1024", 10.0, 30.0)


def test_mensagens_de_configuracao_nao_trazem_valores() -> None:
    settings = _settings(openai_api_key=_CHAVE)
    with pytest.raises(ErroDeConfiguracaoDeImagens) as erro:
        OpenAIImageAdapter.a_partir_de_settings(settings)
    assert _CHAVE not in str(erro.value)


async def test_configuracao_completa_cria_adaptador_com_valores_das_settings() -> None:
    capturadas: list[httpx.Request] = []

    def handler(requisicao: httpx.Request) -> httpx.Response:
        capturadas.append(requisicao)
        return _ok()

    settings = _settings(
        imagens_geradas_habilitadas=True,
        openai_api_key=_CHAVE,
        openai_image_model="modelo-x",
        openai_image_quality="medium",
        openai_image_size="1536x1024",
    )
    cliente = httpx.AsyncClient(
        base_url="https://api.openai.teste/v1", transport=httpx.MockTransport(handler)
    )
    adaptador = OpenAIImageAdapter.a_partir_de_settings(settings, cliente)
    resultado = await adaptador.gerar(_conceito())

    assert isinstance(resultado, ImagemGerada)
    corpo = json.loads(capturadas[0].content)
    assert (corpo["model"], corpo["quality"], corpo["size"]) == ("modelo-x", "medium", "1536x1024")


def test_cliente_padrao_aponta_para_host_fixo_com_timeout_e_sem_redirecionamento() -> None:
    settings = _settings(
        imagens_geradas_habilitadas=True, openai_api_key=_CHAVE, openai_image_model="modelo-x"
    )
    adaptador = OpenAIImageAdapter.a_partir_de_settings(settings)
    cliente = adaptador._cliente
    assert str(cliente.base_url).rstrip("/") == "https://api.openai.com/v1"
    assert cliente.follow_redirects is False
    assert cliente.timeout.read == settings.openai_image_timeout_segundos
    assert cliente.timeout.connect == openai_adapter._TIMEOUT_DE_CONEXAO_SEGUNDOS


# --- logs ------------------------------------------------------------------------------------


async def test_logs_nao_contem_prompt_chave_corpo_nem_texto_da_excecao(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(requisicao: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": "moderation_blocked", "message": "SEGREDO-NO-CORPO"}}
        )

    def handler_com_excecao(requisicao: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError(f"falha com {_CHAVE} e {_DESCRICAO}", request=requisicao)

    with caplog.at_level(logging.DEBUG):
        await _adaptador(handler).gerar(_conceito())
        await _adaptador(handler_com_excecao).gerar(_conceito())
        await _adaptador(lambda r: httpx.Response(200, text="SEGREDO-NO-CORPO")).gerar(_conceito())

    texto = "\n".join(registro.getMessage() for registro in caplog.records)
    assert texto
    for proibido in (_CHAVE, _DESCRICAO, "SEGREDO-NO-CORPO", "Bearer", "prompt"):
        assert proibido not in texto
    assert "c1" in texto


async def test_excecao_inesperada_vira_falha_e_nao_propaga(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(requisicao: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"bug interno com {_CHAVE}")

    with caplog.at_level(logging.DEBUG):
        resultado = await _adaptador(handler).gerar(_conceito())

    assert _motivo(resultado) is MotivoFalhaImagem.INDISPONIVEL
    assert _CHAVE not in "\n".join(registro.getMessage() for registro in caplog.records)
