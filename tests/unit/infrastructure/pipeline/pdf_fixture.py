import pymupdf


def pdf_valido(texto: str = "Conteúdo de teste.") -> bytes:
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto, fontsize=12)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo
