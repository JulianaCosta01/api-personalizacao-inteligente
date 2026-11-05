import re

_TAMANHO_MAXIMO = 500

# Marcação HTML de abertura, fechamento, comentário ou declaração (`<` seguido de letra, `!`, `/`
# ou `?`), inclusive a que não chega a fechar com `>`. Um `<` isolado ("a < b") não é tocado.
_PADRAO_MARCACAO_HTML = re.compile(r"<[A-Za-z!/?][^>]*>?")


def extrair_resumo(conteudo_markdown: str, tamanho_maximo: int = _TAMANHO_MAXIMO) -> str:
    # Resumo derivado do próprio conteúdo adaptado, sem uma segunda chamada ao
    # modelo: primeiro parágrafo não vazio, com marcação básica removida.
    for paragrafo in conteudo_markdown.splitlines():
        texto = paragrafo.strip()
        if not texto or texto.startswith("#"):
            continue
        # O resumo é devolvido pela API como texto puro: tags vindas do conteúdo (que o modelo pode
        # reproduzir do documento original) não podem chegar ao cliente como marcação.
        texto = _PADRAO_MARCACAO_HTML.sub("", texto)
        texto = re.sub(r"[*_`]", "", texto).strip()
        if not texto:
            continue
        if len(texto) > tamanho_maximo:
            return texto[:tamanho_maximo].rstrip() + "…"
        return texto
    return "Material personalizado gerado a partir do documento original."
