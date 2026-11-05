"""Hierarquia de exceções de domínio.

A tradução para HTTP fica em core.exceptions: esta camada não conhece HTTP.
"""

from typing import Any


class DomainError(Exception):
    """Base da hierarquia. Não é lançada diretamente, apenas suas subclasses."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class RecursoNaoEncontradoError(DomainError):
    """Recurso referenciado por id não existe. Mapeada para 404 na API."""


class EntradaInvalidaError(DomainError):
    """Entrada fornecida pelo cliente não tem um formato aceitável (ex.: arquivo que não é
    um PDF de verdade). Diferente de RegraDeNegocioVioladaError: aqui o problema é o dado em
    si, não uma regra de negócio sobre um dado bem formado. Mapeada para 400."""


class RegraDeNegocioVioladaError(DomainError):
    """Corpo da requisição válido, mas em desacordo com uma regra de negócio. Mapeada para 422."""


class ConflitoDeEstadoError(DomainError):
    """Recurso existe, mas seu estado atual impede a operação solicitada. Mapeada para 409."""
