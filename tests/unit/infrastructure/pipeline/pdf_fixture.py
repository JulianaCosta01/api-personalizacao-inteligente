import pymupdf


def pdf_valido(texto: str = "Conteúdo de teste.") -> bytes:
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto, fontsize=12)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def png_sintetico(largura: int, altura: int, cor: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, largura, altura), False)
    pixmap.set_rect(pixmap.irect, cor)
    return pixmap.tobytes("png")


def pdf_com_imagem(texto: str = "Conteúdo de teste.") -> bytes:
    # Pixmap gerado pelo próprio PyMuPDF: evita depender de uma lib de imagem externa
    #  só para produzir um bitmap válido de teste
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto, fontsize=12)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
    pixmap.set_rect(pixmap.irect, (255, 0, 0))
    pagina.insert_image(pymupdf.Rect(72, 100, 100, 128), pixmap=pixmap)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def pdf_com_imagem_repetida(paginas: int = 3, texto: str = "Conteúdo de teste.") -> bytes:
    # O mesmo Pixmap inserido em várias páginas reaproveita um único objeto (xref) no PDF,
    # como acontece com um logotipo repetido em materiais reais.
    documento = pymupdf.open()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
    pixmap.set_rect(pixmap.irect, (255, 0, 0))
    for _ in range(paginas):
        pagina = documento.new_page()
        pagina.insert_text((72, 72), texto, fontsize=12)
        pagina.insert_image(pymupdf.Rect(72, 100, 100, 128), pixmap=pixmap)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def pdf_com_duas_imagens(texto: str = "Conteúdo de teste.") -> bytes:
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto, fontsize=12)

    pixmap_vermelho = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
    pixmap_vermelho.set_rect(pixmap_vermelho.irect, (255, 0, 0))
    pagina.insert_image(pymupdf.Rect(72, 100, 100, 128), pixmap=pixmap_vermelho)

    pixmap_azul = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
    pixmap_azul.set_rect(pixmap_azul.irect, (0, 0, 255))
    pagina.insert_image(pymupdf.Rect(150, 100, 178, 128), pixmap=pixmap_azul)

    conteudo = documento.tobytes()
    documento.close()
    return conteudo
