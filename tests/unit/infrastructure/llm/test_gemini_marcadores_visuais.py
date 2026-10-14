import logging
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest

from application.ports.gerador_imagens import ConceitoVisual
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from infrastructure.llm import gemini_adapter
from infrastructure.llm.gemini_adapter import _INSTRUCAO_COMPLEMENTAR_IMAGENS, GeminiAdapter
from infrastructure.pipeline.gerador_pdf import gerar_pdf
from tests.unit.infrastructure.llm.test_gemini_adapter import _cliente_fake, _InteractionsFake
from tests.unit.infrastructure.pipeline.pdf_fixture import pdf_valido

_DESC = "Grafo com três nós ligados por arestas"
_MARCADOR = f"[[IMAGEM:g1|{_DESC}]]"
_SEM_MARCADOR = (
    "# Título adaptado\n\nPrimeiro parágrafo.\n\nSegundo parágrafo.\n\nTerceiro parágrafo."
)
_COM_MARCADOR = (
    "# Título adaptado\n\nPrimeiro parágrafo.\n\n"
    f"{_MARCADOR}\n\nSegundo parágrafo.\n\nTerceiro parágrafo."
)


def _dimensoes() -> tuple[EstiloProcessamento, Percepcao, Entrada, Compreensao]:
    return EstiloProcessamento.ATIVO, Percepcao.SENSORIAL, Entrada.VISUAL, Compreensao.SEQUENCIAL


def _adaptador(texto: str | None, **opcoes: Any) -> tuple[GeminiAdapter, _InteractionsFake]:
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text=texto))
    adaptador = GeminiAdapter(_cliente_fake(interactions), "gemini-3.1-flash-lite", 5.0, **opcoes)
    return adaptador, interactions


def _paginas(pdf: bytes) -> str:
    documento = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        paginas = (documento[i] for i in range(documento.page_count))
        return " ".join(" ".join(pagina.get_text().split()) for pagina in paginas)
    finally:
        documento.close()


@pytest.fixture
def markdown_enviado_ao_pdf(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recebidos: list[str] = []

    def falso(markdown: str, imagens: Sequence[Any] = (), **_: Any) -> bytes:
        recebidos.append(markdown)
        return b"%PDF-falso"

    monkeypatch.setattr(gemini_adapter, "gerar_pdf", falso)
    return recebidos


def _quebrada(*_: Any, **__: Any) -> Any:
    raise RuntimeError(f"erro com {_DESC}")


# --- recurso desligado -------------------------------------------------------------------------


async def test_desligado_sem_marcadores_a_saida_e_equivalente_a_anterior() -> None:
    adaptador, _ = _adaptador(_SEM_MARCADOR)
    resultado = await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    assert resultado is not None
    assert _paginas(resultado.conteudo_pdf) == _paginas(gerar_pdf(_SEM_MARCADOR))
    assert resultado.resumo == "Primeiro parágrafo."


async def test_desligado_sem_marcadores_o_markdown_chega_identico_ao_pdf(
    markdown_enviado_ao_pdf: list[str],
) -> None:
    adaptador, _ = _adaptador(_SEM_MARCADOR)
    await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())
    assert markdown_enviado_ao_pdf == [_SEM_MARCADOR]


async def test_desligado_o_fluxo_nao_toca_no_texto_nem_com_marcador_literal(
    markdown_enviado_ao_pdf: list[str],
) -> None:
    # Comportamento anterior preservado: sem o recurso, a resposta segue como veio.
    adaptador, _ = _adaptador(_COM_MARCADOR)
    resultado = await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    assert resultado is not None
    assert markdown_enviado_ao_pdf == [_COM_MARCADOR]


async def test_desligado_o_conteudo_original_segue_sem_alteracao_para_o_modelo() -> None:
    adaptador, interactions = _adaptador(_SEM_MARCADOR)
    await adaptador.reescrever_conteudo(pdf_valido("Texto comum do original."), *_dimensoes())
    assert "Texto comum do original." in interactions.chamadas[0]["input"]


# --- recurso ligado ----------------------------------------------------------------------------


async def test_ligado_marcador_valido_vira_conceito_e_some_do_texto_renderizado(
    markdown_enviado_ao_pdf: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    adaptador, _ = _adaptador(_COM_MARCADOR, imagens_geradas_habilitadas=True)
    with caplog.at_level(logging.INFO):
        resultado = await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    assert resultado is not None
    renderizado = markdown_enviado_ao_pdf[0]
    assert "[[IMAGEM" not in renderizado and "mpi-ancora" not in renderizado
    assert _DESC not in renderizado
    assert "Conceitos visuais identificados: 1." in caplog.text
    assert _DESC not in caplog.text


async def test_ligado_o_pdf_real_nao_mostra_marcador_nem_ancora() -> None:
    adaptador, _ = _adaptador(_COM_MARCADOR, imagens_geradas_habilitadas=True)
    resultado = await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    assert resultado is not None
    texto = _paginas(resultado.conteudo_pdf)
    assert "IMAGEM" not in texto and "mpi-ancora" not in texto and _DESC not in texto
    assert texto.index("Primeiro parágrafo.") < texto.index("Segundo parágrafo.")
    assert texto.index("Segundo parágrafo.") < texto.index("Terceiro parágrafo.")


async def test_ligado_o_texto_e_a_ordem_dos_paragrafos_sao_preservados(
    markdown_enviado_ao_pdf: list[str],
) -> None:
    adaptador, _ = _adaptador(_COM_MARCADOR, imagens_geradas_habilitadas=True)
    await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    paragrafos = [p for p in markdown_enviado_ao_pdf[0].split("\n") if p.strip()]
    assert paragrafos == [
        "# Título adaptado",
        "Primeiro parágrafo.",
        "Segundo parágrafo.",
        "Terceiro parágrafo.",
    ]


def test_metodo_extrai_o_conceito_com_os_campos_esperados() -> None:
    adaptador, _ = _adaptador(None, imagens_geradas_habilitadas=True)
    texto, conceitos = adaptador._tratar_marcadores_visuais(_COM_MARCADOR)

    assert [(c.identificador, c.descricao, c.ancora) for c in conceitos] == [("g1", _DESC, "g1")]
    assert all(isinstance(c, ConceitoVisual) for c in conceitos)
    # O marcador some; a âncora interna do conceito aceito fica até a montagem do PDF.
    assert "IMAGEM" not in texto and _DESC not in texto
    assert texto.count("<!--mpi-ancora:g1-->") == 1


def test_metodo_com_recurso_desligado_nao_devolve_conceitos() -> None:
    adaptador, _ = _adaptador(None)
    texto, conceitos = adaptador._tratar_marcadores_visuais(_COM_MARCADOR)
    assert conceitos == ()
    assert texto == _COM_MARCADOR


def test_metodo_ligado_com_maximo_zero_remove_sem_extrair() -> None:
    adaptador, _ = _adaptador(None, imagens_geradas_habilitadas=True, imagens_max_por_material=0)
    texto, conceitos = adaptador._tratar_marcadores_visuais(_COM_MARCADOR)
    assert conceitos == ()
    assert "IMAGEM" not in texto


def test_invalidos_duplicados_e_excedentes_nao_viram_conceito() -> None:
    adaptador, _ = _adaptador(None, imagens_geradas_habilitadas=True, imagens_max_por_material=2)
    texto = "\n\n".join(
        [
            "Início.",
            "[[IMAGEM:a1|Primeira descrição válida]]",
            "[[IMAGEM:a1|Repetida com o mesmo identificador]]",
            "[[IMAGEM:b2|<script>alert(1)</script> hostil]]",
            "[[IMAGEM:c3]]",
            "[[IMAGEM:d4|Segunda descrição válida]]",
            "[[IMAGEM:e5|Terceira descrição acima do limite]]",
            "Fim.",
        ]
    )
    limpo, conceitos = adaptador._tratar_marcadores_visuais(texto)

    assert [c.identificador for c in conceitos] == ["a1", "d4"]
    assert "IMAGEM" not in limpo and "script" not in limpo
    assert limpo.count("mpi-ancora") == 2  # uma âncora por conceito aceito, nenhuma forjada
    assert "<!--mpi-ancora:a1-->" in limpo and "<!--mpi-ancora:d4-->" in limpo
    assert "Início." in limpo and "Fim." in limpo


async def test_ligado_respeita_o_limite_padrao_de_uma_imagem(
    markdown_enviado_ao_pdf: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    resposta = f"# T\n\nCorpo.\n\n{_MARCADOR}\n\n[[IMAGEM:g2|Outra descrição também válida]]\n"
    adaptador, _ = _adaptador(resposta, imagens_geradas_habilitadas=True)
    with caplog.at_level(logging.INFO):
        await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())
    assert "Conceitos visuais identificados: 1." in caplog.text


# --- conteúdo original e âncoras forjadas ------------------------------------------------------


async def test_ligado_marcador_e_ancora_do_original_nao_chegam_ao_modelo() -> None:
    original = "Veja [[IMAGEM:x1|Desenho do original aqui]] e <!--mpi-ancora:x1--> depois."
    adaptador, interactions = _adaptador(_SEM_MARCADOR, imagens_geradas_habilitadas=True)
    await adaptador.reescrever_conteudo(pdf_valido(original), *_dimensoes())

    entrada = interactions.chamadas[0]["input"]
    assert "[[IMAGEM" not in entrada and "mpi-ancora" not in entrada
    assert "Veja" in entrada and "depois." in entrada


async def test_ancora_forjada_na_resposta_e_removida_com_o_recurso_ligado(
    markdown_enviado_ao_pdf: list[str],
) -> None:
    resposta = "# T\n\nAntes.\n\n<!--mpi-ancora:fake-->\n\nMeio <!-- mpi-ancora:x2 --> fim.\n"
    adaptador, _ = _adaptador(resposta, imagens_geradas_habilitadas=True)
    await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    assert "mpi-ancora" not in markdown_enviado_ao_pdf[0]
    assert "Meio" in markdown_enviado_ao_pdf[0]


async def test_ancora_na_resposta_segue_inalterada_com_o_recurso_desligado(
    markdown_enviado_ao_pdf: list[str],
) -> None:
    # Sem o recurso não há consumidor de âncoras: o comentário HTML é inerte no PDF.
    resposta = "# T\n\nAntes.\n\n<!--mpi-ancora:fake-->\n\nDepois."
    adaptador, _ = _adaptador(resposta)
    await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())
    assert markdown_enviado_ao_pdf == [resposta]


async def test_marcador_dentro_de_codigo_na_resposta_permanece_como_texto(
    markdown_enviado_ao_pdf: list[str],
) -> None:
    resposta = f"# T\n\nExemplo:\n\n```\n{_MARCADOR}\n```\n"
    adaptador, _ = _adaptador(resposta, imagens_geradas_habilitadas=True)
    await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())
    assert _MARCADOR in markdown_enviado_ao_pdf[0]


# --- resumo ------------------------------------------------------------------------------------


async def test_resumo_nao_contem_marcador_nem_ancora_com_o_recurso_ligado() -> None:
    resposta = f"{_MARCADOR}\n\n# Título\n\nCorpo do material adaptado."
    adaptador, _ = _adaptador(resposta, imagens_geradas_habilitadas=True)
    resultado = await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    assert resultado is not None
    assert resultado.resumo == "Corpo do material adaptado."


async def test_resposta_so_com_marcadores_e_descartada_com_o_recurso_ligado() -> None:
    adaptador, _ = _adaptador(
        f"{_MARCADOR}\n\n[[IMAGEM:g2|Outra descrição válida aqui]]\n",
        imagens_geradas_habilitadas=True,
    )
    assert await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes()) is None


async def test_resposta_so_com_marcadores_segue_o_fluxo_anterior_com_o_recurso_desligado() -> None:
    adaptador, _ = _adaptador(_MARCADOR)
    assert await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes()) is not None


# --- eco da instrução complementar -------------------------------------------------------------


async def test_eco_completo_do_complemento_e_rejeitado_com_o_recurso_ligado() -> None:
    eco = _INSTRUCAO_COMPLEMENTAR_IMAGENS.format(maximo=1)
    adaptador, _ = _adaptador(eco, imagens_geradas_habilitadas=True)
    assert await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes()) is None


async def test_eco_parcial_da_abertura_do_complemento_e_rejeitado() -> None:
    abertura = _INSTRUCAO_COMPLEMENTAR_IMAGENS.split(" Regras:")[0]
    adaptador, _ = _adaptador(f"# T\n\n{abertura}", imagens_geradas_habilitadas=True)
    assert await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes()) is None


async def test_eco_do_complemento_com_limite_diferente_tambem_e_rejeitado() -> None:
    eco = _INSTRUCAO_COMPLEMENTAR_IMAGENS.format(maximo=4)
    adaptador, _ = _adaptador(eco, imagens_geradas_habilitadas=True, imagens_max_por_material=1)
    assert await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes()) is None


async def test_texto_comum_com_marcador_nao_e_confundido_com_eco() -> None:
    adaptador, _ = _adaptador(_COM_MARCADOR, imagens_geradas_habilitadas=True)
    assert await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes()) is not None


# --- falha no tratamento de conceitos ---------------------------------------------------------


async def test_falha_ao_extrair_conceitos_nao_perde_o_texto_adaptado(
    monkeypatch: pytest.MonkeyPatch,
    markdown_enviado_ao_pdf: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(gemini_adapter, "extrair_conceitos_visuais", _quebrada)
    adaptador, _ = _adaptador(_COM_MARCADOR, imagens_geradas_habilitadas=True)
    with caplog.at_level(logging.DEBUG):
        resultado = await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    assert resultado is not None
    renderizado = markdown_enviado_ao_pdf[0]
    assert "Primeiro parágrafo." in renderizado and "Terceiro parágrafo." in renderizado
    assert "IMAGEM" not in renderizado
    assert "RuntimeError" in caplog.text
    assert _DESC not in caplog.text


async def test_falha_total_no_tratamento_mantem_o_texto_e_nao_interrompe(
    monkeypatch: pytest.MonkeyPatch,
    markdown_enviado_ao_pdf: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(gemini_adapter, "extrair_conceitos_visuais", _quebrada)
    monkeypatch.setattr(gemini_adapter, "remover_marcadores_visuais", _quebrada)
    adaptador, _ = _adaptador(_COM_MARCADOR, imagens_geradas_habilitadas=True)
    with caplog.at_level(logging.DEBUG):
        resultado = await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    assert resultado is not None
    assert "Primeiro parágrafo." in markdown_enviado_ao_pdf[0]
    assert _DESC not in caplog.text


async def test_com_o_recurso_desligado_nenhuma_funcao_de_marcadores_e_chamada(
    monkeypatch: pytest.MonkeyPatch, markdown_enviado_ao_pdf: list[str]
) -> None:
    monkeypatch.setattr(gemini_adapter, "remover_marcadores_visuais", _quebrada)
    monkeypatch.setattr(gemini_adapter, "extrair_conceitos_visuais", _quebrada)
    adaptador, _ = _adaptador(_SEM_MARCADOR)
    resultado = await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())

    assert resultado is not None
    assert markdown_enviado_ao_pdf == [_SEM_MARCADOR]


# --- validação existente continua valendo -----------------------------------------------------


@pytest.mark.parametrize("ligado", [False, True])
@pytest.mark.parametrize("texto", [None, "", "   ", "a" * 200_001])
async def test_validacao_existente_continua_rejeitando(ligado: bool, texto: str | None) -> None:
    adaptador, _ = _adaptador(texto, imagens_geradas_habilitadas=ligado)
    assert await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes()) is None


async def test_uma_unica_chamada_ao_duble_do_cliente() -> None:
    adaptador, interactions = _adaptador(_COM_MARCADOR, imagens_geradas_habilitadas=True)
    await adaptador.reescrever_conteudo(pdf_valido("Origem."), *_dimensoes())
    assert len(interactions.chamadas) == 1
