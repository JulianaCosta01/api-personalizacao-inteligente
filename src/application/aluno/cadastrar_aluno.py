import random
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from application.ports.aluno_repository import IAlunoRepository
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental


@dataclass
class CadastrarAlunoInput:
    nome: str
    email: str
    matricula: str


@dataclass
class CadastrarAlunoResultado:
    aluno: Aluno
    criado: bool


class CadastrarAlunoUseCase:
    def __init__(self, repositorio: IAlunoRepository) -> None:
        self._repositorio = repositorio

    async def executar(self, dados: CadastrarAlunoInput) -> CadastrarAlunoResultado:
        # Upsert por matricula (Documento 3, §2.5): aluno existente é retornado
        # como está, sem sortear grupo_experimental de novo nem tocar seus dados.
        existente = await self._repositorio.obter_por_matricula(dados.matricula)
        if existente is not None:
            return CadastrarAlunoResultado(aluno=existente, criado=False)

        aluno = Aluno(
            id=uuid4(),
            nome=dados.nome,
            email=dados.email,
            matricula=dados.matricula,
            grupo_experimental=random.choice(list(GrupoExperimental)),
            data_cadastro=datetime.now(UTC),
        )
        await self._repositorio.adicionar(aluno)
        return CadastrarAlunoResultado(aluno=aluno, criado=True)
