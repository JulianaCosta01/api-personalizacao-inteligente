import pymupdf
import pytest
from fastapi import HTTPException

from presentation.api.routers.material import _exigir_limite_de_paginas


def _pdf(paginas: int) -> bytes:
    documento = pymupdf.open()
    for _ in range(paginas):
        documento.new_page()
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


async def test_pdf_com_paginas_acima_do_limite_e_recusado_com_400() -> None:
    with pytest.raises(HTTPException) as erro:
        await _exigir_limite_de_paginas(_pdf(4), limite=3)
    assert erro.value.status_code == 400
    assert erro.value.detail["code"] == "PDF_PAGINAS_EXCEDIDAS"  # type: ignore[index]


async def test_pdf_no_limite_passa() -> None:
    await _exigir_limite_de_paginas(_pdf(3), limite=3)


async def test_arquivo_que_nao_abre_segue_para_a_validacao_do_caso_de_uso() -> None:
    # Comportamento atual preservado: PDFs sintéticos que não abrem não são recusados aqui.
    await _exigir_limite_de_paginas(b"%PDF-1.7\nconteudo qualquer", limite=3)
