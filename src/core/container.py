"""Ponto único de composição de dependências.

Na inicialização do processo, instancia as implementações concretas de
Infrastructure e as injeta nos casos de uso da Application.
"""


class Container:
    """Registro central de dependências, resolvidas na inicialização do processo."""
