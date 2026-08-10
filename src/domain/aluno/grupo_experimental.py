from enum import StrEnum


class GrupoExperimental(StrEnum):
    """Grupo do desenho experimental do PIBIC, sorteado uma única vez na criação do Aluno.

    Conjunto fechado por design (Documento 3, §2.6) — sem estratificação ou
    balanceamento por turma, e imutável após o cadastro.
    """

    EXPERIMENTAL = "experimental"
    CONTROLE = "controle"
