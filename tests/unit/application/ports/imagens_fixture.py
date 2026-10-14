import struct
import zlib


def _bloco_png(tipo: bytes, corpo: bytes) -> bytes:
    return (
        struct.pack(">I", len(corpo))
        + tipo
        + corpo
        + struct.pack(">I", zlib.crc32(tipo + corpo) & 0xFFFFFFFF)
    )


def png_valido(largura: int = 2, altura: int = 2, tamanho_total: int | None = None) -> bytes:
    """PNG RGB 8 bits, estruturalmente íntegro. Com `tamanho_total`, acrescenta um bloco
    auxiliar (tEXt) de enchimento até atingir exatamente esse tamanho."""
    linha = b"\x00" + b"\x10\x20\x30" * largura
    cabecalho = _bloco_png(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0))
    dados = _bloco_png(b"IDAT", zlib.compress(linha * altura))
    fim = _bloco_png(b"IEND", b"")
    base = b"\x89PNG\r\n\x1a\n" + cabecalho
    if tamanho_total is None:
        return base + dados + fim
    sobra = tamanho_total - len(base + dados + fim)
    assert sobra >= 12, "tamanho_total pequeno demais"
    enchimento = _bloco_png(b"tEXt", b"k\x00" + b"0" * (sobra - 12 - 2))
    return base + enchimento + dados + fim


def jpeg_valido(largura: int = 2, altura: int = 2) -> bytes:
    """JPEG com a estrutura de segmentos íntegra (SOI, SOF0, SOS, varredura, EOI)."""
    quadro = struct.pack(">BHHB", 8, altura, largura, 1) + bytes([1, 0x11, 0])
    varredura = bytes([1, 1, 0x00, 0, 63, 0])
    return (
        b"\xff\xd8"
        + b"\xff\xc0"
        + struct.pack(">H", len(quadro) + 2)
        + quadro
        + b"\xff\xda"
        + struct.pack(">H", len(varredura) + 2)
        + varredura
        + b"\x12\x34\xff\x00\x56"
        + b"\xff\xd9"
    )
