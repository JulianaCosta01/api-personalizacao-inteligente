"""Recuperação: PDF só com texto quando a montagem com imagens geradas falha.

Nada de rede nem de nova chamada paga; tudo com dublês, exceto o teste marcado.
"""

import logging
import time
from typing import Any

import pymupdf
import pytest

from infrastructure.llm import gemini_adapter
from infrastructure.llm.gemini_adapter import _texto_sem_marcadores_visuais
from tests.unit.infrastructure.llm.test_gemini_adapter import _dimensoes
from tests.unit.infrastructure.llm.test_gemini_geracao_imagens import (
    _RESPOSTA_1,
    _adaptador,
    _GeradorFalso,
)
from tests.unit.infrastructure.pipeline.pdf_fixture import pdf_valido

_PDF_COM_IMAGENS = b"%PDF-com-imagens"
_PDF_SEM_IMAGENS = b"%PDF-sem-imagens"
_CURTO = 0.05  # limite do PDF que as montagens "lentas" (0,3 s) sempre estouram
_OPCOES_IMAGENS: dict[str, Any] = {
    "imagens_geradas_habilitadas": True,
    "imagens_max_por_material": 1,
    "timeout_pdf_segundos": _CURTO,
}


class _Montagens:
    """Dublê das duas montagens de PDF; registra o que cada uma recebeu."""

    def __init__(self) -> None:
        self.com_imagens: list[str] = []
        self.sem_imagens: list[str] = []
        self.comportamento_com_imagens = "ok"
        self.comportamento_sem_imagens = "ok"

    @staticmethod
    def _executar(comportamento: str, pdf: bytes) -> bytes:
        if comportamento == "lento":
            time.sleep(0.3)
        elif comportamento == "erro":
            raise RuntimeError("segredo-na-mensagem-da-excecao")
        return pdf

    def gerar_com_imagens(self, markdown: str, *_args: Any, **_kwargs: Any) -> bytes:
        self.com_imagens.append(markdown)
        return self._executar(self.comportamento_com_imagens, _PDF_COM_IMAGENS)

    def gerar_sem_imagens(self, markdown: str, *_args: Any, **_kwargs: Any) -> bytes:
        self.sem_imagens.append(markdown)
        return self._executar(self.comportamento_sem_imagens, _PDF_SEM_IMAGENS)


@pytest.fixture
def montagens(monkeypatch: pytest.MonkeyPatch) -> _Montagens:
    dubles = _Montagens()
    monkeypatch.setattr(gemini_adapter, "extrair_markdown", lambda _c: "# T\n\nOriginal.")
    monkeypatch.setattr(gemini_adapter, "extrair_imagens", lambda _c: [])
    monkeypatch.setattr(gemini_adapter, "gerar_pdf_com_imagens_geradas", dubles.gerar_com_imagens)
    monkeypatch.setattr(gemini_adapter, "gerar_pdf", dubles.gerar_sem_imagens)
    return dubles


async def _rodar(adaptador: Any) -> Any:
    return await adaptador.reescrever_conteudo(pdf_valido(), *_dimensoes())


# Caminho normal


async def test_pdf_com_imagens_e_gerado_normalmente_sem_acionar_o_fallback(
    montagens: _Montagens,
) -> None:
    gerador = _GeradorFalso()
    adaptador, interactions = _adaptador(_RESPOSTA_1, gerador, **_OPCOES_IMAGENS)

    resultado = await _rodar(adaptador)

    assert resultado is not None and resultado.conteudo_pdf == _PDF_COM_IMAGENS
    assert len(montagens.com_imagens) == 1
    assert montagens.sem_imagens == []
    assert len(gerador.conceitos) == 1 and len(interactions.chamadas) == 1


# Recuperação


@pytest.mark.parametrize("falha", ["erro", "lento"])
async def test_falha_ou_timeout_do_pdf_com_imagens_recai_no_pdf_so_com_texto(
    montagens: _Montagens, falha: str
) -> None:
    montagens.comportamento_com_imagens = falha
    gerador = _GeradorFalso()
    adaptador, interactions = _adaptador(_RESPOSTA_1, gerador, **_OPCOES_IMAGENS)

    resultado = await _rodar(adaptador)

    assert resultado is not None
    assert resultado.conteudo_pdf == _PDF_SEM_IMAGENS
    assert len(montagens.com_imagens) == 1 and len(montagens.sem_imagens) == 1


@pytest.mark.parametrize("falha", ["erro", "lento"])
async def test_fallback_nao_repete_nenhuma_chamada_paga(montagens: _Montagens, falha: str) -> None:
    montagens.comportamento_com_imagens = falha
    gerador = _GeradorFalso()
    adaptador, interactions = _adaptador(_RESPOSTA_1, gerador, **_OPCOES_IMAGENS)

    assert await _rodar(adaptador) is not None

    assert len(interactions.chamadas) == 1  # Gemini: só a chamada original
    assert len(gerador.conceitos) == 1  # a imagem já gerada não é pedida de novo


async def test_fallback_preserva_o_texto_e_nao_deixa_marcadores_nem_ancoras(
    montagens: _Montagens,
) -> None:
    montagens.comportamento_com_imagens = "erro"
    adaptador, _ = _adaptador(_RESPOSTA_1, _GeradorFalso(), **_OPCOES_IMAGENS)

    resultado = await _rodar(adaptador)

    # A montagem com imagens recebeu a âncora (é ela que posiciona a imagem)...
    assert "mpi-ancora" in montagens.com_imagens[0]
    # ...e a de recuperação recebeu o mesmo texto, sem marcador, sem âncora e sem descrição.
    texto = montagens.sem_imagens[0]
    assert "[[IMAGEM" not in texto and "mpi-ancora" not in texto and "Grafo com" not in texto
    assert "Primeiro parágrafo." in texto and "Segundo parágrafo." in texto
    assert resultado is not None and "IMAGEM" not in resultado.resumo


def test_remocao_de_marcadores_do_fallback_apaga_marcador_e_ancora() -> None:
    sujo = (
        "Antes.\n\n[[IMAGEM:g1|Grafo com três nós ligados por arestas]]\n\n"
        "<!--mpi-ancora:g1-->\n\nDepois."
    )
    limpo = _texto_sem_marcadores_visuais(sujo)
    assert "[[IMAGEM" not in limpo and "mpi-ancora" not in limpo
    assert "Antes." in limpo and "Depois." in limpo


# Falha também na montagem sem imagens


@pytest.mark.parametrize(
    ("com_imagens", "sem_imagens"), [("erro", "erro"), ("lento", "erro"), ("lento", "lento")]
)
async def test_falha_tambem_no_pdf_sem_imagens_mantem_o_erro_atual(
    montagens: _Montagens, com_imagens: str, sem_imagens: str
) -> None:
    montagens.comportamento_com_imagens = com_imagens
    montagens.comportamento_sem_imagens = sem_imagens
    gerador = _GeradorFalso()
    adaptador, interactions = _adaptador(_RESPOSTA_1, gerador, **_OPCOES_IMAGENS)

    # None = o caso de uso encerra em erro; nenhum PDF inválido é devolvido, nenhuma exceção
    # transitória é levantada (o job não volta à fila para repetir chamadas pagas).
    assert await _rodar(adaptador) is None
    assert len(montagens.sem_imagens) == 1
    assert len(interactions.chamadas) == 1 and len(gerador.conceitos) == 1


# Imagens desabilitadas


async def test_com_imagens_desabilitadas_nada_muda(montagens: _Montagens) -> None:
    adaptador, interactions = _adaptador(_RESPOSTA_1, None, timeout_pdf_segundos=_CURTO)

    resultado = await _rodar(adaptador)

    assert resultado is not None and resultado.conteudo_pdf == _PDF_SEM_IMAGENS
    assert montagens.com_imagens == []  # nunca tenta a montagem com imagens
    assert len(montagens.sem_imagens) == 1
    # Recurso desligado: o texto do modelo segue para o PDF exatamente como antes desta recuperação
    # (o tratamento de marcadores só atua com o recurso ligado).
    assert montagens.sem_imagens[0] == _RESPOSTA_1
    assert len(interactions.chamadas) == 1


async def test_sem_nenhuma_imagem_gerada_o_pdf_sem_imagens_e_o_caminho_normal(
    montagens: _Montagens,
) -> None:
    from application.ports.gerador_imagens import FalhaGeracaoImagem, MotivoFalhaImagem

    falha = FalhaGeracaoImagem("g1", MotivoFalhaImagem.INDISPONIVEL)
    adaptador, _ = _adaptador(_RESPOSTA_1, _GeradorFalso(falha), **_OPCOES_IMAGENS)

    resultado = await _rodar(adaptador)

    assert resultado is not None and resultado.conteudo_pdf == _PDF_SEM_IMAGENS
    assert montagens.com_imagens == []


# Registro


async def test_fallback_registra_tipo_e_pilha_sem_a_mensagem_da_excecao(
    montagens: _Montagens, caplog: pytest.LogCaptureFixture
) -> None:
    montagens.comportamento_com_imagens = "erro"
    adaptador, _ = _adaptador(_RESPOSTA_1, _GeradorFalso(), **_OPCOES_IMAGENS)

    with caplog.at_level(logging.WARNING):
        assert await _rodar(adaptador) is not None

    assert "refazendo só com o texto" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "segredo-na-mensagem-da-excecao" not in caplog.text


# Pipeline de PDF real


async def test_fallback_com_o_gerador_de_pdf_real_produz_pdf_valido_sem_marcadores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Único teste desta recuperação que usa a montagem real do PDF (WeasyPrint): confirma que o
    # arquivo é um PDF legível e que nenhum marcador aparece no texto. O limite é o de produção
    # (60 s), não um valor ajustado para o teste passar.
    monkeypatch.setattr(gemini_adapter, "extrair_markdown", lambda _c: "# T\n\nOriginal.")
    monkeypatch.setattr(gemini_adapter, "extrair_imagens", lambda _c: [])

    def quebrar(*_args: Any, **_kwargs: Any) -> bytes:
        raise RuntimeError("falha simulada na montagem com imagens")

    monkeypatch.setattr(gemini_adapter, "gerar_pdf_com_imagens_geradas", quebrar)
    adaptador, _ = _adaptador(
        _RESPOSTA_1,
        _GeradorFalso(),
        imagens_geradas_habilitadas=True,
        imagens_max_por_material=1,
        timeout_pdf_segundos=60.0,
    )

    resultado = await _rodar(adaptador)

    assert resultado is not None and resultado.conteudo_pdf.startswith(b"%PDF-")
    documento = pymupdf.open(stream=resultado.conteudo_pdf, filetype="pdf")
    texto = " ".join(documento[i].get_text() for i in range(documento.page_count))
    assert "Primeiro parágrafo." in texto and "Segundo parágrafo." in texto
    assert "IMAGEM" not in texto and "mpi-ancora" not in texto
