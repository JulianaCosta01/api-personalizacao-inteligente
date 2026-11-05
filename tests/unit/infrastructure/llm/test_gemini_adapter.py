import asyncio
from collections.abc import Callable, Coroutine
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from google import genai
from google.genai import types

from application.ports.llm import CategoriaFalhaTransitoria, FalhaTransitoriaDoProvedorError
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


@pytest.fixture
def pipeline_local_substituido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Troca extração e montagem do PDF por funções instantâneas.

    Aqui o foco é o que vai para o modelo; o pipeline real tem testes próprios.
    """
    monkeypatch.setattr(
        "infrastructure.llm.gemini_adapter.extrair_markdown",
        lambda _conteudo: "# Documento\n\nConteúdo original.",
    )
    monkeypatch.setattr("infrastructure.llm.gemini_adapter.extrair_imagens", lambda _c: [])
    monkeypatch.setattr(
        "infrastructure.llm.gemini_adapter.gerar_pdf", lambda _md, _imagens: b"%PDF-falso"
    )


@pytest.mark.usefixtures("pipeline_local_substituido")
async def test_reescrita_chamada_correta_do_modelo() -> None:
    interactions = _InteractionsFake(
        resposta=SimpleNamespace(output_text="# Título adaptado\n\nConteúdo reescrito.")
    )
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0)

    await adaptador.reescrever_conteudo(pdf_valido("Conteúdo original."), *_dimensoes())

    assert interactions.chamadas[0]["model"] == "gemini-3.1-flash-lite"


@pytest.mark.usefixtures("pipeline_local_substituido")
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


async def test_reescrita_timeout_da_chamada_ao_modelo_e_falha_transitoria() -> None:
    # Antes devolvia None (indistinguível de qualquer outra falha); agora o estouro do orçamento
    # da chamada ao modelo é sinalizado, para o caso de uso poder repetir o job.
    interactions = _InteractionsFake(
        resposta=SimpleNamespace(output_text="tarde demais"), atraso=0.5
    )
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0, 0.05)

    with pytest.raises(FalhaTransitoriaDoProvedorError) as info:
        await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert info.value.categoria == CategoriaFalhaTransitoria.TIMEOUT_TOTAL
    assert info.value.status_http is None


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


async def test_falha_permanente_registra_tipo_e_pilha_sem_a_mensagem(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A causa precisa ser localizável (tipo + arquivo/linha/função), mas a mensagem da exceção
    # pode conter corpo de requisição/resposta ou texto do material e não vai para o log.
    interactions = _InteractionsFake(excecao=ValueError("texto-do-material-na-mensagem"))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0, 10.0)

    with caplog.at_level("WARNING"):
        resultado = await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert resultado is None
    assert "ValueError" in caplog.text
    assert "gemini_adapter.py" in caplog.text
    assert "_chamar_modelo_para_reescrita" in caplog.text
    assert "texto-do-material-na-mensagem" not in caplog.text


def test_pilha_sem_mensagem_nunca_levanta() -> None:
    from infrastructure.llm.gemini_adapter import _pilha_sem_mensagem

    assert _pilha_sem_mensagem(None) == ""
    assert "indisponível" in _pilha_sem_mensagem(object())  # type: ignore[arg-type]


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
    # genai.Client constrói também o lado síncrono na inicialização, sem transporte
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
    # para uma tentativa única, nenhuma mudança de comportamento para quem não passar o parâmetro.
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
    # Um orçamento total pequeno ainda corta o retry pela metade via asyncio.wait_for: o
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


# Classificação de falhas transitórias do provedor (só a chamada ao modelo)


class _ErroHttpFake(Exception):
    # As exceções do SDK expõem o código HTTP em `status_code`; o adaptador usa duck typing.
    def __init__(self, status_code: int, mensagem: str = "detalhe-interno-sensivel") -> None:
        super().__init__(mensagem)
        self.status_code = status_code


def _adaptador_com_excecao(excecao: Exception) -> GeminiAdapter:
    interactions = _InteractionsFake(excecao=excecao)
    return GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0, 10.0)


@pytest.mark.parametrize(
    ("status", "categoria"),
    [
        (503, CategoriaFalhaTransitoria.HTTP_5XX),
        (500, CategoriaFalhaTransitoria.HTTP_5XX),
        (504, CategoriaFalhaTransitoria.HTTP_5XX),
        (429, CategoriaFalhaTransitoria.HTTP_429),
        (408, CategoriaFalhaTransitoria.HTTP_408),
    ],
)
async def test_reescrita_status_transitorio_levanta_falha_transitoria(
    status: int, categoria: CategoriaFalhaTransitoria
) -> None:
    adaptador = _adaptador_com_excecao(_ErroHttpFake(status))

    with pytest.raises(FalhaTransitoriaDoProvedorError) as info:
        await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert info.value.categoria == categoria
    assert info.value.status_http == status


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
async def test_reescrita_status_permanente_retorna_none(status: int) -> None:
    # Credencial inválida, modelo inexistente ou requisição malformada não melhoram repetindo.
    adaptador = _adaptador_com_excecao(_ErroHttpFake(status))

    assert await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes()) is None


@pytest.mark.parametrize(
    "excecao",
    [
        httpx.ReadTimeout("lento"),
        httpx.ConnectTimeout("sem conexão"),
        httpx.ConnectError("recusada"),
        httpx.RemoteProtocolError("conexão encerrada"),
    ],
)
async def test_reescrita_falha_de_rede_e_transitoria(excecao: Exception) -> None:
    adaptador = _adaptador_com_excecao(excecao)

    with pytest.raises(FalhaTransitoriaDoProvedorError) as info:
        await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert info.value.categoria == CategoriaFalhaTransitoria.REDE
    assert info.value.status_http is None


class APIConnectionError(Exception):
    """Réplica, pelo NOME, da falha de conexão do SDK google-genai (fora do httpx, sem status)."""


class APITimeoutError(APIConnectionError):
    """Réplica, pelo NOME, do timeout do cliente do SDK google-genai."""


class _SubclasseDeAPITimeoutError(APITimeoutError):
    pass


@pytest.mark.parametrize(
    "excecao",
    [APITimeoutError("timeout"), APIConnectionError("conexão"), _SubclasseDeAPITimeoutError("x")],
)
async def test_reescrita_falha_de_conexao_do_sdk_e_transitoria(excecao: Exception) -> None:
    adaptador = _adaptador_com_excecao(excecao)

    with pytest.raises(FalhaTransitoriaDoProvedorError) as info:
        await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert info.value.categoria == CategoriaFalhaTransitoria.REDE
    assert info.value.status_http is None
    assert info.value.__cause__ is None  # `from None`: nada do erro original é carregado


async def test_reescrita_timeout_do_cliente_no_sdk_real_levanta_falha_transitoria() -> None:
    # Cliente real do SDK: o httpx estoura o tempo e o SDK levanta o APITimeoutError que antes
    # terminava o job em erro sem nenhuma repetição.
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        raise httpx.ReadTimeout("lento", request=request)

    adaptador = GeminiAdapter(
        _cliente_com_retry(handler, tentativas=2), "gemini-3.1-flash-lite", 5.0, 10.0
    )

    with pytest.raises(FalhaTransitoriaDoProvedorError) as info:
        await adaptador.reescrever_conteudo(pdf_valido("Original."), *_dimensoes())

    assert info.value.categoria == CategoriaFalhaTransitoria.REDE
    # Medido com o SDK 2.18.1: um timeout do cliente NÃO é repetido pelo SDK (1 chamada), ao
    # contrário de 503/429. A repetição fica a cargo do job; este teste não fixa essa contagem.
    assert chamadas["n"] >= 1


@pytest.mark.parametrize("excecao", [ValueError("x"), TimeoutError, KeyError("k")])
async def test_reescrita_excecao_comum_nao_vira_falha_de_conexao(excecao: object) -> None:
    # Só o nome da classe (na cadeia de herança) conta: uma exceção qualquer segue como antes.
    instancia = excecao if isinstance(excecao, Exception) else excecao()  # type: ignore[operator]
    adaptador = _adaptador_com_excecao(instancia)
    try:
        resultado = await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())
    except FalhaTransitoriaDoProvedorError as falha:
        assert falha.categoria == CategoriaFalhaTransitoria.TIMEOUT_TOTAL  # TimeoutError embutido
    else:
        assert resultado is None


async def test_reescrita_configuracao_de_transporte_invalida_nao_e_transitoria() -> None:
    adaptador = _adaptador_com_excecao(httpx.UnsupportedProtocol("esquema inválido"))

    assert await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes()) is None


async def test_reescrita_erro_desconhecido_continua_retornando_none() -> None:
    adaptador = _adaptador_com_excecao(RuntimeError("falha simulada do SDK"))

    assert await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes()) is None


async def test_reescrita_503_persistente_no_sdk_real_levanta_falha_transitoria() -> None:
    # Cliente real do SDK, só com o transporte trocado: depois de esgotar as repetições internas,
    # o erro do SDK (com `status_code`) é classificado como transitório.
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(503, json={"error": {"message": "sempre indisponível"}})

    adaptador = GeminiAdapter(
        _cliente_com_retry(handler, tentativas=2), "gemini-3.1-flash-lite", 5.0, 10.0
    )

    with pytest.raises(FalhaTransitoriaDoProvedorError) as info:
        await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert info.value.categoria == CategoriaFalhaTransitoria.HTTP_5XX
    assert info.value.status_http == 503
    assert chamadas["n"] > 1  # o SDK de fato repetiu antes de desistir


async def test_reescrita_429_persistente_no_sdk_real_levanta_falha_transitoria() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "limite de taxa"}})

    adaptador = GeminiAdapter(
        _cliente_com_retry(handler, tentativas=2), "gemini-3.1-flash-lite", 5.0, 10.0
    )

    with pytest.raises(FalhaTransitoriaDoProvedorError) as info:
        await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert info.value.categoria == CategoriaFalhaTransitoria.HTTP_429


async def test_reescrita_401_no_sdk_real_retorna_none_sem_repetir() -> None:
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(401, json={"error": {"message": "chave inválida"}})

    adaptador = GeminiAdapter(
        _cliente_com_retry(handler, tentativas=3), "gemini-3.1-flash-lite", 5.0, 10.0
    )

    assert await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes()) is None
    assert chamadas["n"] == 1  # erro de credencial não é repetido nem pelo SDK


async def test_reescrita_falha_transitoria_nao_expoe_detalhes_no_log_nem_na_excecao(
    caplog: pytest.LogCaptureFixture,
) -> None:
    segredo = "AIzaSy-segredo-de-teste"
    adaptador = _adaptador_com_excecao(_ErroHttpFake(503, f"unavailable: {segredo}"))

    with caplog.at_level("WARNING"), pytest.raises(FalhaTransitoriaDoProvedorError) as info:
        await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

    assert segredo not in caplog.text
    assert segredo not in str(info.value)
    assert info.value.__cause__ is None  # a exceção original (com a requisição) é descartada
    assert "http_5xx" in caplog.text


async def test_reescrita_timeout_da_extracao_continua_retornando_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Extração/montagem do PDF não são falhas do provedor: o TimeoutError delas segue sendo None.
    import time

    def extracao_lenta(conteudo: bytes) -> str:
        time.sleep(0.3)
        return "texto"

    monkeypatch.setattr("infrastructure.llm.gemini_adapter.extrair_markdown", extracao_lenta)
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text="não chega aqui"))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 0.05, 10.0)

    assert await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes()) is None
    assert interactions.chamadas == []  # o modelo nem chegou a ser chamado


async def test_descricao_do_perfil_continua_devolvendo_none_em_falha_transitoria() -> None:
    # Contrato do fluxo síncrono do Perfil preservado: nunca propaga a exceção nova.
    adaptador = _adaptador_com_excecao(_ErroHttpFake(503))

    assert await adaptador.gerar_descricao_perfil(*_dimensoes()) is None
