from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from domain.aluno.grupo_experimental import GrupoExperimental


class AlunoCadastroRequest(BaseModel):
    nome: str
    email: EmailStr
    matricula: str


class AlunoAtualizacaoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str
    email: EmailStr


class AlunoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    email: str
    matricula: str
    data_cadastro: datetime
    grupo_experimental: GrupoExperimental
