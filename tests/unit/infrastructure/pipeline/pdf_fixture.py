import pymupdf


def pdf_valido(texto: str = "Conteúdo de teste.") -> bytes:
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto, fontsize=12)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def pdf_com_imagem(texto: str = "Conteúdo de teste.") -> bytes:
    # Pixmap gerado pelo próprio PyMuPDF: evita depender de uma lib de imagem externa só para produzir um bitmap válido de teste.
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto, fontsize=12)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
    pixmap.set_rect(pixmap.irect, (255, 0, 0))
    pagina.insert_image(pymupdf.Rect(72, 100, 100, 128), pixmap=pixmap)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo
