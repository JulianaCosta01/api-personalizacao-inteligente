import markdown
from weasyprint import HTML, URLFetcher

from infrastructure.pipeline.erros import ErroDePipeline

_EXTENSOES_MARKDOWN = ["tables", "fenced_code"]

# O HTML renderizado vem de Markdown gerado pelo Gemini (Etapa 2) — conteúdo
# que, apesar das defesas de prompt injection na system_instruction, não é
# confiável o bastante para permitir que o WeasyPrint busque recursos
# externos (<img src="...">, @import etc.) durante a geração do PDF: isso
# seria uma porta de SSRF a partir do processo do Worker. Texto, títulos,
# tabelas, código e fórmulas normalizadas não dependem de nenhum recurso
# externo — por isso o fetcher nega todos os protocolos (allowlist vazia),
# em vez de tentar filtrar por domínio/IP, o que seria contornável.
_url_fetcher_sem_rede = URLFetcher(allowed_protocols=[])


def gerar_pdf(conteudo_markdown: str) -> bytes:
    try:
        html = markdown.markdown(conteudo_markdown, extensions=_EXTENSOES_MARKDOWN)
        return HTML(string=html, url_fetcher=_url_fetcher_sem_rede).write_pdf()
    except Exception as exc:
        raise ErroDePipeline("Falha ao gerar o PDF personalizado.") from exc
