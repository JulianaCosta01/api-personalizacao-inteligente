from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from domain.aluno.grupo_experimental import GrupoExperimental

# Limites iguais aos das colunas (aluno.nome 255, aluno.email 254, aluno.matricula 20): um valor
# maior viraria erro de banco (500) em vez de uma resposta 400 clara.
NomeDoAluno = Annotated[str, Field(min_length=1, max_length=255)]
EmailDoAluno = Annotated[EmailStr, Field(max_length=254)]
MatriculaDoAluno = Annotated[str, Field(min_length=1, max_length=20)]


class AlunoCadastroRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: NomeDoAluno
    email: EmailDoAluno
    matricula: MatriculaDoAluno


class AlunoAtualizacaoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: NomeDoAluno
    email: EmailDoAluno


class AlunoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    email: str
    matricula: str
    data_cadastro: datetime
    grupo_experimental: GrupoExperimental


class AlunoExistenteResponse(BaseModel):
    """Resposta de POST /alunos quando a matrícula já estava cadastrada.

    Só o identificador e o grupo: quem chama a partir de uma matrícula não recebe nome nem
    e-mail de um cadastro anterior (evita usar o endpoint para consultar dados pessoais por
    tentativa de matrícula). Os dados completos continuam em GET /alunos/{id}.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    grupo_experimental: GrupoExperimental
