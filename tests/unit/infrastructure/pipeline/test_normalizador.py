from infrastructure.pipeline.normalizador import normalizar_markdown


def test_converte_simbolos_latex_inline_para_unicode() -> None:
    resultado = normalizar_markdown("Se $A \\to B$ então $A \\in C$.")

    assert "→" in resultado
    assert "∈" in resultado
    assert "\\to" not in resultado


def test_remove_comandos_text_preservando_conteudo() -> None:
    resultado = normalizar_markdown("O valor de $\\text{x}$ é importante.")

    assert "x" in resultado
    assert "\\text" not in resultado


def test_texto_sem_latex_permanece_inalterado() -> None:
    texto = "Parágrafo comum, sem nenhuma notação matemática."

    assert normalizar_markdown(texto) == texto
