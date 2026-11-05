import logging
from dataclasses import dataclass

import pymupdf
import pymupdf4llm

from core.config import get_settings
from domain.material.tipo_arquivo import eh_pdf_valido
from infrastructure.pipeline.erros import ErroDePipeline

logger = logging.getLogger(__name__)


def contar_paginas(conteudo_pdf: bytes) -> int | None:
    """Número de páginas do PDF, ou None se ele não puder ser aberto (a falha de abertura é
    tratada por quem de fato processa o arquivo, não aqui)."""
    try:
        documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    except Exception:
        return None
    try:
        return int(documento.page_count)
    finally:
        documento.close()


def _exigir_limite_de_paginas(documento: pymupdf.Document) -> None:
    limite = get_settings().pdf_paginas_maximas
    if documento.page_count > limite:
        raise ErroDePipeline(f"O PDF excede o limite de {limite} páginas aceito pelo pipeline.")


def extrair_markdown(conteudo_pdf: bytes) -> str:
    # Extensão/Content-Type declarados no cadastro não garantem que os bytes do Storage
    # ainda são um PDF válido (a assinatura é checada de novo aqui)
    if not eh_pdf_valido(conteudo_pdf):
        raise ErroDePipeline("Conteúdo obtido do Storage não é um PDF válido.")
    # Mesmo teto do upload de Material Didático, reaproveitado como defesa em
    # profundidade contra PDFs grandes do Storage
    if len(conteudo_pdf) > get_settings().material_tamanho_maximo_bytes:
        raise ErroDePipeline("Conteúdo do PDF excede o tamanho máximo aceito pelo pipeline.")

    try:
        documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    except Exception as exc:
        raise ErroDePipeline("Falha ao abrir o PDF para extração.") from exc

    try:
        _exigir_limite_de_paginas(documento)
        markdown = pymupdf4llm.to_markdown(documento)
    except ErroDePipeline:
        raise
    except Exception as exc:
        raise ErroDePipeline("Falha ao extrair o conteúdo do PDF.") from exc
    finally:
        documento.close()

    return markdown


@dataclass
class ImagemExtraida:
    """Uma imagem extraída do PDF original, com os bytes preservados sem reprocessamento."""

    numero_pagina: int
    indice_na_pagina: int
    conteudo: bytes
    extensao: str
    xref: int | None = None


def _eh_mascara_de_imagem(documento: pymupdf.Document, xref: int) -> bool:
    try:
        return documento.xref_get_key(xref, "ImageMask")[1] == "true"
    except Exception:
        return False


def _compor_png_com_alfa(documento: pymupdf.Document, xref: int, xref_mascara: int) -> bytes:
    # Pixmap(documento, xref) devolve só as cores; o canal alfa vem da máscara (/SMask ou
    # /Mask em stream, ambas reportadas por get_images no mesmo campo) e precisa ser recomposto.
    cores = pymupdf.Pixmap(documento, xref)
    mascara = pymupdf.Pixmap(documento, xref_mascara)
    # PNG só aceita Gray/RGB: CMYK com máscara compõe, mas não serializa sem converter antes.
    if cores.colorspace is not None and cores.colorspace.n not in (1, 3):
        cores = pymupdf.Pixmap(pymupdf.csRGB, cores)
    # A composição exige máscara e cores do mesmo tamanho. A máscara é ajustada às cores
    # (e não o contrário) para não reamostrar a imagem original.
    if (mascara.width, mascara.height) != (cores.width, cores.height):
        if mascara.width * mascara.height > cores.width * cores.height:
            logger.warning(
                "Máscara de transparência com resolução maior que a imagem; reduzida ao tamanho "
                "da imagem (xref=%d).",
                xref,
            )
        mascara = pymupdf.Pixmap(mascara, cores.width, cores.height)
    return pymupdf.Pixmap(cores, mascara).tobytes("png")


def _extrair_imagem_com_transparencia(
    documento: pymupdf.Document, xref: int, xref_mascara: int, numero_pagina: int
) -> tuple[bytes, str]:
    # extract_image devolve os bytes originais (JPEG sem recompressão, por exemplo), mas sem a
    # máscara. Só quando existe máscara o resultado é recomposto como PNG com alfa.
    # Chave de cor (/Mask em array) já é aplicada pelo próprio extract_image.
    imagem_base = documento.extract_image(xref)
    conteudo: bytes = imagem_base["image"]
    extensao: str = imagem_base["ext"]

    # Limitação conhecida: ImageMask isolado sai em preto e branco (fallback de extract_image),
    # porque a cor de preenchimento da página não é lida aqui.
    if _eh_mascara_de_imagem(documento, xref):
        logger.warning(
            "Imagem é uma máscara de 1 bit (stencil); a cor de preenchimento do original não é "
            "reconstruída e o bitmap extraído é cinza opaco, sem a aparência do original "
            "(página=%d, xref=%d).",
            numero_pagina + 1,
            xref,
        )
    if not xref_mascara:
        return conteudo, extensao

    try:
        return _compor_png_com_alfa(documento, xref, xref_mascara), "png"
    except Exception as exc:
        # Melhor resultado disponível: a imagem sem transparência, em vez de perdê-la.
        logger.warning(
            "Falha ao reconstruir a transparência da imagem; mantida sem máscara "
            "(página=%d, xref=%d, erro=%s).",
            numero_pagina + 1,
            xref,
            type(exc).__name__,
        )
        return conteudo, extensao


def extrair_imagens(conteudo_pdf: bytes) -> list[ImagemExtraida]:
    # Mesma validação de extrair_markdown, duplicada de propósito: as duas funções
    # extraem partes diferentes do mesmo PDF e não devem depender uma da outra.
    if not eh_pdf_valido(conteudo_pdf):
        raise ErroDePipeline("Conteúdo obtido do Storage não é um PDF válido.")
    if len(conteudo_pdf) > get_settings().material_tamanho_maximo_bytes:
        raise ErroDePipeline("Conteúdo do PDF excede o tamanho máximo aceito pelo pipeline.")

    try:
        documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    except Exception as exc:
        raise ErroDePipeline("Falha ao abrir o PDF para extração.") from exc

    try:
        _exigir_limite_de_paginas(documento)
        limite_de_pixels = get_settings().pdf_pixels_maximos_por_imagem
        imagens: list[ImagemExtraida] = []
        # O cache evita converter de novo um xref reaproveitado; cada colocação continua
        # gerando a sua própria entrada.
        convertidas: dict[int, tuple[bytes, str]] = {}
        for numero_pagina in range(documento.page_count):
            pagina = documento[numero_pagina]
            for indice, referencia in enumerate(pagina.get_images(full=True)):
                xref = referencia[0]
                # Largura e altura declaradas no PDF (campos 2 e 3), lidas sem decodificar a
                # imagem: uma imagem acima do limite é descartada antes de qualquer conversão.
                if int(referencia[2]) * int(referencia[3]) > limite_de_pixels:
                    logger.warning(
                        "Imagem descartada: acima do limite de pixels (página=%d, xref=%d).",
                        numero_pagina + 1,
                        xref,
                    )
                    continue
                if xref not in convertidas:
                    convertidas[xref] = _extrair_imagem_com_transparencia(
                        documento, xref, referencia[1], numero_pagina
                    )
                conteudo, extensao = convertidas[xref]
                imagens.append(
                    ImagemExtraida(
                        numero_pagina=numero_pagina,
                        indice_na_pagina=indice,
                        conteudo=conteudo,
                        extensao=extensao,
                        xref=xref,
                    )
                )
    except ErroDePipeline:
        raise
    except Exception as exc:
        raise ErroDePipeline("Falha ao extrair imagens do PDF.") from exc
    finally:
        documento.close()

    return imagens
