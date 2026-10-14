import asyncio
import logging
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from application.ports.gerador_imagens import (
    ConceitoVisual,
    FalhaGeracaoImagem,
    ImagemGerada,
    MotivoFalhaImagem,
    ResultadoGeracaoImagem,
)
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from infrastructure.imagens.gerador_do_material import GeradorDeImagensDoMaterial
from infrastructure.imagens.prazo_total import PrazoTotal
from infrastructure.llm import gemini_adapter
from infrastructure.llm.gemini_adapter import _INSTRUCAO_COMPLEMENTAR_IMAGENS, GeminiAdapter
from tests.unit.application.ports.imagens_fixture import png_valido
from tests.unit.infrastructure.llm.test_gemini_adapter import _cliente_fake, _InteractionsFake
from tests.unit.infrastructure.pipeline.pdf_fixture import pdf_valido

_DESC1 = "Grafo com três nós ligados por arestas"
_DESC2 = "Árvore binária com raiz e dois filhos"
_M1 = f"[[IMAGEM:g1|{_DESC1}]]"
_M2 = f"[[IMAGEM:g2|{_DESC2}]]"
_RESPOSTA_1 = f"# Título adaptado\n\nPrimeiro parágrafo.\n\n{_M1}\n\nSegundo parágrafo."
_RESPOSTA_2 = f"# Título adaptado\n\nPrimeiro parágrafo.\n\n{_M1}\n\nMeio.\n\n{_M2}\n\nFim."
_SEM_MARCADOR = "# Título adaptado\n\nPrimeiro parágrafo.\n\nSegundo parágrafo."


def _dimensoes() -> tuple[EstiloProcessamento, Percepcao, Entrada, Compreensao]:
    return EstiloProcessamento.ATIVO, Percepcao.SENSORIAL, Entrada.VISUAL, Compreensao.SEQUENCIAL


def _imagem() -> ImagemGerada:
    return ImagemGerada(png_valido(), "texto alternativo")


class _GeradorFalso:
    """Gerador de imagens simulado (nenhuma chamada real à OpenAI)."""

    def __init__(self, *comportamentos: Any) -> None:
        self._comportamentos = list(comportamentos)
        self.conceitos: list[ConceitoVisual] = []
        self.iniciou = asyncio.Event()

    async def gerar(self, conceito: ConceitoVisual) -> ResultadoGeracaoImagem:
        self.conceitos.append(conceito)
        self.iniciou.set()
        comportamento = self._comportamentos.pop(0) if self._comportamentos else _imagem()
        if comportamento == "travar":
            await asyncio.Event().wait()
        if isinstance(comportamento, BaseException):
            raise comportamento
        return comportamento


def _adaptador(
    texto: str | None, gerador: _GeradorFalso | None, **opcoes: Any
) -> tuple[GeminiAdapter, _InteractionsFake]:
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text=texto))
    adaptador = GeminiAdapter(
        _cliente_fake(interactions),
        "gemini-3.1-flash-lite",
        5.0,
        gerador_de_imagens=gerador,
        **opcoes,
    )
    return adaptador, interactions


async def _rodar(adaptador: GeminiAdapter, original: str = "Origem.") -> Any:
    return await adaptador.reescrever_conteudo(pdf_valido(original), *_dimensoes())


@pytest.fixture
def markdown_enviado_ao_pdf(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recebidos: list[str] = []

    def falso(markdown: str, imagens: Sequence[Any] = (), **_: Any) -> bytes:
        recebidos.append(markdown)
        return b"%PDF-falso"

    monkeypatch.setattr(gemini_adapter, "gerar_pdf", falso)
    return recebidos


@pytest.fixture
def instancias(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    # Registra cada PrazoTotal e cada orquestrador criado, sem alterar o comportamento.
    registro = SimpleNamespace(prazos=[], orquestradores=[])

    class PrazoEspiao(PrazoTotal):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            registro.prazos.append(self)

    class OrquestradorEspiao(GeradorDeImagensDoMaterial):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            registro.orquestradores.append((self, kwargs))

    monkeypatch.setattr(gemini_adapter, "PrazoTotal", PrazoEspiao)
    monkeypatch.setattr(gemini_adapter, "GeradorDeImagensDoMaterial", OrquestradorEspiao)
    return registro


@pytest.fixture
def pontos_de_integracao(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    # Observa o que chega ao ponto de integração pendente (texto, conceitos e resultados).
    chamadas: list[Any] = []
    original = GeminiAdapter._incorporar_imagens

    def espiao(self: GeminiAdapter, conteudo: str, conceitos: Any, resultados: Any) -> str:
        chamadas.append((conteudo, conceitos, resultados))
        return original(self, conteudo, conceitos, resultados)

    monkeypatch.setattr(GeminiAdapter, "_incorporar_imagens", espiao)
    return chamadas


# --- recurso desligado -------------------------------------------------------------------------


async def test_desligado_nao_chama_o_gerador_nem_cria_prazo_ou_orquestrador(
    instancias: SimpleNamespace,
) -> None:
    gerador = _GeradorFalso()
    adaptador, interactions = _adaptador(_RESPOSTA_1, gerador)  # flag padrão: desligada

    resultado = await _rodar(adaptador)

    assert resultado is not None
    assert gerador.conceitos == []
    assert instancias.prazos == [] and instancias.orquestradores == []


async def test_desligado_a_saida_textual_e_a_instrucao_sao_as_de_antes(
    markdown_enviado_ao_pdf: list[str],
) -> None:
    gerador = _GeradorFalso()
    adaptador, interactions = _adaptador(_SEM_MARCADOR, gerador)
    sem_gerador, interactions_b = _adaptador(_SEM_MARCADOR, None)

    r1 = await _rodar(adaptador)
    r2 = await _rodar(sem_gerador)

    assert (r1.conteudo_pdf, r1.resumo) == (r2.conteudo_pdf, r2.resumo)
    assert markdown_enviado_ao_pdf == [_SEM_MARCADOR, _SEM_MARCADOR]
    instrucao = interactions.chamadas[0]["system_instruction"]
    assert instrucao == interactions_b.chamadas[0]["system_instruction"]
    assert _INSTRUCAO_COMPLEMENTAR_IMAGENS.split(" Regras:")[0] not in instrucao
    assert gerador.conceitos == []


async def test_desligado_com_marcador_literal_o_fluxo_nao_toca_no_texto(
    markdown_enviado_ao_pdf: list[str], instancias: SimpleNamespace
) -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(_RESPOSTA_1, gerador)
    await _rodar(adaptador)

    assert markdown_enviado_ao_pdf == [_RESPOSTA_1]  # comportamento anterior, sem tratamento
    assert gerador.conceitos == [] and instancias.orquestradores == []


# --- recurso ligado ----------------------------------------------------------------------------


async def test_ligado_conceitos_validos_chegam_ao_orquestrador_e_ao_gerador(
    instancias: SimpleNamespace, pontos_de_integracao: list[Any]
) -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(
        _RESPOSTA_2, gerador, imagens_geradas_habilitadas=True, imagens_max_por_material=2
    )

    resultado = await _rodar(adaptador)

    assert resultado is not None
    assert [(c.identificador, c.descricao, c.ancora) for c in gerador.conceitos] == [
        ("g1", _DESC1, "g1"),
        ("g2", _DESC2, "g2"),
    ]
    _, conceitos, resultados = pontos_de_integracao[0]
    assert [c.identificador for c in conceitos] == ["g1", "g2"]
    assert len(resultados) == 2 and all(isinstance(r, ImagemGerada) for r in resultados)


async def test_ligado_o_orquestrador_recebe_gerador_e_limites_configurados(
    instancias: SimpleNamespace,
) -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(
        _RESPOSTA_1,
        gerador,
        imagens_geradas_habilitadas=True,
        imagens_max_por_material=3,
        imagens_orcamento_total_segundos=90.0,
        imagens_timeout_total_segundos=45.0,
        imagens_limite_individual_segundos=20.0,
    )
    await _rodar(adaptador)

    assert len(instancias.orquestradores) == 1
    orquestrador, kwargs = instancias.orquestradores[0]
    assert kwargs["gerador"] is gerador
    assert kwargs["prazo"] is instancias.prazos[0]
    assert kwargs["maximo"] == 3
    assert kwargs["timeout_por_imagem_segundos"] == 45.0
    assert kwargs["limite_individual_segundos"] == 20.0
    assert instancias.prazos[0].total == 90.0


async def test_ligado_o_limite_maximo_vale_antes_de_qualquer_chamada() -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(_RESPOSTA_2, gerador, imagens_geradas_habilitadas=True)  # máximo 1

    await _rodar(adaptador)

    assert [c.identificador for c in gerador.conceitos] == ["g1"]


async def test_ligado_marcadores_invalidos_nao_geram_chamada(instancias: SimpleNamespace) -> None:
    gerador = _GeradorFalso()
    resposta = "# T\n\nCorpo.\n\n[[IMAGEM:x1|curta]]\n\n[[IMAGEM:x2|<script>alert(1)</script>]]\n"
    adaptador, _ = _adaptador(resposta, gerador, imagens_geradas_habilitadas=True)

    resultado = await _rodar(adaptador)

    assert resultado is not None
    assert gerador.conceitos == []
    assert instancias.prazos == [] and instancias.orquestradores == []


async def test_ligado_sem_marcadores_nao_cria_prazo_nem_orquestrador(
    instancias: SimpleNamespace,
) -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(_SEM_MARCADOR, gerador, imagens_geradas_habilitadas=True)
    await _rodar(adaptador)
    assert gerador.conceitos == [] and instancias.prazos == []


async def test_ligado_com_maximo_zero_nao_gera_nada(instancias: SimpleNamespace) -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(
        _RESPOSTA_1, gerador, imagens_geradas_habilitadas=True, imagens_max_por_material=0
    )
    resultado = await _rodar(adaptador)
    assert resultado is not None
    assert gerador.conceitos == [] and instancias.prazos == []


async def test_ligado_sem_gerador_injetado_segue_so_com_texto(
    instancias: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    adaptador, _ = _adaptador(_RESPOSTA_1, None, imagens_geradas_habilitadas=True)
    with caplog.at_level(logging.WARNING):
        resultado = await _rodar(adaptador)

    assert resultado is not None
    assert instancias.prazos == [] and instancias.orquestradores == []
    assert "sem gerador configurado" in caplog.text


# --- prazo e orquestrador por material ---------------------------------------------------------


async def test_prazo_e_orquestrador_sao_novos_a_cada_material(
    instancias: SimpleNamespace,
) -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(_RESPOSTA_1, gerador, imagens_geradas_habilitadas=True)

    await _rodar(adaptador, "Material um.")
    await _rodar(adaptador, "Material dois.")

    assert len(instancias.prazos) == 2 and len(instancias.orquestradores) == 2
    assert instancias.prazos[0] is not instancias.prazos[1]
    assert instancias.orquestradores[0][0] is not instancias.orquestradores[1][0]
    assert instancias.orquestradores[0][1]["prazo"] is instancias.prazos[0]
    assert instancias.orquestradores[1][1]["prazo"] is instancias.prazos[1]
    assert len(gerador.conceitos) == 2  # uma imagem por material, cada um com o seu prazo


async def test_materiais_concorrentes_nao_compartilham_prazo(
    instancias: SimpleNamespace,
) -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(_RESPOSTA_1, gerador, imagens_geradas_habilitadas=True)

    await asyncio.gather(_rodar(adaptador, "A."), _rodar(adaptador, "B."), _rodar(adaptador, "C."))

    assert len({id(p) for p in instancias.prazos}) == 3
    assert len({id(o) for o, _ in instancias.orquestradores}) == 3


async def test_o_prazo_comeca_depois_do_gemini_e_nao_atravessa_materiais(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Cada prazo é criado no início da fase de imagens (depois da resposta do Gemini).
    ordem: list[str] = []
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text=_RESPOSTA_1))
    original_create = interactions.create

    async def create(**kwargs: Any) -> Any:
        ordem.append("gemini")
        return await original_create(**kwargs)

    interactions.create = create  # type: ignore[method-assign]

    class PrazoEspiao(PrazoTotal):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            ordem.append("prazo")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(gemini_adapter, "PrazoTotal", PrazoEspiao)
    adaptador = GeminiAdapter(
        _cliente_fake(interactions),
        "gemini-3.1-flash-lite",
        5.0,
        imagens_geradas_habilitadas=True,
        gerador_de_imagens=_GeradorFalso(),
    )
    await _rodar(adaptador)

    assert ordem == ["gemini", "prazo"]


async def test_orcamento_esgotado_preserva_o_texto_e_nao_chama_o_gerador(
    monkeypatch: pytest.MonkeyPatch, markdown_enviado_ao_pdf: list[str]
) -> None:
    leituras = iter([0.0, 10_000.0, 10_000.0, 10_000.0])
    monkeypatch.setattr(
        gemini_adapter, "PrazoTotal", lambda segundos: PrazoTotal(segundos, lambda: next(leituras))
    )
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(_RESPOSTA_1, gerador, imagens_geradas_habilitadas=True)

    resultado = await _rodar(adaptador)

    assert resultado is not None
    assert gerador.conceitos == []
    assert "Primeiro parágrafo." in markdown_enviado_ao_pdf[0]


# --- falhas de imagem --------------------------------------------------------------------------


async def test_falha_de_imagem_nao_elimina_o_texto_adaptado(
    markdown_enviado_ao_pdf: list[str], pontos_de_integracao: list[Any]
) -> None:
    falha = FalhaGeracaoImagem("g1", MotivoFalhaImagem.INDISPONIVEL)
    adaptador, _ = _adaptador(_RESPOSTA_1, _GeradorFalso(falha), imagens_geradas_habilitadas=True)

    resultado = await _rodar(adaptador)

    assert resultado is not None
    assert resultado.resumo == "Primeiro parágrafo."
    paragrafos = [p for p in markdown_enviado_ao_pdf[0].split("\n") if p.strip()]
    assert paragrafos == ["# Título adaptado", "Primeiro parágrafo.", "Segundo parágrafo."]
    assert pontos_de_integracao[0][2] == (falha,)


async def test_imagens_geradas_sao_preservadas_ao_lado_de_uma_falha(
    pontos_de_integracao: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    imagem = _imagem()
    falha = FalhaGeracaoImagem("g2", MotivoFalhaImagem.TIMEOUT)
    adaptador, _ = _adaptador(
        _RESPOSTA_2,
        _GeradorFalso(imagem, falha),
        imagens_geradas_habilitadas=True,
        imagens_max_por_material=2,
    )
    with caplog.at_level(logging.INFO):
        resultado = await _rodar(adaptador)

    assert resultado is not None
    assert pontos_de_integracao[0][2] == (imagem, falha)
    # Não descartadas em silêncio: a pendência de incorporação é registrada (só contagem).
    assert "1 imagem(ns) gerada(s) sem incorporação" in caplog.text


async def test_logs_nao_trazem_descricao_nem_texto_alternativo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adaptador, _ = _adaptador(_RESPOSTA_1, _GeradorFalso(), imagens_geradas_habilitadas=True)
    with caplog.at_level(logging.DEBUG):
        await _rodar(adaptador)
    assert _DESC1 not in caplog.text
    assert "texto alternativo" not in caplog.text


# --- cancelamento e erros de programação -------------------------------------------------------


async def test_cancelamento_externo_continua_propagando() -> None:
    gerador = _GeradorFalso("travar")
    adaptador, _ = _adaptador(_RESPOSTA_1, gerador, imagens_geradas_habilitadas=True)

    tarefa = asyncio.create_task(_rodar(adaptador))
    await asyncio.wait_for(gerador.iniciou.wait(), timeout=5)
    tarefa.cancel()

    with pytest.raises(asyncio.CancelledError):
        await tarefa


async def test_erro_de_programacao_na_geracao_nao_e_escondido(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Não vira "imagem que falhou": segue o tratamento já existente de falha inesperada do
    # método (registro com o nome da classe e retorno None), sem o texto da exceção.
    gerador = _GeradorFalso(RuntimeError(f"defeito com {_DESC1}"))
    adaptador, _ = _adaptador(_RESPOSTA_1, gerador, imagens_geradas_habilitadas=True)

    with caplog.at_level(logging.WARNING):
        resultado = await _rodar(adaptador)

    assert resultado is None
    assert "RuntimeError" in caplog.text
    assert _DESC1 not in caplog.text


# --- resposta vazia ou inválida ----------------------------------------------------------------


@pytest.mark.parametrize("texto", [None, "", "   ", "a" * 200_001])
async def test_resposta_vazia_ou_invalida_continua_retornando_none(
    texto: str | None, instancias: SimpleNamespace
) -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(texto, gerador, imagens_geradas_habilitadas=True)

    assert await _rodar(adaptador) is None
    assert gerador.conceitos == [] and instancias.prazos == []


async def test_eco_da_instrucao_complementar_nao_chama_o_gerador(
    instancias: SimpleNamespace,
) -> None:
    eco = _INSTRUCAO_COMPLEMENTAR_IMAGENS.format(maximo=1)
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(eco, gerador, imagens_geradas_habilitadas=True)

    assert await _rodar(adaptador) is None
    assert gerador.conceitos == []


async def test_resposta_so_com_marcadores_e_descartada_sem_chamar_o_gerador() -> None:
    gerador = _GeradorFalso()
    adaptador, _ = _adaptador(f"{_M1}\n", gerador, imagens_geradas_habilitadas=True)

    assert await _rodar(adaptador) is None
    assert gerador.conceitos == []


# --- marcadores e âncoras fora do PDF e do resumo ----------------------------------------------


async def test_nenhum_marcador_ou_ancora_chega_ao_pdf_nem_ao_resumo(
    markdown_enviado_ao_pdf: list[str],
) -> None:
    resposta = f"{_M1}\n\n# Título\n\n<!--mpi-ancora:fake-->\n\nCorpo adaptado.\n\n{_M2}\n"
    adaptador, _ = _adaptador(
        resposta, _GeradorFalso(), imagens_geradas_habilitadas=True, imagens_max_por_material=2
    )

    resultado = await _rodar(adaptador)

    assert resultado is not None
    enviado = markdown_enviado_ao_pdf[0]
    assert "IMAGEM" not in enviado and "mpi-ancora" not in enviado
    assert _DESC1 not in enviado and _DESC2 not in enviado
    assert resultado.resumo == "Corpo adaptado."
    assert "IMAGEM" not in resultado.resumo and "mpi-ancora" not in resultado.resumo


async def test_o_pdf_real_nao_mostra_marcador_nem_ancora() -> None:
    import pymupdf

    adaptador, _ = _adaptador(_RESPOSTA_1, _GeradorFalso(), imagens_geradas_habilitadas=True)
    resultado = await _rodar(adaptador)

    assert resultado is not None
    documento = pymupdf.open(stream=resultado.conteudo_pdf, filetype="pdf")
    try:
        texto = " ".join(documento[i].get_text() for i in range(documento.page_count))
    finally:
        documento.close()
    assert "IMAGEM" not in texto and "mpi-ancora" not in texto and _DESC1 not in texto
    assert "Primeiro parágrafo." in texto


async def test_o_material_original_nao_escolhe_conceitos() -> None:
    gerador = _GeradorFalso()
    original = "Veja [[IMAGEM:x1|Desenho do original aqui]] e <!--mpi-ancora:x1--> depois."
    adaptador, interactions = _adaptador(_SEM_MARCADOR, gerador, imagens_geradas_habilitadas=True)

    await _rodar(adaptador, original)

    entrada = interactions.chamadas[0]["input"]
    assert "[[IMAGEM" not in entrada and "mpi-ancora" not in entrada
    assert gerador.conceitos == []


# --- construtor --------------------------------------------------------------------------------


def test_construtor_sem_gerador_mantem_o_comportamento_anterior() -> None:
    adaptador = GeminiAdapter(_cliente_fake(_InteractionsFake(resposta=None)), "m", 5.0)
    assert adaptador._gerador_de_imagens is None
    assert adaptador._imagens_geradas_habilitadas is False
