from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from application.aluno.atualizar_aluno import AtualizarAlunoInput, AtualizarAlunoUseCase
from application.aluno.cadastrar_aluno import CadastrarAlunoInput, CadastrarAlunoUseCase
from application.aluno.consultar_aluno import ConsultarAlunoUseCase
from application.ports.aluno_repository import IAlunoRepository
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
from infrastructure.database.session import get_db_session
from presentation.api.dependencies import validar_token_servico
from presentation.api.schemas.aluno import (
    AlunoAtualizacaoRequest,
    AlunoCadastroRequest,
    AlunoResponse,
)

router = APIRouter(
    prefix="/api/v1/alunos", tags=["Aluno"], dependencies=[Depends(validar_token_servico)]
)


async def _repositorio_aluno(session: AsyncSession = Depends(get_db_session)) -> IAlunoRepository:
    return AlunoRepositorySQLAlchemy(session)


@router.post("", response_model=AlunoResponse)
async def cadastrar_aluno(
    dados: AlunoCadastroRequest,
    response: Response,
    repositorio: IAlunoRepository = Depends(_repositorio_aluno),
) -> AlunoResponse:
    resultado = await CadastrarAlunoUseCase(repositorio).executar(
        CadastrarAlunoInput(nome=dados.nome, email=dados.email, matricula=dados.matricula)
    )
    # Upsert por matricula (Documento 3, §4.1): 201 para cadastro novo, 200
    # quando o registro já existia e foi apenas retornado.
    response.status_code = status.HTTP_201_CREATED if resultado.criado else status.HTTP_200_OK
    return AlunoResponse.model_validate(resultado.aluno)


@router.get("/{id}", response_model=AlunoResponse)
async def consultar_aluno(
    id: UUID, repositorio: IAlunoRepository = Depends(_repositorio_aluno)
) -> AlunoResponse:
    aluno = await ConsultarAlunoUseCase(repositorio).executar(id)
    return AlunoResponse.model_validate(aluno)


@router.put("/{id}", response_model=AlunoResponse)
async def atualizar_aluno(
    id: UUID,
    dados: AlunoAtualizacaoRequest,
    repositorio: IAlunoRepository = Depends(_repositorio_aluno),
) -> AlunoResponse:
    aluno = await AtualizarAlunoUseCase(repositorio).executar(
        AtualizarAlunoInput(id=id, nome=dados.nome, email=dados.email)
    )
    return AlunoResponse.model_validate(aluno)
