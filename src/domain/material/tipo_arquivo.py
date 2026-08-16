from enum import StrEnum

_ASSINATURA_PDF = b"%PDF-"


class TipoArquivo(StrEnum):
    PDF = "application/pdf"


def eh_pdf_valido(conteudo: bytes) -> bool:
    # Extensão e Content-Type vêm do cliente e não são confiáveis; a assinatura
    # nos bytes é o único jeito de confirmar que o arquivo é mesmo um PDF.
    return conteudo.startswith(_ASSINATURA_PDF)
