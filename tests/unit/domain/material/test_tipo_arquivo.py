from domain.material.tipo_arquivo import eh_pdf_valido


def test_conteudo_com_assinatura_pdf_e_valido() -> None:
    assert eh_pdf_valido(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nconteudo qualquer")


def test_conteudo_sem_assinatura_pdf_e_invalido() -> None:
    assert not eh_pdf_valido(b"MZ\x90\x00executavel disfarcado de pdf")


def test_conteudo_vazio_e_invalido() -> None:
    assert not eh_pdf_valido(b"")


def test_assinatura_fora_do_inicio_do_arquivo_nao_conta() -> None:
    assert not eh_pdf_valido(b"lixo antes %PDF-1.7")
