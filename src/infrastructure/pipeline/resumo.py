import re

_TAMANHO_MAXIMO = 500


def extrair_resumo(conteudo_markdown: str, tamanho_maximo: int = _TAMANHO_MAXIMO) -> str:
    # Resumo derivado do próprio conteúdo adaptado, sem uma segunda chamada ao
    # modelo: primeiro parágrafo não vazio, com marcação básica removida.
    for paragrafo in conteudo_markdown.splitlines():
        texto = paragrafo.strip()
        if not texto or texto.startswith("#"):
            continue
        texto = re.sub(r"[*_`]", "", texto)
        if not texto:
            continue
        if len(texto) > tamanho_maximo:
            return texto[:tamanho_maximo].rstrip() + "…"
        return texto
    return "Material personalizado gerado a partir do documento original."
