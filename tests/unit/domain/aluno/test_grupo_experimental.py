from domain.aluno.grupo_experimental import GrupoExperimental


def test_conjunto_fechado_de_valores() -> None:
    assert {g.value for g in GrupoExperimental} == {"experimental", "controle"}
