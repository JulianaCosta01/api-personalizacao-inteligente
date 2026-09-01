from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from application.processamento.processar_personalizacao import ProcessarPersonalizacaoUseCase
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy
from infrastructure.database.material_personalizado.material_personalizado_repository import (
    MaterialPersonalizadoRepositorySQLAlchemy,
)
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from tests.unit.application.material.fakes import ObjectStorageFake
from tests.unit.application.perfil.fakes import LLMFake


async def _cenario(session: AsyncSession) -> tuple[Processamento, MaterialDidatico]:
    aluno = Aluno(
        id=uuid4(),
        nome="Kristiano Fernandes Plácido",
        email=f"{uuid4()}@discente.ufma.br",
        matricula=str(uuid4())[:20],
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )
    await AlunoRepositorySQLAlchemy(session).adicionar(aluno)

    material = MaterialDidatico(
        id=uuid4(),
        titulo="Introdução a Grafos",
        nome_arquivo=f"{uuid4()}.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage=f"materiais/{uuid4()}.pdf",
        versao=1,
        data_upload=datetime.now(UTC),
    )
    await MaterialRepositorySQLAlchemy(session).adicionar(material)

    perfil = Perfil(
        id=uuid4(),
        aluno_id=aluno.id,
        estilo_processamento=EstiloProcessamento.ATIVO,
        percepcao=Percepcao.SENSORIAL,
        entrada=Entrada.VISUAL,
        compreensao=Compreensao.SEQUENCIAL,
        descricao_llm=None,
        data_atualizacao=datetime.now(UTC),
    )
    await PerfilRepositorySQLAlchemy(session).adicionar(perfil)

    processamento = Processamento(
        id=uuid4(),
        aluno_id=aluno.id,
        material_didatico_id=material.id,
        perfil_id=perfil.id,
        status=StatusProcessamento.EM_PROCESSAMENTO,
        modelo_ia=None,
        data_criacao=datetime.now(UTC),
        inicio=datetime.now(UTC),
        fim=None,
        erro=None,
    )
    await ProcessamentoRepositorySQLAlchemy(session).adicionar(processamento)
    return processamento, material


async def test_falha_real_de_integridade_ao_persistir_material_personalizado_marca_erro(
    db_session: AsyncSession,
) -> None:
    """Reprodução de ponta a ponta do bug: um MaterialPersonalizado já existente
    para o processamento_id faz o UniqueConstraint do banco rejeitar a tentativa
    com uma exceção real do driver. Antes do SAVEPOINT em adicionar(), isso
    deixava o Processamento sem ser marcado como erro.
    """
    processamento, material = await _cenario(db_session)
    await MaterialPersonalizadoRepositorySQLAlchemy(db_session).adicionar(
        MaterialPersonalizado(
            id=uuid4(),
            processamento_id=processamento.id,
            titulo="Já existente",
            caminho_pdf="materiais-personalizados/existente.pdf",
            resumo="Resumo já existente.",
            data_geracao=datetime.now(UTC),
        )
    )

    storage = ObjectStorageFake()
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    llm = LLMFake()

    caso_de_uso = ProcessarPersonalizacaoUseCase(
        ProcessamentoRepositorySQLAlchemy(db_session),
        MaterialRepositorySQLAlchemy(db_session),
        PerfilRepositorySQLAlchemy(db_session),
        MaterialPersonalizadoRepositorySQLAlchemy(db_session),
        storage,
        llm,
    )

    # A falha real (UniqueViolation) ocorre, mas não escapa de executar().
    resultado = await caso_de_uso.executar(processamento.id)

    # A sessão continua utilizável e o Processamento é marcado como erro.
    assert resultado.status == StatusProcessamento.ERRO
    assert resultado.erro is not None

    # Nenhuma mensagem interna do driver/SQL vaza para o campo de erro.
    mensagem_erro = resultado.erro.lower()
    assert resultado.erro == "Falha ao processar a personalização do material."
    assert "duplicate" not in mensagem_erro
    assert "unique" not in mensagem_erro
    assert "sqlalchemy" not in mensagem_erro
    assert "asyncpg" not in mensagem_erro
    assert "insert into" not in mensagem_erro

    # O estado de erro é persistido no banco, não só em memória.
    persistido = await ProcessamentoRepositorySQLAlchemy(db_session).obter_por_id(processamento.id)
    assert persistido is not None
    assert persistido.status == StatusProcessamento.ERRO
    assert persistido.erro == "Falha ao processar a personalização do material."

    # Proteção contra PDF órfão (já existente) continua funcionando: o PDF
    # recém-enviado ao Storage para a tentativa que colidiu foi revertido.
    assert len(storage.removidos) == 1
