import pymupdf
import pymupdf4llm

from core.config import get_settings
from domain.material.tipo_arquivo import eh_pdf_valido
from infrastructure.pipeline.erros import ErroDePipeline


def extrair_markdown(conteudo_pdf: bytes) -> str:
    # Extensão/Content-Type declarados no cadastro não garantem que os bytes
    # do Storage ainda são um PDF válido (a assinatura é checada de novo aqui).
    if not eh_pdf_valido(conteudo_pdf):
        raise ErroDePipeline("Conteúdo obtido do Storage não é um PDF válido.")
    # Mesmo teto do upload de Material Didático, reaproveitado como defesa em
    # profundidade contra PDFs grandes do Storage.
    if len(conteudo_pdf) > get_settings().material_tamanho_maximo_bytes:
        raise ErroDePipeline("Conteúdo do PDF excede o tamanho máximo aceito pelo pipeline.")

    try:
        documento = pymupdf.open(stream=conteudo_pdf, filetype="pdf")
    except Exception as exc:
        raise ErroDePipeline("Falha ao abrir o PDF para extração.") from exc

    try:
        markdown = pymupdf4llm.to_markdown(documento)
    except Exception as exc:
        raise ErroDePipeline("Falha ao extrair o conteúdo do PDF.") from exc
    finally:
        documento.close()

    return markdown
