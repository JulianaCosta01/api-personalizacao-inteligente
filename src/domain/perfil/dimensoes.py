from enum import StrEnum


class EstiloProcessamento(StrEnum):
    ATIVO = "Ativo"
    REFLEXIVO = "Reflexivo"


class Percepcao(StrEnum):
    SENSORIAL = "Sensorial"
    INTUITIVO = "Intuitivo"


class Entrada(StrEnum):
    VISUAL = "Visual"
    VERBAL = "Verbal"


class Compreensao(StrEnum):
    SEQUENCIAL = "Sequencial"
    GLOBAL = "Global"
