import struct
import zlib

# Validação estrutural de PNG/JPEG vindos de provedor externo, sem decodificar pixels.
# Barra arquivo truncado, dados anexados e bombas de descompressão antes de chegar ao PDF.
LADO_MAXIMO_EM_PIXELS = 8192
PIXELS_MAXIMOS = 40_000_000

_ASSINATURA_PNG = b"\x89PNG\r\n\x1a\n"
_ASSINATURA_JPEG = b"\xff\xd8\xff"

# tipo de cor do PNG -> (profundidades de bit permitidas, canais)
_PNG_TIPOS_DE_COR = {
    0: ({1, 2, 4, 8, 16}, 1),
    2: ({8, 16}, 3),
    3: ({1, 2, 4, 8}, 1),
    4: ({8, 16}, 2),
    6: ({8, 16}, 4),
}
_JPEG_SOF = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def estrutura_da_imagem_valida(conteudo: bytes) -> bool:
    try:
        if conteudo.startswith(_ASSINATURA_PNG):
            return _png_valido(conteudo)
        if conteudo.startswith(_ASSINATURA_JPEG):
            return _jpeg_valido(conteudo)
    except (struct.error, zlib.error, ValueError, IndexError):
        return False
    return False


def _dimensoes_validas(largura: int, altura: int) -> bool:
    return (
        0 < largura <= LADO_MAXIMO_EM_PIXELS
        and 0 < altura <= LADO_MAXIMO_EM_PIXELS
        and largura * altura <= PIXELS_MAXIMOS
    )


def _png_valido(dados: bytes) -> bool:
    posicao = len(_ASSINATURA_PNG)
    total = len(dados)
    primeiro = True
    cabecalho: tuple[int, int, int, int, int] | None = None
    tem_paleta = False
    idat = bytearray()
    terminou = False

    while posicao < total:
        if posicao + 8 > total:
            return False
        tamanho, tipo = struct.unpack(">I4s", dados[posicao : posicao + 8])
        if tamanho > 0x7FFFFFFF or not all(65 <= b <= 90 or 97 <= b <= 122 for b in tipo):
            return False
        inicio = posicao + 8
        fim = inicio + tamanho
        if fim + 4 > total:
            return False
        corpo = dados[inicio:fim]
        (crc,) = struct.unpack(">I", dados[fim : fim + 4])
        if zlib.crc32(tipo + corpo) & 0xFFFFFFFF != crc:
            return False
        posicao = fim + 4

        if primeiro:
            if tipo != b"IHDR" or tamanho != 13:
                return False
            largura, altura, profundidade, cor, compressao, filtro, entrelacado = struct.unpack(
                ">IIBBBBB", corpo
            )
            permitidas = _PNG_TIPOS_DE_COR.get(cor)
            if permitidas is None or profundidade not in permitidas[0]:
                return False
            if compressao != 0 or filtro != 0 or entrelacado not in (0, 1):
                return False
            if not _dimensoes_validas(largura, altura):
                return False
            cabecalho = (largura, altura, profundidade * permitidas[1], cor, entrelacado)
            primeiro = False
            continue
        if tipo == b"IHDR":
            return False
        if tipo == b"PLTE":
            tem_paleta = True
        elif tipo == b"IDAT":
            idat += corpo
        elif tipo == b"IEND":
            if tamanho != 0:
                return False
            terminou = True
            break

    if not terminou or posicao != total or cabecalho is None or not idat:
        return False
    largura, altura, bits_por_pixel, cor, entrelacado = cabecalho
    if cor == 3 and not tem_paleta:
        return False
    return _fluxo_idat_valido(bytes(idat), largura, altura, bits_por_pixel, entrelacado == 1)


def _fluxo_idat_valido(
    idat: bytes, largura: int, altura: int, bits_por_pixel: int, entrelacado: bool
) -> bool:
    # Descompressão limitada ao tamanho que a imagem declarada exige: impede bomba de
    # descompressão e confirma que o fluxo zlib está íntegro e completo.
    bytes_por_linha = (largura * bits_por_pixel + 7) // 8 + 1
    esperado = bytes_por_linha * altura
    limite = esperado + 8 * altura + 64 if entrelacado else esperado
    descompressor = zlib.decompressobj()
    saida = descompressor.decompress(idat, limite + 1)
    if len(saida) > limite or not descompressor.eof or descompressor.unused_data:
        return False
    return entrelacado or len(saida) == esperado


def _jpeg_valido(dados: bytes) -> bool:
    total = len(dados)
    posicao = 2
    achou_quadro = False
    achou_varredura = False

    while posicao < total:
        if dados[posicao] != 0xFF:
            return False
        while posicao < total and dados[posicao] == 0xFF:
            posicao += 1
        if posicao >= total:
            return False
        marcador = dados[posicao]
        posicao += 1

        if marcador == 0xD9:  # EOI
            return achou_quadro and achou_varredura and posicao == total
        if marcador == 0x00 or marcador == 0x01 or 0xD0 <= marcador <= 0xD8:
            if marcador == 0xD8:
                return False  # SOI repetido
            continue
        if posicao + 2 > total:
            return False
        (tamanho,) = struct.unpack(">H", dados[posicao : posicao + 2])
        if tamanho < 2 or posicao + tamanho > total:
            return False
        segmento = dados[posicao + 2 : posicao + tamanho]
        posicao += tamanho

        if marcador in _JPEG_SOF:
            if achou_quadro or len(segmento) < 6:
                return False
            _precisao, altura, largura, componentes = struct.unpack(">BHHB", segmento[:6])
            if not _dimensoes_validas(largura, altura) or not 1 <= componentes <= 4:
                return False
            if len(segmento) != 6 + 3 * componentes:
                return False
            achou_quadro = True
        elif marcador == 0xDA:  # SOS: segue a varredura codificada
            if not achou_quadro:
                return False
            achou_varredura = True
            while posicao < total:
                if dados[posicao] != 0xFF:
                    posicao += 1
                    continue
                if posicao + 1 >= total:
                    return False
                seguinte = dados[posicao + 1]
                if seguinte == 0x00 or 0xD0 <= seguinte <= 0xD7 or seguinte == 0xFF:
                    posicao += 2 if seguinte != 0xFF else 1
                    continue
                break
    return False
