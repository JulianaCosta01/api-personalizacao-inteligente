import pymupdf
import pymupdf4llm

from core.config import get_settings
from domain.material.tipo_arquivo import eh_pdf_valido
from infrastructure.pipeline.erros import ErroDePipeline


def extrair_markdown(conteudo_pdf: bytes) -> str:
    # A extensão/Content-Type declarados no cadastro do Material não são
    # garantia de que os bytes obtidos do Storage ainda são um PDF válido —
    # a assinatura é checada de novo aqui, no ponto em que o conteúdo é lido.
    if not eh_pdf_valido(conteudo_pdf):
        raise ErroDePipeline("Conteúdo obtido do Storage não é um PDF válido.")
    # Mesmo teto usado no upload de Material Didático (Fase 4) — Settings é a
    # única fonte de verdade; aqui é reaproveitado como defesa em profundidade
    # contra documentos desproporcionalmente grandes vindos do Storage.
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
