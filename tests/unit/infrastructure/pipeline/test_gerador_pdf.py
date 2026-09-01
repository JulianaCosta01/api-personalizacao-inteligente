from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from infrastructure.pipeline.gerador_pdf import gerar_pdf


def test_gera_pdf_valido_a_partir_de_markdown() -> None:
    pdf = gerar_pdf("# Título\n\nParágrafo de conteúdo adaptado.")

    assert pdf.startswith(b"%PDF-")


def test_gera_pdf_com_tabela_e_codigo() -> None:
    conteudo = "| A | B |\n| - | - |\n| 1 | 2 |\n\n```\ncodigo de exemplo\n```\n"

    pdf = gerar_pdf(conteudo)

    assert pdf.startswith(b"%PDF-")


def test_gera_pdf_com_titulos_e_formulas_normalizadas() -> None:
    # Fórmulas já chegam normalizadas para Unicode (infrastructure.pipeline.normalizador) —
    # gerar_pdf só precisa continuar aceitando texto comum, sem referência a recurso externo.
    conteudo = "## Lógica proposicional\n\nSe A → B e A, então B (∴ modus ponens).\n"

    pdf = gerar_pdf(conteudo)

    assert pdf.startswith(b"%PDF-")


@contextmanager
def _bloqueia_conexoes_de_rede() -> Iterator[None]:
    # Prova mais forte que "não deu erro": se o WeasyPrint tentasse abrir uma conexão real,
    # o teste falha aqui, em vez de depender de timing ou de DNS de fato falhar.
    def _levantar(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Nenhuma conexão de rede deveria ser aberta durante a geração do PDF.")

    with patch("socket.socket.connect", side_effect=_levantar):
        yield


def test_referencia_http_externa_e_bloqueada_sem_acessar_a_rede() -> None:
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto adaptado ![imagem](http://exemplo-externo.test/x.png) depois.")

    # PDF continua sendo gerado normalmente — a imagem bloqueada só não aparece.
    assert pdf.startswith(b"%PDF-")


def test_referencia_a_localhost_e_bloqueada_sem_acessar_a_rede() -> None:
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto adaptado ![imagem](http://127.0.0.1:8000/interno) depois.")

    assert pdf.startswith(b"%PDF-")


def test_referencia_a_ip_privado_e_bloqueada_sem_acessar_a_rede() -> None:
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto adaptado ![imagem](http://10.0.0.5/interno) depois.")

    assert pdf.startswith(b"%PDF-")


def test_referencia_a_metadata_endpoint_e_bloqueada_sem_acessar_a_rede() -> None:
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto adaptado ![imagem](http://169.254.169.254/latest/meta-data/) fim.")

    assert pdf.startswith(b"%PDF-")


def test_bloqueio_de_recurso_externo_nao_levanta_excecao_nem_vaza_detalhes() -> None:
    # O bloqueio é tratado internamente pelo WeasyPrint (recurso ausente, não
    # erro fatal) — gerar_pdf não deve propagar exceção nenhuma para esse caso.
    with _bloqueia_conexoes_de_rede():
        pdf = gerar_pdf("Texto ![imagem](http://exemplo-externo.test/segredo?token=abc) fim.")

    assert pdf.startswith(b"%PDF-")
