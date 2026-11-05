"""Guarda: a integração com a OpenAI foi removida e não deve voltar sem decisão explícita."""

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[3]
_PADRAO = re.compile(r"openai", re.IGNORECASE)


def test_codigo_fonte_nao_referencia_openai() -> None:
    achados = [
        str(p.relative_to(_RAIZ))
        for p in (_RAIZ / "src").rglob("*.py")
        if _PADRAO.search(p.read_text(encoding="utf-8"))
    ]
    assert achados == []


def test_compose_e_exemplo_de_ambiente_nao_referenciam_openai() -> None:
    for nome in ("docker-compose.yml", ".env.example"):
        assert _PADRAO.search((_RAIZ / nome).read_text(encoding="utf-8")) is None, nome


def test_dependencias_nao_incluem_o_sdk_da_openai() -> None:
    for nome in ("requirements.txt", "pyproject.toml"):
        arquivo = _RAIZ / nome
        if arquivo.exists():
            assert _PADRAO.search(arquivo.read_text(encoding="utf-8")) is None, nome
