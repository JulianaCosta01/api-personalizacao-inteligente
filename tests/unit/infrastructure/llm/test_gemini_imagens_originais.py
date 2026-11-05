"""As imagens do PDF de origem não substituem as ilustrações geradas por IA.

Por padrão elas não são extraídas nem anexadas ("Imagens do material original"); só entram com o
opt-in explícito. Nenhum teste aqui fala com o Gemini ou com o provedor de imagens.
"""

from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from infrastructure.config.settings import Settings
from infrastructure.llm import gemini_adapter
from infrastructure.llm.gemini_adapter import GeminiAdapter
from tests.unit.infrastructure.llm.limites_locais import LIMITES_LOCAIS_DE_PRODUCAO
from tests.unit.infrastructure.llm.test_gemini_adapter import _cliente_fake, _InteractionsFake
from tests.unit.infrastructure.pipeline.pdf_fixture import pdf_com_imagem

_TEXTO = "# Título\n\nConteúdo adaptado do material, com uma explicação suficiente."


def _dimensoes() -> tuple[EstiloProcessamento, Percepcao, Entrada, Compreensao]:
    return EstiloProcessamento.ATIVO, Percepcao.SENSORIAL, Entrada.VISUAL, Compreensao.SEQUENCIAL


async def _rodar(**opcoes: Any) -> tuple[Any, list[int]]:
    chamadas: list[int] = []
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text=_TEXTO))
    adaptador = GeminiAdapter(
        _cliente_fake(interactions),
        "gemini-3.1-flash-lite",
        5.0,
        **{**LIMITES_LOCAIS_DE_PRODUCAO, **opcoes},
    )
    original = gemini_adapter.extrair_imagens

    def espiao(conteudo: bytes) -> Any:
        chamadas.append(1)
        return original(conteudo)

    gemini_adapter.extrair_imagens = espiao  # type: ignore[assignment]
    try:
        resultado = await adaptador.reescrever_conteudo(pdf_com_imagem(), *_dimensoes())
    finally:
        gemini_adapter.extrair_imagens = original  # type: ignore[assignment]
    return resultado, chamadas


def _titulos_e_imagens(pdf: bytes) -> tuple[str, int]:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    texto = "".join(p.get_text() for p in doc)
    # A imagem do logotipo institucional da capa é a única esperada sem opt-in.
    unicas = {ref[0] for p in doc for ref in p.get_images(full=True)}
    return texto, len(unicas)


def test_o_padrao_do_settings_nao_anexa_imagens_originais() -> None:
    assert Settings(_env_file=None).pdf_anexar_imagens_originais is False


async def test_por_padrao_as_imagens_originais_nem_sao_extraidas() -> None:
    resultado, chamadas = await _rodar()

    assert resultado is not None
    assert chamadas == []  # sem extração: sem custo e sem seção de imagens originais
    texto, _ = _titulos_e_imagens(resultado.conteudo_pdf)
    assert "Imagens do material original" not in texto


async def test_com_opt_in_as_imagens_originais_voltam_a_ser_anexadas() -> None:
    resultado, chamadas = await _rodar(anexar_imagens_originais=True)

    assert resultado is not None
    assert chamadas == [1]
    texto, _ = _titulos_e_imagens(resultado.conteudo_pdf)
    assert "Imagens do material original" in texto


async def test_opt_in_acrescenta_imagens_ao_pdf_em_relacao_ao_padrao() -> None:
    sem, _ = await _rodar()
    com, _ = await _rodar(anexar_imagens_originais=True)
    assert sem is not None and com is not None

    _, imagens_sem = _titulos_e_imagens(sem.conteudo_pdf)
    _, imagens_com = _titulos_e_imagens(com.conteudo_pdf)
    assert imagens_com > imagens_sem


@pytest.mark.parametrize("valor", ["true", "false"])
def test_o_settings_le_a_variavel_de_ambiente(monkeypatch: pytest.MonkeyPatch, valor: str) -> None:
    monkeypatch.setenv("PDF_ANEXAR_IMAGENS_ORIGINAIS", valor)
    assert Settings(_env_file=None).pdf_anexar_imagens_originais is (valor == "true")
