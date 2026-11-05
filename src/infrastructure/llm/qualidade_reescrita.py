"""Heurísticas locais e baratas para detectar uma reescrita insuficiente.

Não provam qualidade, só decidem se vale UMA chamada extra. Fidelidade semântica não é
avaliada aqui.
"""

import re
import unicodedata
from collections import Counter

TAMANHO_MAXIMO_RESPOSTA_REESCRITA = 200_000
# Abaixo disto o original é curto demais para exigir proporção ou cobertura de conceitos.
TAMANHO_MINIMO_PARA_AVALIAR = 600
# Só originais deste tamanho para cima justificam exigir exemplos, prática e erros comuns.
TAMANHO_MINIMO_PARA_EXIGIR_ELEMENTOS = 2000
# Fração mínima dos conceitos essenciais do original que a resposta precisa manter.
COBERTURA_MINIMA_DE_CONCEITOS = 0.6
# Menos termos que isto não é sinal suficiente para julgar a cobertura.
MINIMO_DE_TERMOS_PARA_JULGAR = 5
_MAXIMO_DE_TERMOS = 40

_TITULO = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_NEGRITO = re.compile(r"\*\*([^*\n]{3,60})\*\*")
_PALAVRA_LONGA = re.compile(r"[^\W\d_]{7,}")
_PALAVRA = re.compile(r"[^\W\d_]{4,}")

_EXEMPLOS = re.compile(r"exemplo")
_PRATICA = re.compile(r"exercicio|atividade|questao|questoes|pratique|resolva")
_ERROS = re.compile(r"erro|equivoco|armadilha|engano|confus")


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sem_acento.casefold()).strip()


def _termos_essenciais(original: str) -> list[str]:
    """Títulos, termos em negrito e as palavras longas mais frequentes do original."""
    termos: list[str] = []
    for achado in _TITULO.findall(original) + _NEGRITO.findall(original):
        limpo = _normalizar(re.sub(r"[*_`#]", "", achado))
        if 3 <= len(limpo) <= 80:
            termos.append(limpo)
    frequencia = Counter(_normalizar(p) for p in _PALAVRA_LONGA.findall(original))
    termos.extend(p for p, n in frequencia.most_common(15) if n >= 3)
    unicos = list(dict.fromkeys(termos))  # sem repetir, mantendo a ordem
    return unicos[:_MAXIMO_DE_TERMOS]


def _termo_preservado(termo: str, resposta_normalizada: str) -> bool:
    if termo in resposta_normalizada:
        return True
    palavras = _PALAVRA.findall(termo)
    if len(palavras) < 2:
        return False
    # Título reescrito de outro jeito: basta a maioria das palavras significativas continuar lá.
    presentes = sum(1 for p in palavras if p in resposta_normalizada)
    return presentes * 2 >= len(palavras)


def cobertura_de_conceitos(original: str, resposta: str) -> float | None:
    """Fração dos conceitos essenciais do original presentes na resposta; `None` = sem sinal."""
    termos = _termos_essenciais(original)
    if len(termos) < MINIMO_DE_TERMOS_PARA_JULGAR:
        return None
    resposta_normalizada = _normalizar(resposta)
    preservados = sum(1 for t in termos if _termo_preservado(t, resposta_normalizada))
    return preservados / len(termos)


def elementos_pedagogicos_ausentes(resposta: str) -> list[str]:
    """Quais dos três elementos (exemplos, prática, erros comuns) NÃO aparecem na resposta."""
    texto = _normalizar(resposta)
    presentes = {
        "exemplos": bool(_EXEMPLOS.search(texto)),
        "pratica": bool(_PRATICA.search(texto)),
        "erros_comuns": bool(_ERROS.search(texto)),
    }
    return [nome for nome, ok in presentes.items() if not ok]


def motivo_de_insuficiencia(
    original: str, resposta: str, status: object, proporcao_minima: float
) -> str | None:
    """`None` = suficiente; senão, um código curto do motivo (nunca o texto).

    Ordem: truncada (sempre insuficiente) → tamanho em relação ao original → conceitos do original
    perdidos → ausência de elementos pedagógicos (exige 2 de 3 entre exemplos, prática e erros
    comuns, e só em originais longos, onde esses elementos são pertinentes).
    """
    if status == "incomplete":
        return "resposta_incompleta"
    if len(original) < TAMANHO_MINIMO_PARA_AVALIAR:
        return None
    minimo = int(len(original) * proporcao_minima)
    # Um mínimo que passaria do teto de resposta aceito é inalcançável: não se exige o impossível.
    if minimo < TAMANHO_MAXIMO_RESPOSTA_REESCRITA and len(resposta) < minimo:
        return "resposta_curta"
    cobertura = cobertura_de_conceitos(original, resposta)
    if cobertura is not None and cobertura < COBERTURA_MINIMA_DE_CONCEITOS:
        return "conceitos_ausentes"
    if (
        len(original) >= TAMANHO_MINIMO_PARA_EXIGIR_ELEMENTOS
        and len(elementos_pedagogicos_ausentes(resposta)) >= 2
    ):
        return "sem_elementos_pedagogicos"
    return None
