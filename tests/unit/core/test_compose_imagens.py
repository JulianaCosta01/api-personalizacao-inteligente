"""Guarda de regressão do docker-compose.yml para o recurso de imagens geradas por IA.

Lê o arquivo como texto (sem depender de YAML): confere que as credenciais dos provedores chegam só
ao Worker, como "chave sem valor" (o valor vem do .env, ignorado pelo Git), e que nada no Compose
liga o recurso.
"""

import re
from pathlib import Path

import pytest

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"
_VARIAVEIS_DO_WORKER = [
    "IMAGENS_GERADAS_HABILITADAS",
    "IMAGENS_PROVEDOR",
    "IMAGENS_MAX_POR_MATERIAL",
    "IMAGENS_TIMEOUT_TOTAL_SEGUNDOS",
    "IMAGENS_ORCAMENTO_TOTAL_SEGUNDOS",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_IMAGE_MODEL",
    "CLOUDFLARE_IMAGE_STEPS",
    "CLOUDFLARE_IMAGE_TIMEOUT_SEGUNDOS",
]


def _bloco_do_servico(nome: str) -> list[str]:
    linhas = _COMPOSE.read_text(encoding="utf-8").splitlines()
    inicio = next(i for i, linha in enumerate(linhas) if linha.rstrip() == f"  {nome}:")
    fim = len(linhas)
    for i in range(inicio + 1, len(linhas)):
        if re.match(r"^(  [A-Za-z_][\w-]*:\s*$|[A-Za-z_][\w-]*:)", linhas[i]):
            fim = i
            break
    return linhas[inicio:fim]


def _atribuicoes(bloco: list[str]) -> dict[str, str]:
    resultado: dict[str, str] = {}
    for linha in bloco:
        achado = re.match(r"^      ([A-Z][A-Z0-9_]*):\s*(.*)$", linha)
        if achado:
            resultado[achado.group(1)] = achado.group(2).strip()
    return resultado


@pytest.mark.parametrize("variavel", _VARIAVEIS_DO_WORKER)
def test_worker_recebe_a_variavel_sem_valor_fixo_no_compose(variavel: str) -> None:
    atribuicoes = _atribuicoes(_bloco_do_servico("worker"))
    assert variavel in atribuicoes
    # "Chave sem valor": o valor vem do .env/ambiente do host, nunca escrito no Compose.
    assert atribuicoes[variavel] == ""


def test_a_api_nao_recebe_nenhuma_variavel_de_imagens_nem_de_provedor() -> None:
    atribuicoes = _atribuicoes(_bloco_do_servico("api"))
    indevidas = [n for n in atribuicoes if re.match(r"(IMAGENS_|CLOUDFLARE_)", n)]
    assert indevidas == []


def test_compose_nao_liga_o_recurso_nem_traz_valores_de_credenciais() -> None:
    texto = _COMPOSE.read_text(encoding="utf-8")
    assert re.search(r"IMAGENS_GERADAS_HABILITADAS:[ \t]*\S", texto) is None
    assert re.search(r"CLOUDFLARE_API_TOKEN:[ \t]*\S", texto) is None


def test_worker_nao_usa_env_file() -> None:
    # Com env_file o contêiner receberia o .env inteiro, inclusive segredos que ele não usa.
    assert not any(linha.strip().startswith("env_file") for linha in _bloco_do_servico("worker"))
