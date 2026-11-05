"""Limites das etapas locais do pipeline (extração e PDF) no GeminiAdapter.

O timeout do Gemini não governa essas etapas, e estourá-las não repete a chamada paga.
"""

import time
from types import SimpleNamespace
from typing import Any

import pytest

from infrastructure.llm import gemini_adapter
from infrastructure.llm.gemini_adapter import GeminiAdapter
from tests.unit.infrastructure.llm.test_gemini_adapter import (
    _cliente_fake,
    _dimensoes,
    _InteractionsFake,
)
from tests.unit.infrastructure.llm.test_gemini_geracao_imagens import (
    _RESPOSTA_1,
    _adaptador,
    _GeradorFalso,
)
from tests.unit.infrastructure.pipeline.pdf_fixture import pdf_valido

_RESPOSTA = SimpleNamespace(output_text="# Título adaptado\n\nConteúdo reescrito.")
_CURTO = 0.05  # estoura de forma previsível: as etapas simuladas dormem 0,3 s
_LONGO = 5.0  # folga ampla: as etapas simuladas dormem 0,2 s


def _dormindo(segundos: float, resultado: Any) -> Any:
    def etapa(*_args: Any, **_kwargs: Any) -> Any:
        time.sleep(segundos)
        return resultado

    return etapa


@pytest.fixture
def etapas_rapidas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini_adapter, "extrair_markdown", _dormindo(0, "# T\n\nOriginal."))
    monkeypatch.setattr(gemini_adapter, "extrair_imagens", _dormindo(0, []))
    monkeypatch.setattr(gemini_adapter, "gerar_pdf", _dormindo(0, b"%PDF-falso"))


def _adaptador_do_modelo(**opcoes: Any) -> tuple[GeminiAdapter, _InteractionsFake]:
    interactions = _InteractionsFake(resposta=_RESPOSTA)
    adaptador = GeminiAdapter(
        _cliente_fake(interactions),
        "gemini-3.1-flash-lite",
        opcoes.pop("gemini", 5.0),
        10.0,
        **opcoes,
    )
    return adaptador, interactions


async def _rodar(adaptador: GeminiAdapter) -> Any:
    return await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())


# Compatibilidade


def test_sem_limites_dedicados_as_etapas_locais_herdam_o_timeout_anterior() -> None:
    adaptador, _ = _adaptador_do_modelo(gemini=7.0)
    assert adaptador._timeout_extracao_segundos == 7.0
    assert adaptador._timeout_pdf_segundos == 7.0


def test_limites_dedicados_nao_alteram_o_timeout_da_chamada_ao_gemini() -> None:
    adaptador, _ = _adaptador_do_modelo(timeout_extracao_segundos=30.0, timeout_pdf_segundos=60.0)
    assert adaptador._timeout_segundos == 5.0
    assert adaptador._timeout_total_segundos == 10.0
    assert (adaptador._timeout_extracao_segundos, adaptador._timeout_pdf_segundos) == (30.0, 60.0)


# Extração


@pytest.mark.usefixtures("etapas_rapidas")
async def test_extracao_nao_e_limitada_pelo_timeout_do_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gemini_adapter, "extrair_markdown", _dormindo(0.2, "# T\n\nOriginal."))
    # Timeout do Gemini menor que o tempo da extração: antes, isto abortava a extração.
    adaptador, interactions = _adaptador_do_modelo(gemini=_CURTO, timeout_extracao_segundos=_LONGO)

    resultado = await _rodar(adaptador)

    assert resultado is not None
    assert len(interactions.chamadas) == 1


@pytest.mark.usefixtures("etapas_rapidas")
async def test_extracao_alem_do_limite_proprio_encerra_sem_chamar_o_modelo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gemini_adapter, "extrair_markdown", _dormindo(0.3, "# T\n\nOriginal."))
    adaptador, interactions = _adaptador_do_modelo(gemini=_LONGO, timeout_extracao_segundos=_CURTO)

    assert await _rodar(adaptador) is None
    assert interactions.chamadas == []


@pytest.mark.usefixtures("etapas_rapidas")
async def test_timeout_da_extracao_e_registrado_com_etapa_e_limite(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(gemini_adapter, "extrair_markdown", _dormindo(0.3, "# T\n\nOriginal."))
    adaptador, interactions = _adaptador_do_modelo(gemini=_LONGO, timeout_extracao_segundos=_CURTO)

    with caplog.at_level("WARNING", logger=gemini_adapter.logger.name):
        assert await _rodar(adaptador) is None

    registro = "\n".join(r.getMessage() for r in caplog.records)
    assert "etapa local 'extração do Markdown'" in registro
    assert "limite de 0 s" in registro  # 0,05 s arredondado por %.0f
    assert "não chegou a ser chamado" in registro
    assert interactions.chamadas == []


@pytest.mark.usefixtures("etapas_rapidas")
async def test_timeout_da_montagem_do_pdf_e_registrado_com_a_etapa_certa(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(gemini_adapter, "gerar_pdf", _dormindo(0.3, b"%PDF-falso"))
    adaptador, _ = _adaptador_do_modelo(
        timeout_extracao_segundos=_LONGO, timeout_pdf_segundos=_CURTO
    )

    with caplog.at_level("WARNING", logger=gemini_adapter.logger.name):
        assert await _rodar(adaptador) is None

    registro = "\n".join(r.getMessage() for r in caplog.records)
    assert "etapa local 'montagem do PDF'" in registro
    assert "extração do Markdown'" not in registro


@pytest.mark.usefixtures("etapas_rapidas")
async def test_extracao_de_imagens_lenta_nao_derruba_o_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gemini_adapter, "extrair_imagens", _dormindo(0.3, []))
    adaptador, interactions = _adaptador_do_modelo(
        timeout_extracao_segundos=_CURTO, anexar_imagens_originais=True
    )

    resultado = await _rodar(adaptador)

    assert resultado is not None  # sai sem as imagens originais, como já era o comportamento
    assert len(interactions.chamadas) == 1


# Montagem do PDF


@pytest.mark.usefixtures("etapas_rapidas")
async def test_pdf_nao_e_limitado_pelo_timeout_do_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gemini_adapter, "gerar_pdf", _dormindo(0.2, b"%PDF-falso"))
    adaptador, _ = _adaptador_do_modelo(gemini=_CURTO, timeout_pdf_segundos=_LONGO)

    resultado = await _rodar(adaptador)

    assert resultado is not None
    assert resultado.conteudo_pdf == b"%PDF-falso"


@pytest.mark.usefixtures("etapas_rapidas")
async def test_pdf_alem_do_limite_proprio_nao_repete_o_modelo_nem_vira_falha_transitoria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gemini_adapter, "gerar_pdf", _dormindo(0.3, b"%PDF-falso"))
    adaptador, interactions = _adaptador_do_modelo(timeout_pdf_segundos=_CURTO)

    # Devolve None (e não FalhaTransitoriaDoProvedorError): o caso de uso encerra em erro em vez
    # de devolver o job à fila, o que repetiria a chamada paga ao modelo.
    assert await _rodar(adaptador) is None
    assert len(interactions.chamadas) == 1


async def test_pdf_com_imagens_alem_do_limite_nao_gera_nem_cobra_imagem_de_novo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gemini_adapter, "extrair_markdown", _dormindo(0, "# T\n\nOriginal."))
    monkeypatch.setattr(gemini_adapter, "extrair_imagens", _dormindo(0, []))
    monkeypatch.setattr(
        gemini_adapter, "gerar_pdf_com_imagens_geradas", _dormindo(0.3, b"%PDF-falso")
    )
    gerador = _GeradorFalso()
    adaptador, interactions = _adaptador(
        _RESPOSTA_1,
        gerador,
        imagens_geradas_habilitadas=True,
        imagens_max_por_material=1,
        timeout_pdf_segundos=_CURTO,
    )

    assert await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes()) is None
    # A imagem foi gerada uma única vez e a montagem estourou: nada é refeito nesta execução.
    assert len(gerador.conceitos) == 1
    assert len(interactions.chamadas) == 1


# Limite conhecido: a thread da etapa não é interrompida


async def test_apos_o_timeout_a_thread_continua_e_o_fallback_nao_espera_por_ela(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Trava o comportamento atual: estourar o limite encerra só a espera.

    A thread do PDF não pode ser cancelada em Python e segue até terminar; o evento a libera
    no fim do teste.
    """
    import logging
    import threading

    iniciou, liberar, terminou = threading.Event(), threading.Event(), threading.Event()

    def pdf_com_imagens_travado(*_args: Any, **_kwargs: Any) -> bytes:
        iniciou.set()
        liberar.wait(timeout=30)  # trava de segurança: nunca prende o processo de testes
        terminou.set()
        return b"%PDF-tardio"

    monkeypatch.setattr(gemini_adapter, "extrair_markdown", _dormindo(0, "# T\n\nOriginal."))
    monkeypatch.setattr(gemini_adapter, "extrair_imagens", _dormindo(0, []))
    monkeypatch.setattr(gemini_adapter, "gerar_pdf", _dormindo(0, b"%PDF-sem-imagens"))
    monkeypatch.setattr(gemini_adapter, "gerar_pdf_com_imagens_geradas", pdf_com_imagens_travado)
    adaptador, interactions = _adaptador(
        _RESPOSTA_1,
        _GeradorFalso(),
        imagens_geradas_habilitadas=True,
        imagens_max_por_material=1,
        timeout_pdf_segundos=_CURTO,
    )

    try:
        with caplog.at_level(logging.WARNING):
            resultado = await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())

        assert resultado is not None and resultado.conteudo_pdf == b"%PDF-sem-imagens"
        assert iniciou.is_set() and not terminou.is_set()  # a thread órfã ainda está rodando
        assert "continuar em segundo plano" in caplog.text
        assert len(interactions.chamadas) == 1  # e nenhuma chamada paga foi repetida
    finally:
        liberar.set()
        assert terminou.wait(timeout=10)  # a thread acaba assim que liberada
