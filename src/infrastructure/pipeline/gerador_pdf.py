import markdown
from weasyprint import HTML, URLFetcher

from infrastructure.pipeline.erros import ErroDePipeline

_EXTENSOES_MARKDOWN = ["tables", "fenced_code"]

# HTML vem de Markdown gerado pelo Gemini, não confiável para permitir busca de
# recursos externos pelo WeasyPrint (porta de SSRF); fetcher nega tudo.
_url_fetcher_sem_rede = URLFetcher(allowed_protocols=[])


def gerar_pdf(conteudo_markdown: str) -> bytes:
    try:
        html = markdown.markdown(conteudo_markdown, extensions=_EXTENSOES_MARKDOWN)
        return HTML(string=html, url_fetcher=_url_fetcher_sem_rede).write_pdf()
    except Exception as exc:
        raise ErroDePipeline("Falha ao gerar o PDF personalizado.") from exc
