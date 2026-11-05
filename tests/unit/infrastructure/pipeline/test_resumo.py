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


def test_resumo_nao_carrega_marcacao_html() -> None:
    from infrastructure.pipeline.resumo import extrair_resumo

    assert extrair_resumo("# T\n\n<img src=x onerror=alert(1)>Texto seguro\n") == "Texto seguro"
    assert extrair_resumo("<script>alert(1)</script>Olá") == "alert(1)Olá"
    assert extrair_resumo("Veja <b>isto</b> agora") == "Veja isto agora"
    assert extrair_resumo("<!-- c -->Comentário removido") == "Comentário removido"


def test_resumo_remove_tag_que_nao_fecha_e_pula_paragrafo_so_de_marcacao() -> None:
    from infrastructure.pipeline.resumo import extrair_resumo

    assert "<" not in extrair_resumo("Antes <img src=x onerror=alert(1)")
    assert extrair_resumo("<div></div>\n\nSegundo parágrafo.") == "Segundo parágrafo."


def test_resumo_preserva_sinal_de_menor_em_texto_comum() -> None:
    from infrastructure.pipeline.resumo import extrair_resumo

    assert extrair_resumo("Se x < y e y > z então vale.") == "Se x < y e y > z então vale."
