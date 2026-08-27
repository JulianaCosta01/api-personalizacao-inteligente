from enum import StrEnum


class StatusProcessamento(StrEnum):
    PENDENTE = "pendente"
    EM_PROCESSAMENTO = "em_processamento"
    CONCLUIDO = "concluido"
    ERRO = "erro"
