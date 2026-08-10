from application.aluno.cadastrar_aluno import CadastrarAlunoInput, CadastrarAlunoUseCase
from domain.aluno.grupo_experimental import GrupoExperimental

from .fakes import AlunoRepositorioFake


async def test_cadastra_novo_aluno_quando_matricula_nao_existe() -> None:
    repositorio = AlunoRepositorioFake()
    caso_de_uso = CadastrarAlunoUseCase(repositorio)
    dados = CadastrarAlunoInput(
        nome="Kristiano", email="kristiano@discente.ufma.br", matricula="123"
    )

    resultado = await caso_de_uso.executar(dados)

    assert resultado.criado is True
    assert resultado.aluno.matricula == "123"
    assert resultado.aluno.grupo_experimental in GrupoExperimental
    assert await repositorio.obter_por_id(resultado.aluno.id) == resultado.aluno


async def test_retorna_aluno_existente_quando_matricula_ja_cadastrada() -> None:
    repositorio = AlunoRepositorioFake()
    caso_de_uso = CadastrarAlunoUseCase(repositorio)
    primeiro = await caso_de_uso.executar(
        CadastrarAlunoInput(nome="Kristiano", email="kristiano@discente.ufma.br", matricula="123")
    )

    segundo = await caso_de_uso.executar(
        CadastrarAlunoInput(nome="Outro Nome", email="outro@discente.ufma.br", matricula="123")
    )

    assert segundo.criado is False
    assert segundo.aluno.id == primeiro.aluno.id
    assert segundo.aluno.nome == "Kristiano"
    assert segundo.aluno.grupo_experimental == primeiro.aluno.grupo_experimental
