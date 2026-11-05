import struct
import zlib

import pytest

from application.ports.estrutura_imagem import (
    LADO_MAXIMO_EM_PIXELS,
    estrutura_da_imagem_valida,
)
from application.ports.gerador_imagens import ImagemGerada
from domain.shared.exceptions import EntradaInvalidaError
from tests.unit.application.ports.imagens_fixture import _bloco_png, jpeg_valido, png_valido

_ASSINATURA = b"\x89PNG\r\n\x1a\n"


def _png_com(cabecalho: bytes, idat: bytes | None = None, *, fim: bool = True) -> bytes:
    if idat is None:
        idat = zlib.compress((b"\x00" + b"\x10\x20\x30" * 2) * 2)
    return (
        _ASSINATURA
        + _bloco_png(b"IHDR", cabecalho)
        + _bloco_png(b"IDAT", idat)
        + (_bloco_png(b"IEND", b"") if fim else b"")
    )


def test_png_e_jpeg_integros_sao_aceitos() -> None:
    assert estrutura_da_imagem_valida(png_valido())
    assert estrutura_da_imagem_valida(png_valido(17, 9))
    assert estrutura_da_imagem_valida(jpeg_valido())


# PNG


@pytest.mark.parametrize("corte", [9, 20, 33, 40, 50])
def test_png_truncado_e_rejeitado(corte: int) -> None:
    assert not estrutura_da_imagem_valida(png_valido()[:corte])


def test_png_so_com_assinatura_e_rejeitado() -> None:
    assert not estrutura_da_imagem_valida(_ASSINATURA + b"dados")


def test_png_com_crc_alterado_e_rejeitado() -> None:
    png = bytearray(png_valido())
    png[20] ^= 0xFF  # dentro do IHDR
    assert not estrutura_da_imagem_valida(bytes(png))


def test_png_com_dados_apos_o_iend_e_rejeitado() -> None:
    assert not estrutura_da_imagem_valida(png_valido() + b"<script>alert(1)</script>")


def test_png_sem_iend_e_rejeitado() -> None:
    assert not estrutura_da_imagem_valida(
        _png_com(struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0), fim=False)
    )


def test_png_sem_idat_e_rejeitado() -> None:
    cabecalho = _bloco_png(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
    assert not estrutura_da_imagem_valida(_ASSINATURA + cabecalho + _bloco_png(b"IEND", b""))


def test_png_sem_ihdr_primeiro_e_rejeitado() -> None:
    corpo = _bloco_png(b"IDAT", zlib.compress(b"x")) + _bloco_png(b"IEND", b"")
    assert not estrutura_da_imagem_valida(_ASSINATURA + corpo)


@pytest.mark.parametrize(
    "cabecalho",
    [
        struct.pack(">IIBBBBB", 0, 2, 8, 2, 0, 0, 0),
        struct.pack(">IIBBBBB", 2, 0, 8, 2, 0, 0, 0),
        struct.pack(">IIBBBBB", 2, 2, 7, 2, 0, 0, 0),
        struct.pack(">IIBBBBB", 2, 2, 8, 5, 0, 0, 0),
        struct.pack(">IIBBBBB", 2, 2, 8, 2, 1, 0, 0),
        struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 1, 0),
        struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 2),
        struct.pack(">IIBBBBB", 2, 2, 8, 3, 0, 0, 0),  # paleta obrigatória ausente
    ],
)
def test_png_com_cabecalho_invalido_e_rejeitado(cabecalho: bytes) -> None:
    assert not estrutura_da_imagem_valida(_png_com(cabecalho))


def test_png_com_dimensoes_acima_do_limite_e_rejeitado() -> None:
    cabecalho = struct.pack(">IIBBBBB", LADO_MAXIMO_EM_PIXELS + 1, 2, 8, 2, 0, 0, 0)
    assert not estrutura_da_imagem_valida(_png_com(cabecalho))
    cabecalho = struct.pack(">IIBBBBB", 8000, 8000, 8, 2, 0, 0, 0)  # 64 Mpx
    assert not estrutura_da_imagem_valida(_png_com(cabecalho))


def test_png_cujo_fluxo_nao_bate_com_as_dimensoes_e_rejeitado() -> None:
    cabecalho = struct.pack(">IIBBBBB", 50, 50, 8, 2, 0, 0, 0)
    assert not estrutura_da_imagem_valida(_png_com(cabecalho))  # dados de 2x2


def test_png_com_bomba_de_descompressao_e_rejeitado() -> None:
    bomba = zlib.compress(b"\x00" * 50_000_000)
    cabecalho = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    assert len(bomba) < 200_000
    assert not estrutura_da_imagem_valida(_png_com(cabecalho, bomba))


def test_png_com_fluxo_zlib_corrompido_e_rejeitado() -> None:
    cabecalho = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    assert not estrutura_da_imagem_valida(_png_com(cabecalho, b"nao-e-zlib"))


# JPEG


@pytest.mark.parametrize("corte", [3, 4, 10, 20, 30])
def test_jpeg_truncado_e_rejeitado(corte: int) -> None:
    assert not estrutura_da_imagem_valida(jpeg_valido()[:corte])


def test_jpeg_so_com_assinatura_e_rejeitado() -> None:
    assert not estrutura_da_imagem_valida(b"\xff\xd8\xff\xe0" + b"dados")


def test_jpeg_com_dados_apos_o_eoi_e_rejeitado() -> None:
    assert not estrutura_da_imagem_valida(jpeg_valido() + b"<script>")


def test_jpeg_sem_quadro_ou_sem_varredura_e_rejeitado() -> None:
    assert not estrutura_da_imagem_valida(b"\xff\xd8\xff\xe0\x00\x02\xff\xd9")


def test_jpeg_com_dimensoes_acima_do_limite_e_rejeitado() -> None:
    assert not estrutura_da_imagem_valida(jpeg_valido(LADO_MAXIMO_EM_PIXELS + 1, 2))
    assert not estrutura_da_imagem_valida(jpeg_valido(8000, 8000))
    assert not estrutura_da_imagem_valida(jpeg_valido(0, 2))


def test_jpeg_com_tamanho_de_segmento_incoerente_e_rejeitado() -> None:
    jpeg = bytearray(jpeg_valido())
    jpeg[5] = 0xFF  # tamanho do primeiro segmento maior que o arquivo
    assert not estrutura_da_imagem_valida(bytes(jpeg))


# Integração com ImagemGerada


@pytest.mark.parametrize(
    "conteudo",
    [
        b"\x89PNG\r\n\x1a\n" + b"dados",
        b"\xff\xd8\xff\xe0" + b"dados",
        png_valido()[:-5],
        png_valido() + b"x",
        jpeg_valido()[:-2],
    ],
)
def test_imagem_gerada_recusa_assinatura_valida_com_estrutura_invalida(conteudo: bytes) -> None:
    with pytest.raises(EntradaInvalidaError) as erro:
        ImagemGerada(conteudo, "alt")
    assert erro.value.code == "IMAGEM_GERADA_INVALIDA"


def test_imagem_gerada_aceita_imagens_integras() -> None:
    assert ImagemGerada(png_valido(), "alt").extensao == "png"
    assert ImagemGerada(jpeg_valido(), "alt").extensao == "jpeg"
