import re

# LaTeX inline não renderiza fora de um visualizador compatível; como o conteúdo
# final é lido como Markdown puro, os símbolos são convertidos para Unicode.
_SIMBOLOS = {
    r"\to": "→",
    r"\rightarrow": "→",
    r"\implies": "→",
    r"\gets": "←",
    r"\leftarrow": "←",
    r"\leftrightarrow": "↔",
    r"\Leftrightarrow": "⇔",
    r"\iff": "↔",
    r"\neg": "¬",
    r"\lnot": "¬",
    r"\land": "∧",
    r"\wedge": "∧",
    r"\lor": "∨",
    r"\vee": "∨",
    r"\oplus": "⊕",
    r"\therefore": "∴",
    r"\forall": "∀",
    r"\exists": "∃",
    r"\nexists": "∄",
    r"\in": "∈",
    r"\notin": "∉",
    r"\subset": "⊂",
    r"\subseteq": "⊆",
    r"\supset": "⊃",
    r"\supseteq": "⊇",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\emptyset": "∅",
    r"\infty": "∞",
    r"\equiv": "≡",
    r"\neq": "≠",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\times": "×",
    r"\cdot": "·",
    r"\cdots": "⋯",
    r"\dots": "…",
    r"\ldots": "…",
    r"\quad": "  ",
    r"\qquad": "    ",
    r"\,": " ",
    r"\;": " ",
    r"\!": "",
    r"\ ": " ",
}
_SIMBOLOS_ORDENADOS = sorted(_SIMBOLOS.items(), key=lambda item: -len(item[0]))

_COMANDOS_COM_CONTEUDO = [
    re.compile(r"\\text\{([^}]*)\}"),
    re.compile(r"\\textbf\{([^}]*)\}"),
    re.compile(r"\\textit\{([^}]*)\}"),
    re.compile(r"\\mathbf\{([^}]*)\}"),
]


def _converter_expressao(expressao: str) -> str:
    resultado = expressao
    for latex, unicode_equivalente in _SIMBOLOS_ORDENADOS:
        resultado = resultado.replace(latex, unicode_equivalente)
    for padrao in _COMANDOS_COM_CONTEUDO:
        resultado = padrao.sub(r"\1", resultado)
    resultado = re.sub(r"\\overline\{([^}]*)\}", r"¬\1", resultado)
    resultado = re.sub(r"\\bar\{([^}]*)\}", r"¬\1", resultado)
    resultado = re.sub(r" {2,}", " ", resultado)
    return resultado.strip()


def normalizar_markdown(conteudo: str) -> str:
    conteudo = re.sub(r"\$\$([^$]+?)\$\$", lambda m: _converter_expressao(m.group(1)), conteudo)
    conteudo = re.sub(r"\$([^$]+?)\$", lambda m: _converter_expressao(m.group(1)), conteudo)
    return conteudo
