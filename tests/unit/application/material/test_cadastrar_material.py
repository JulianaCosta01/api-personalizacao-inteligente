from uuid import UUID, uuid4

import pytest

from application.material.cadastrar_material import (
    CadastrarMaterialInput,
    CadastrarMaterialUseCase,
)
from domain.material.tipo_arquivo import TipoArquivo
from domain.shared.exceptions import EntradaInvalidaError, RecursoNaoEncontradoError

from .fakes import MaterialRepositorioFake, ObjectStorageFake

_PDF_VALIDO = b"%PDF-1.7\nconteudo qualquer"


def _input(
    titulo: str = "Introdução a Grafos",
    nome_arquivo: str = "grafos.pdf",
    conteudo: bytes = _PDF_VALIDO,
    material_original_id: UUID | None = None,
) -> CadastrarMaterialInput:
    return CadastrarMaterialInput(
        titulo=titulo,
        nome_arquivo=nome_arquivo,
        conteudo=conteudo,
        material_original_id=material_original_id,
    )


async def test_cadastra_novo_material_com_versao_1() -> None:
    repositorio = MaterialRepositorioFake()
    storage = ObjectStorageFake()

    material = await CadastrarMaterialUseCase(repositorio, storage).executar(_input())

    assert material.versao == 1
    assert material.tipo_arquivo == TipoArquivo.PDF
    assert await repositorio.obter_por_id(material.id) is not None


async def test_grava_no_storage_antes_de_persistir() -> None:
    repositorio = MaterialRepositorioFake()
    storage = ObjectStorageFake()

    material = await CadastrarMaterialUseCase(repositorio, storage).executar(_input())

    assert storage.salvos[material.caminho_storage] == _PDF_VALIDO


async def test_arquivo_sem_assinatura_pdf_levanta_entrada_invalida() -> None:
    repositorio = MaterialRepositorioFake()
    storage = ObjectStorageFake()

    with pytest.raises(EntradaInvalidaError):
        await CadastrarMaterialUseCase(repositorio, storage).executar(
            _input(conteudo=b"nao e um pdf")
        )

    assert storage.salvos == {}


async def test_revisao_de_material_existente_incrementa_versao_preserva_id() -> None:
    repositorio = MaterialRepositorioFake()
    storage = ObjectStorageFake()
    original = await CadastrarMaterialUseCase(repositorio, storage).executar(_input())

    revisao = await CadastrarMaterialUseCase(repositorio, storage).executar(
        _input(nome_arquivo="grafos_v2.pdf", material_original_id=original.id)
    )

    assert revisao.id == original.id
    assert revisao.versao == 2
    assert revisao.nome_arquivo == "grafos_v2.pdf"


async def test_revisao_de_material_inexistente_levanta_recurso_nao_encontrado() -> None:
    repositorio = MaterialRepositorioFake()
    storage = ObjectStorageFake()

    with pytest.raises(RecursoNaoEncontradoError):
        await CadastrarMaterialUseCase(repositorio, storage).executar(
            _input(material_original_id=uuid4())
        )


async def test_falha_ao_persistir_remove_o_objeto_recem_gravado_no_storage() -> None:
    repositorio = MaterialRepositorioFake(falhar_escrita=True)
    storage = ObjectStorageFake()

    with pytest.raises(RuntimeError):
        await CadastrarMaterialUseCase(repositorio, storage).executar(_input())

    assert storage.salvos == {}
    assert len(storage.removidos) == 1


async def test_falha_ao_remover_objeto_orfao_nao_mascara_o_erro_original() -> None:
    repositorio = MaterialRepositorioFake(falhar_escrita=True)
    storage = ObjectStorageFake(falhar_remocao=True)

    with pytest.raises(RuntimeError, match="falha simulada de banco"):
        await CadastrarMaterialUseCase(repositorio, storage).executar(_input())
