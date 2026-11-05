import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pymupdf
import pytest

from core.config import get_settings
from infrastructure.pipeline import extrator
from infrastructure.pipeline.erros import ErroDePipeline
from infrastructure.pipeline.extrator import (
    ImagemExtraida,
    contar_paginas,
    extrair_imagens,
    extrair_markdown,
)

from .pdf_fixture import pdf_com_imagem, pdf_valido


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
    # precisa ser rejeitado: prova que o teto não é uma constante fixa no módulo.
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
        return_value=SimpleNamespace(
            material_tamanho_maximo_bytes=1_000_000, pdf_paginas_maximas=100
        ),
    ):
        markdown = extrair_markdown(conteudo)

    assert "Titulo Dentro Do Limite" in markdown


def test_extrai_lista_vazia_de_pdf_sem_imagens() -> None:
    imagens = extrair_imagens(pdf_valido("Sem imagem."))

    assert imagens == []


def test_extrai_imagem_de_pdf_com_uma_imagem() -> None:
    imagens = extrair_imagens(pdf_com_imagem("Com imagem."))

    assert len(imagens) == 1
    assert imagens[0].numero_pagina == 0
    assert imagens[0].indice_na_pagina == 0
    assert imagens[0].extensao


def test_imagem_extraida_preserva_os_bytes_originais() -> None:
    imagens = extrair_imagens(pdf_com_imagem())

    assert len(imagens) == 1
    assert isinstance(imagens[0].conteudo, bytes)
    assert len(imagens[0].conteudo) > 0


def test_extrair_imagens_rejeita_conteudo_sem_assinatura_de_pdf() -> None:
    with pytest.raises(ErroDePipeline):
        extrair_imagens(b"nao e um pdf")


def test_extrair_imagens_rejeita_conteudo_com_assinatura_mas_corrompido() -> None:
    with pytest.raises(ErroDePipeline):
        extrair_imagens(b"%PDF-1.7 dados corrompidos, nao e um pdf de verdade")


def test_extrair_imagens_rejeita_pdf_acima_do_tamanho_maximo() -> None:
    conteudo_grande = pdf_valido("x") + b"0" * (10 * 1024 * 1024)

    with pytest.raises(ErroDePipeline):
        extrair_imagens(conteudo_grande)


# Transparência, bytes originais e cache de conversão
# Os PDFs são montados aqui (e não em pdf_fixture) porque dependem de detalhes de /SMask e /Mask.


def _pixmap_meio_transparente(espaco: Any, cor: tuple[int, ...]) -> pymupdf.Pixmap:
    # Metade esquerda com alfa 0 e metade direita opaca.
    pixmap = pymupdf.Pixmap(espaco, (0, 0, 16, 16), True)
    pixmap.set_rect(pixmap.irect, (*cor, 255))
    for x in range(8):
        for y in range(16):
            pixmap.set_pixel(x, y, (*cor, 0))
    return pixmap


def _pdf_com_pixmap(pixmap: pymupdf.Pixmap, paginas: int = 1) -> bytes:
    documento = pymupdf.open()
    for _ in range(paginas):
        documento.new_page().insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=pixmap)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def _alfa_esquerda_direita(conteudo_png: bytes) -> tuple[int, int]:
    pixmap = pymupdf.Pixmap(conteudo_png)
    assert pixmap.alpha == 1
    return pixmap.pixel(0, 0)[-1], pixmap.pixel(15, 0)[-1]


def _anexar_mascara(
    documento: pymupdf.Document, xref_imagem: int, chave: str, dicionario: str, dados: bytes
) -> None:
    xref_mascara = documento.get_new_xref()
    documento.update_object(xref_mascara, dicionario)
    documento.update_stream(xref_mascara, dados, compress=False)
    documento.xref_set_key(xref_imagem, chave, f"{xref_mascara} 0 R")


def test_transparencia_rgb_com_smask_e_preservada_como_png_com_alfa() -> None:
    pdf = _pdf_com_pixmap(_pixmap_meio_transparente(pymupdf.csRGB, (200, 30, 30)))

    (imagem,) = extrair_imagens(pdf)

    assert imagem.extensao == "png"
    assert _alfa_esquerda_direita(imagem.conteudo) == (0, 255)


def test_transparencia_em_tons_de_cinza_e_preservada() -> None:
    pdf = _pdf_com_pixmap(_pixmap_meio_transparente(pymupdf.csGRAY, (90,)))

    (imagem,) = extrair_imagens(pdf)

    assert imagem.extensao == "png"
    assert _alfa_esquerda_direita(imagem.conteudo) == (0, 255)


def test_transparencia_cmyk_com_smask_e_convertida_para_rgb_com_alfa() -> None:
    pdf = _pdf_com_pixmap(_pixmap_meio_transparente(pymupdf.csCMYK, (0, 255, 255, 0)))

    (imagem,) = extrair_imagens(pdf)

    resultado = pymupdf.Pixmap(imagem.conteudo)
    assert imagem.extensao == "png"
    assert resultado.alpha == 1
    assert resultado.colorspace is not None
    assert resultado.colorspace.n == 3
    assert _alfa_esquerda_direita(imagem.conteudo) == (0, 255)


def test_mascara_com_tamanho_diferente_da_imagem_e_ajustada_sem_perder_a_imagem() -> None:
    cores = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 16, 16), False)
    cores.set_rect(cores.irect, (10, 20, 200))
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=cores)
    xref = pagina.get_images(full=True)[0][0]
    _anexar_mascara(
        documento,
        xref,
        "SMask",
        "<</Type/XObject/Subtype/Image/Width 4/Height 4/ColorSpace/DeviceGray/BitsPerComponent 8>>",
        bytes([0, 0, 255, 255] * 4),
    )
    pdf = documento.tobytes()
    documento.close()

    (imagem,) = extrair_imagens(pdf)

    assert imagem.extensao == "png"
    assert _alfa_esquerda_direita(imagem.conteudo) == (0, 255)


def _pdf_com_smask_de_largura(largura_mascara: int, alfa_da_coluna: Any) -> bytes:
    # Imagem 16x16 opaca; a máscara é quadrada, com `largura_mascara` px, e o alfa de cada
    # coluna vem de alfa_da_coluna(x, largura_mascara).
    cores = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 16, 16), False)
    cores.set_rect(cores.irect, (10, 20, 200))
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=cores)
    xref = pagina.get_images(full=True)[0][0]
    dados = bytes(
        alfa_da_coluna(x, largura_mascara)
        for _ in range(largura_mascara)
        for x in range(largura_mascara)
    )
    _anexar_mascara(
        documento,
        xref,
        "SMask",
        f"<</Type/XObject/Subtype/Image/Width {largura_mascara}/Height {largura_mascara}"
        "/ColorSpace/DeviceGray/BitsPerComponent 8>>",
        dados,
    )
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def _alfas_da_linha(conteudo_png: bytes) -> list[int]:
    pixmap = pymupdf.Pixmap(conteudo_png)
    return [pixmap.pixel(x, 0)[-1] for x in range(pixmap.width)]


@pytest.mark.parametrize("largura_mascara", [4, 32], ids=["menor", "maior"])
def test_borda_da_mascara_redimensionada_preserva_regioes_transparentes_e_opacas(
    largura_mascara: int,
) -> None:
    # Metade esquerda alfa 0, direita 255. A reamostragem suave (MuPDF) só pode misturar
    # valores perto da fronteira; longe dela o alfa precisa continuar exatamente 0 e 255, e a
    # transição não pode oscilar.
    pdf = _pdf_com_smask_de_largura(
        largura_mascara, lambda x, largura: 0 if x < largura // 2 else 255
    )

    (imagem,) = extrair_imagens(pdf)

    alfas = _alfas_da_linha(imagem.conteudo)
    assert len(alfas) == 16
    assert alfas[:4] == [0, 0, 0, 0]
    assert alfas[-4:] == [255, 255, 255, 255]
    assert alfas == sorted(alfas)


@pytest.mark.parametrize("largura_mascara", [4, 32], ids=["menor", "maior"])
def test_alfa_parcial_uniforme_e_preservado_quando_a_mascara_e_redimensionada(
    largura_mascara: int,
) -> None:
    pdf = _pdf_com_smask_de_largura(largura_mascara, lambda x, largura: 128)

    (imagem,) = extrair_imagens(pdf)

    assert set(_alfas_da_linha(imagem.conteudo)) == {128}


def test_mascara_maior_que_a_imagem_registra_aviso_e_a_menor_nao(
    caplog: pytest.LogCaptureFixture,
) -> None:
    maior = _pdf_com_smask_de_largura(32, lambda x, largura: 255)
    menor = _pdf_com_smask_de_largura(4, lambda x, largura: 255)

    with caplog.at_level(logging.WARNING, logger=extrator.__name__):
        extrair_imagens(menor)
        assert "resolução maior" not in caplog.text
        extrair_imagens(maior)

    assert "resolução maior" in caplog.text


def test_mascara_explicita_em_stream_e_composta_como_alfa() -> None:
    cores = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
    cores.set_rect(cores.irect, (0, 0, 255))
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=cores)
    xref = pagina.get_images(full=True)[0][0]
    # Stencil de 1 bit com Decode padrão: metade esquerda mascarada (bit 1), direita pintada.
    _anexar_mascara(
        documento,
        xref,
        "Mask",
        "<</Type/XObject/Subtype/Image/Width 8/Height 8/ImageMask true/BitsPerComponent 1>>",
        bytes([0xF0] * 8),
    )
    pdf = documento.tobytes()
    documento.close()

    (imagem,) = extrair_imagens(pdf)

    resultado = pymupdf.Pixmap(imagem.conteudo)
    assert imagem.extensao == "png"
    assert resultado.alpha == 1
    assert (resultado.pixel(0, 0)[-1], resultado.pixel(7, 0)[-1]) == (0, 255)


def test_mascara_por_chave_de_cor_mantem_a_transparencia_sem_reconstrucao() -> None:
    # /Mask em array (chave de cor) não aparece como smask; o próprio extract_image já aplica.
    cores = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
    cores.set_rect(cores.irect, (255, 255, 255))
    for x in range(4):
        for y in range(8):
            cores.set_pixel(x, y, (0, 0, 255))
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=cores)
    xref = pagina.get_images(full=True)[0][0]
    documento.xref_set_key(xref, "Mask", "[250 255 250 255 250 255]")
    pdf = documento.tobytes()
    documento.close()

    (imagem,) = extrair_imagens(pdf)

    resultado = pymupdf.Pixmap(imagem.conteudo)
    assert resultado.alpha == 1
    assert (resultado.pixel(0, 0)[-1], resultado.pixel(7, 0)[-1]) == (255, 0)


def test_jpeg_sem_mascara_preserva_os_bytes_originais() -> None:
    origem = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 16, 16), False)
    origem.set_rect(origem.irect, (10, 200, 10))
    jpeg = origem.tobytes("jpeg")
    documento = pymupdf.open()
    documento.new_page().insert_image(pymupdf.Rect(50, 50, 150, 150), stream=jpeg)
    pdf = documento.tobytes()
    documento.close()

    (imagem,) = extrair_imagens(pdf)

    assert imagem.extensao == "jpeg"
    assert imagem.conteudo == jpeg


def test_imagem_sem_mascara_nao_passa_pela_reconstrucao_de_alfa() -> None:
    with patch.object(extrator, "_compor_png_com_alfa") as compor:
        imagens = extrair_imagens(pdf_com_imagem())

    assert len(imagens) == 1
    compor.assert_not_called()


def test_xref_e_registrado_e_e_opcional_na_construcao() -> None:
    (imagem,) = extrair_imagens(pdf_com_imagem())

    assert isinstance(imagem.xref, int)
    assert ImagemExtraida(0, 0, b"x", "png").xref is None


def test_mesmo_xref_em_varias_paginas_mantem_todas_as_colocacoes_e_converte_uma_vez() -> None:
    pdf = _pdf_com_pixmap(_pixmap_meio_transparente(pymupdf.csRGB, (200, 30, 30)), paginas=3)
    chamadas: list[int] = []
    original = extrator._extrair_imagem_com_transparencia

    def contar(*argumentos: Any) -> tuple[bytes, str]:
        chamadas.append(argumentos[1])
        resultado: tuple[bytes, str] = original(*argumentos)
        return resultado

    with patch.object(extrator, "_extrair_imagem_com_transparencia", side_effect=contar):
        imagens = extrair_imagens(pdf)

    assert [imagem.numero_pagina for imagem in imagens] == [0, 1, 2]
    assert len({imagem.xref for imagem in imagens}) == 1
    assert len(chamadas) == 1
    assert all(_alfa_esquerda_direita(imagem.conteudo) == (0, 255) for imagem in imagens)


def test_falha_na_reconstrucao_mantem_a_imagem_sem_mascara_e_registra_aviso(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pdf = _pdf_com_pixmap(_pixmap_meio_transparente(pymupdf.csRGB, (200, 30, 30)))

    with (
        caplog.at_level(logging.WARNING, logger=extrator.__name__),
        patch.object(extrator, "_compor_png_com_alfa", side_effect=RuntimeError("segredo-xyz")),
    ):
        (imagem,) = extrair_imagens(pdf)

    assert len(imagem.conteudo) > 0
    assert imagem.extensao
    assert "RuntimeError" in caplog.text
    assert "segredo-xyz" not in caplog.text
    assert "página=1" in caplog.text


def test_mascara_de_imagem_de_1_bit_gera_aviso_de_cor_nao_preservada(
    caplog: pytest.LogCaptureFixture,
) -> None:
    documento = pymupdf.open()
    pagina = documento.new_page()
    base = pymupdf.Pixmap(pymupdf.csGRAY, (0, 0, 8, 8), False)
    base.set_rect(base.irect, (0,))
    pagina.insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=base)
    xref = pagina.get_images(full=True)[0][0]
    documento.update_object(
        xref,
        "<</Type/XObject/Subtype/Image/Width 8/Height 8/ImageMask true/BitsPerComponent 1>>",
    )
    documento.update_stream(xref, bytes([0xF0] * 8), compress=False)
    pdf = documento.tobytes()
    documento.close()

    with caplog.at_level(logging.WARNING, logger=extrator.__name__):
        imagens = extrair_imagens(pdf)

    assert len(imagens) == 1
    assert "máscara de 1 bit" in caplog.text


def test_mascara_de_imagem_isolada_cai_no_bitmap_cinza_opaco_sem_reconstruir_a_cor() -> None:
    # Trava a limitação conhecida: sem a cor de preenchimento da página, o stencil sai do
    # extract_image em preto e branco. Se a cor passar a ser reconstruída, este teste muda junto.
    documento = pymupdf.open()
    pagina = documento.new_page()
    base = pymupdf.Pixmap(pymupdf.csGRAY, (0, 0, 8, 8), False)
    base.set_rect(base.irect, (0,))
    pagina.insert_image(pymupdf.Rect(50, 50, 150, 150), pixmap=base)
    xref = pagina.get_images(full=True)[0][0]
    documento.update_object(
        xref,
        "<</Type/XObject/Subtype/Image/Width 8/Height 8/ImageMask true/BitsPerComponent 1>>",
    )
    documento.update_stream(xref, bytes([0xF0] * 8), compress=False)
    pdf = documento.tobytes()
    documento.close()

    (imagem,) = extrair_imagens(pdf)

    resultado = pymupdf.Pixmap(imagem.conteudo)
    assert imagem.extensao == "png"
    assert resultado.alpha == 0
    assert resultado.colorspace is not None
    assert resultado.colorspace.n == 1
    assert (resultado.pixel(0, 0)[0], resultado.pixel(7, 0)[0]) == (0, 255)


# Limites de consumo (páginas e pixels)


def _pdf_com_paginas(n: int) -> bytes:
    documento = pymupdf.open()
    for _ in range(n):
        documento.new_page().insert_text((72, 72), "texto", fontsize=12)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def _com_limites(monkeypatch: pytest.MonkeyPatch, **campos: int) -> None:
    configuracao = get_settings().model_copy(update=campos)
    monkeypatch.setattr(extrator, "get_settings", lambda: configuracao)


def test_pdf_com_paginas_acima_do_limite_e_recusado_na_extracao_de_texto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _com_limites(monkeypatch, pdf_paginas_maximas=3)
    with pytest.raises(ErroDePipeline, match="limite de 3 páginas"):
        extrair_markdown(_pdf_com_paginas(4))


def test_pdf_com_paginas_acima_do_limite_e_recusado_na_extracao_de_imagens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _com_limites(monkeypatch, pdf_paginas_maximas=3)
    with pytest.raises(ErroDePipeline, match="limite de 3 páginas"):
        extrair_imagens(_pdf_com_paginas(4))


def test_pdf_exatamente_no_limite_de_paginas_e_aceito(monkeypatch: pytest.MonkeyPatch) -> None:
    _com_limites(monkeypatch, pdf_paginas_maximas=3)
    assert "texto" in extrair_markdown(_pdf_com_paginas(3))


def test_limite_padrao_de_paginas_e_100() -> None:
    assert get_settings().pdf_paginas_maximas == 100
    assert contar_paginas(_pdf_com_paginas(2)) == 2
    assert contar_paginas(b"%PDF-1.7\nnao abre") is None


def test_imagem_acima_do_limite_de_pixels_e_descartada_sem_derrubar_o_material(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    conteudo = pdf_com_imagem()  # imagem de 8x8 = 64 pixels
    _com_limites(monkeypatch, pdf_pixels_maximos_por_imagem=63)
    with caplog.at_level("WARNING"):
        assert extrair_imagens(conteudo) == []
    assert "acima do limite de pixels" in caplog.text


def test_imagem_no_limite_de_pixels_e_extraida(monkeypatch: pytest.MonkeyPatch) -> None:
    _com_limites(monkeypatch, pdf_pixels_maximos_por_imagem=64)
    assert len(extrair_imagens(pdf_com_imagem())) == 1
