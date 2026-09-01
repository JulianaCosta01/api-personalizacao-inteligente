from types import SimpleNamespace
from unittest.mock import patch

import pytest

from infrastructure.pipeline.erros import ErroDePipeline
from infrastructure.pipeline.extrator import extrair_markdown

from .pdf_fixture import pdf_valido


def test_extrai_markdown_de_pdf_valido() -> None:
    conteudo = extrair_markdown(pdf_valido("Titulo de Teste"))

    assert "Titulo de Teste" in conteudo


def test_rejeita_conteudo_sem_assinatura_de_pdf() -> None:
    with pytest.raises(ErroDePipeline):
        extrair_markdown(b"nao e um pdf")


def test_rejeita_conteudo_com_assinatura_mas_corrompido() -> None:
    with pytest.raises(ErroDePipeline):
        extrair_markdown(b"%PDF-1.7 dados corrompidos, nao e um pdf de verdade")


def test_rejeita_pdf_acima_do_tamanho_maximo() -> None:
    conteudo_grande = pdf_valido("x") + b"0" * (10 * 1024 * 1024)

    with pytest.raises(ErroDePipeline):
        extrair_markdown(conteudo_grande)


def test_respeita_o_limite_configurado_em_settings_nao_um_valor_fixo() -> None:
    # Settings é a única fonte de verdade: um PDF pequeno mas acima do limite configurado
    # precisa ser rejeitado — prova que o teto não é uma constante fixa no módulo.
    conteudo = pdf_valido("x") + b"0" * 2048

    with (
        patch(
            "infrastructure.pipeline.extrator.get_settings",
            return_value=SimpleNamespace(material_tamanho_maximo_bytes=1024),
        ),
        pytest.raises(ErroDePipeline),
    ):
        extrair_markdown(conteudo)


def test_aceita_pdf_dentro_do_limite_configurado_em_settings() -> None:
    conteudo = pdf_valido("Titulo Dentro Do Limite")
    assert len(conteudo) < 1_000_000

    with patch(
        "infrastructure.pipeline.extrator.get_settings",
        return_value=SimpleNamespace(material_tamanho_maximo_bytes=1_000_000),
    ):
        markdown = extrair_markdown(conteudo)

    assert "Titulo Dentro Do Limite" in markdown
