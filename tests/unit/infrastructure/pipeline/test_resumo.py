from infrastructure.pipeline.resumo import extrair_resumo


def test_extrai_primeiro_paragrafo_nao_vazio() -> None:
    conteudo = "# Título\n\nEste é o primeiro parágrafo relevante.\n\nOutro parágrafo."

    assert extrair_resumo(conteudo) == "Este é o primeiro parágrafo relevante."


def test_remove_marcacao_basica_de_markdown() -> None:
    conteudo = "**Parágrafo** com `código` e _ênfase_."

    resultado = extrair_resumo(conteudo)

    assert "*" not in resultado
    assert "_" not in resultado
    assert "`" not in resultado


def test_trunca_paragrafo_muito_longo() -> None:
    conteudo = "x" * 1000

    resultado = extrair_resumo(conteudo, tamanho_maximo=100)

    assert len(resultado) == 101  # 100 caracteres + reticências
    assert resultado.endswith("…")


def test_conteudo_vazio_retorna_resumo_padrao() -> None:
    assert extrair_resumo("") == "Material personalizado gerado a partir do documento original."
