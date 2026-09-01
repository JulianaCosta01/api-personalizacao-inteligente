import asyncio
from collections.abc import Callable, Coroutine
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from google import genai
from google.genai import types

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from infrastructure.llm.gemini_adapter import (
    _SYSTEM_INSTRUCTION,
    _SYSTEM_INSTRUCTION_REESCRITA,
    GeminiAdapter,
)
from tests.unit.infrastructure.pipeline.pdf_fixture import pdf_valido


class _InteractionsFake:
    def __init__(
        self, resposta: Any = None, excecao: Exception | None = None, atraso: float = 0.0
    ) -> None:
        self.resposta = resposta
        self.excecao = excecao
        self.atraso = atraso
        self.chamadas: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.chamadas.append(kwargs)
        if self.atraso:
            await asyncio.sleep(self.atraso)
        if self.excecao is not None:
            raise self.excecao
        return self.resposta


def _cliente_fake(interactions: _InteractionsFake) -> genai.Client:
    aio = SimpleNamespace(interactions=interactions)
    return cast(genai.Client, SimpleNamespace(aio=aio))


def _dimensoes() -> tuple[EstiloProcessamento, Percepcao, Entrada, Compreensao]:
    return EstiloProcessamento.ATIVO, Percepcao.SENSORIAL, Entrada.VISUAL, Compreensao.SEQUENCIAL


async def test_chamada_correta_do_modelo() -> None:
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text="Descrição válida."))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    await adaptador.gerar_descricao_perfil(*_dimensoes())

    assert interactions.chamadas[0]["model"] == "gemini-3.1-flash-lite"


async def test_system_instruction_separada_do_conteudo_do_usuario() -> None:
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text="Descrição válida."))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    await adaptador.gerar_descricao_perfil(*_dimensoes())

    chamada = interactions.chamadas[0]
    assert chamada["system_instruction"] == _SYSTEM_INSTRUCTION
    assert _SYSTEM_INSTRUCTION not in chamada["input"]


async def test_conteudo_das_dimensoes_enviado_corretamente() -> None:
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text="Descrição válida."))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    await adaptador.gerar_descricao_perfil(
        EstiloProcessamento.REFLEXIVO, Percepcao.INTUITIVO, Entrada.VERBAL, Compreensao.GLOBAL
    )

    entrada_enviada = interactions.chamadas[0]["input"]
    assert "Reflexivo" in entrada_enviada
    assert "Intuitivo" in entrada_enviada
    assert "Verbal" in entrada_enviada
    assert "Global" in entrada_enviada


async def test_retorno_de_texto_valido() -> None:
    interactions = _InteractionsFake(
        resposta=SimpleNamespace(output_text="Perfil com forte tendência prática.")
    )
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    resultado = await adaptador.gerar_descricao_perfil(*_dimensoes())

    assert resultado == "Perfil com forte tendência prática."


async def test_resposta_vazia_retorna_none() -> None:
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text=""))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    assert await adaptador.gerar_descricao_perfil(*_dimensoes()) is None


async def test_resposta_sem_texto_algum_retorna_none() -> None:
    interactions = _InteractionsFake(resposta=SimpleNamespace())
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    assert await adaptador.gerar_descricao_perfil(*_dimensoes()) is None


async def test_resposta_excessivamente_grande_retorna_none() -> None:
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text="x" * 3000))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    assert await adaptador.gerar_descricao_perfil(*_dimensoes()) is None


async def test_resposta_que_ecoa_a_system_instruction_retorna_none() -> None:
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text=_SYSTEM_INSTRUCTION))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    assert await adaptador.gerar_descricao_perfil(*_dimensoes()) is None


async def test_excecao_do_sdk_retorna_none_sem_propagar() -> None:
    interactions = _InteractionsFake(excecao=RuntimeError("falha simulada do SDK"))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    assert await adaptador.gerar_descricao_perfil(*_dimensoes()) is None


async def test_timeout_retorna_none() -> None:
    interactions = _InteractionsFake(
        resposta=SimpleNamespace(output_text="tarde demais"), atraso=0.2
    )
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 0.05)

    assert await adaptador.gerar_descricao_perfil(*_dimensoes()) is None


async def test_erro_do_sdk_nao_expoe_api_key_no_log(caplog: pytest.LogCaptureFixture) -> None:
    chave_secreta = "AIzaSy-chave-secreta-de-teste-nao-deve-vazar"
    interactions = _InteractionsFake(excecao=RuntimeError(f"unauthorized: {chave_secreta}"))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    with caplog.at_level("WARNING"):
        await adaptador.gerar_descricao_perfil(*_dimensoes())

    assert chave_secreta not in caplog.text


async def test_reescrita_chamada_correta_do_modelo() -> None:
    interactions = _InteractionsFake(
        resposta=SimpleNamespace(output_text="# Título adaptado\n\nConteúdo reescrito.")
    )
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    await adaptador.reescrever_conteudo(pdf_valido("Conteúdo original."), *_dimensoes())

    assert interactions.chamadas[0]["model"] == "gemini-3.1-flash-lite"


async def test_reescrita_system_instruction_separada_do_conteudo_do_usuario() -> None:
    interactions = _InteractionsFake(
        resposta=SimpleNamespace(output_text="# Título adaptado\n\nConteúdo reescrito.")
    )
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    await adaptador.reescrever_conteudo(pdf_valido("Conteúdo original."), *_dimensoes())

    chamada = interactions.chamadas[0]
    assert chamada["system_instruction"] == _SYSTEM_INSTRUCTION_REESCRITA
    assert _SYSTEM_INSTRUCTION_REESCRITA not in chamada["input"]


async def test_reescrita_fluxo_completo_retorna_pdf_e_resumo() -> None:
    interactions = _InteractionsFake(
        resposta=SimpleNamespace(
            output_text="# Título adaptado\n\nConteúdo reescrito para o estilo do aluno."
        )
    )
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    resultado = await adaptador.reescrever_conteudo(
        pdf_valido("Conteúdo original de teste."), *_dimensoes()
    )

    assert resultado is not None
    assert resultado.conteudo_pdf.startswith(b"%PDF-")
    assert resultado.resumo == "Conteúdo reescrito para o estilo do aluno."


async def test_reescrita_material_invalido_retorna_none() -> None:
    interactions = _InteractionsFake(
        resposta=SimpleNamespace(output_text="não deveria chegar aqui")
    )
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    resultado = await adaptador.reescrever_conteudo(b"nao e um pdf", *_dimensoes())

    assert resultado is None
    assert interactions.chamadas == []


async def test_reescrita_resposta_vazia_retorna_none() -> None:
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text=""))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    resultado = await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert resultado is None


async def test_reescrita_excecao_do_sdk_retorna_none_sem_propagar() -> None:
    interactions = _InteractionsFake(excecao=RuntimeError("falha simulada do SDK"))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    resultado = await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert resultado is None


async def test_reescrita_timeout_retorna_none() -> None:
    interactions = _InteractionsFake(
        resposta=SimpleNamespace(output_text="tarde demais"), atraso=0.2
    )
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 0.05)

    resultado = await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert resultado is None


async def test_reescrita_nao_expoe_api_key_no_log(caplog: pytest.LogCaptureFixture) -> None:
    chave_secreta = "AIzaSy-chave-secreta-de-teste-nao-deve-vazar"
    interactions = _InteractionsFake(excecao=RuntimeError(f"unauthorized: {chave_secreta}"))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    with caplog.at_level("WARNING"):
        await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert chave_secreta not in caplog.text


async def test_reescrita_nao_expoe_conteudo_do_material_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conteudo_sensivel = "informação sigilosa do material didático"
    interactions = _InteractionsFake(excecao=RuntimeError("falha simulada do SDK"))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    with caplog.at_level("WARNING"):
        await adaptador.reescrever_conteudo(pdf_valido(conteudo_sensivel), *_dimensoes())

    assert conteudo_sensivel not in caplog.text


# `_InteractionsFake` acima é bom para a lógica do adaptador, mas não exercita retry real,
# que roda dentro do SDK. Os testes abaixo usam um genai.Client real, só trocando o transporte.


def _cliente_com_retry(
    handler: Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
    tentativas: int = 3,
    atraso_inicial: float = 0.01,
    atraso_maximo: float = 0.05,
    jitter: float = 0.0,
) -> genai.Client:
    # genai.Client constrói também o lado síncrono na inicialização — sem transporte
    # explícito ele tentaria resolver proxy real e falhar; o handler abaixo nunca é chamado.
    def _handler_sincrono_nao_usado(request: httpx.Request) -> httpx.Response:
        raise AssertionError("O lado síncrono do cliente não deveria ser chamado.")

    return genai.Client(
        api_key="chave-de-teste",
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=tentativas,
                initial_delay=atraso_inicial,
                max_delay=atraso_maximo,
                jitter=jitter,
            ),
            httpx_client=httpx.Client(transport=httpx.MockTransport(_handler_sincrono_nao_usado)),
            httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )


def test_timeout_total_padrao_e_igual_ao_timeout_por_tentativa() -> None:
    # Sem timeout_total_segundos explícito (caminho síncrono do Perfil), o orçamento cai
    # para uma tentativa única — nenhuma mudança de comportamento para quem não passar o parâmetro.
    adaptador = GeminiAdapter(cast(genai.Client, SimpleNamespace()), "modelo", 5.0)

    assert adaptador._timeout_total_segundos == 5.0


def test_timeout_total_explicito_e_respeitado() -> None:
    adaptador = GeminiAdapter(cast(genai.Client, SimpleNamespace()), "modelo", 5.0, 45.0)

    assert adaptador._timeout_total_segundos == 45.0


async def test_retry_recupera_apos_falha_transitoria_e_retorna_descricao() -> None:
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        if chamadas["n"] < 3:
            return httpx.Response(503, json={"error": {"message": "temporariamente indisponível"}})
        return httpx.Response(200, json={"id": "abc", "output_text": "Perfil recuperado."})

    adaptador = GeminiAdapter(_cliente_com_retry(handler), "gemini-3.1-flash-lite", 5.0, 10.0)

    resultado = await adaptador.gerar_descricao_perfil(*_dimensoes())

    assert resultado == "Perfil recuperado."
    assert chamadas["n"] >= 3  # 2 falhas + a tentativa que teve sucesso


async def test_retry_reescrita_recupera_apos_falha_transitoria() -> None:
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        if chamadas["n"] < 2:
            return httpx.Response(429, json={"error": {"message": "limite de taxa"}})
        return httpx.Response(
            200,
            json={
                "id": "abc",
                "output_text": "# Título adaptado\n\nConteúdo reescrito após retry.",
            },
        )

    adaptador = GeminiAdapter(_cliente_com_retry(handler), "gemini-3.1-flash-lite", 5.0, 10.0)

    resultado = await adaptador.reescrever_conteudo(pdf_valido("Original."), *_dimensoes())

    assert resultado is not None
    assert resultado.resumo == "Conteúdo reescrito após retry."
    assert chamadas["n"] >= 2


async def test_retry_esgota_tentativas_e_retorna_none_sem_propagar() -> None:
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(503, json={"error": {"message": "sempre indisponível"}})

    adaptador = GeminiAdapter(
        _cliente_com_retry(handler, tentativas=3), "gemini-3.1-flash-lite", 5.0, 10.0
    )

    resultado = await adaptador.gerar_descricao_perfil(*_dimensoes())

    assert resultado is None
    assert chamadas["n"] > 1  # de fato tentou mais de uma vez antes de desistir


async def test_retry_esgotado_nao_expoe_detalhes_da_excecao_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Mensagem de erro simulando algo que a API poderia devolver e que
        # nunca deveria aparecer, verbatim, no log de operação.
        return httpx.Response(503, json={"error": {"message": "detalhe-interno-sensivel"}})

    adaptador = GeminiAdapter(
        _cliente_com_retry(handler, tentativas=2), "gemini-3.1-flash-lite", 5.0, 10.0
    )

    with caplog.at_level("WARNING"):
        resultado = await adaptador.gerar_descricao_perfil(*_dimensoes())

    assert resultado is None
    assert "detalhe-interno-sensivel" not in caplog.text


async def test_orcamento_total_pequeno_ainda_pode_interromper_o_retry() -> None:
    # Um orçamento total pequeno ainda corta o retry pela metade via asyncio.wait_for — o
    # retry não "engana" o timeout externo mesmo com total igual ao de uma tentativa só.
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"id": "abc", "output_text": "tarde demais"})

    adaptador = GeminiAdapter(
        _cliente_com_retry(handler, tentativas=3, atraso_inicial=0.01, atraso_maximo=0.02),
        "gemini-3.1-flash-lite",
        0.05,  # timeout por tentativa
        0.05,  # orçamento total IGUAL ao de uma tentativa única, de propósito
    )

    resultado = await adaptador.gerar_descricao_perfil(*_dimensoes())

    assert resultado is None
