from datetime import UTC, datetime
from uuid import uuid4

from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental


def _aluno() -> Aluno:
    return Aluno(
        id=uuid4(),
        nome="Kristiano Fernandes Plácido",
        email="kristiano@discente.ufma.br",
        matricula="2021045123",
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )


def test_atualizar_cadastro_altera_nome_e_email() -> None:
    aluno = _aluno()

    aluno.atualizar_cadastro(nome="Novo Nome", email="novo@discente.ufma.br")

    assert aluno.nome == "Novo Nome"
    assert aluno.email == "novo@discente.ufma.br"


def test_atualizar_cadastro_preserva_matricula_e_grupo_experimental() -> None:
    aluno = _aluno()

    aluno.atualizar_cadastro(nome="Novo Nome", email="novo@discente.ufma.br")

    assert aluno.matricula == "2021045123"
    assert aluno.grupo_experimental == GrupoExperimental.EXPERIMENTAL
