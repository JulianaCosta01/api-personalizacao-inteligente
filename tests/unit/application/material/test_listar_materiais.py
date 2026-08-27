from datetime import UTC, datetime
from uuid import uuid4

from application.material.listar_materiais import ListarMateriaisInput, ListarMateriaisUseCase
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo

from .fakes import MaterialRepositorioFake


def _material(titulo: str) -> MaterialDidatico:
    return MaterialDidatico(
        id=uuid4(),
        titulo=titulo,
        nome_arquivo="arquivo.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage=f"materiais/{uuid4()}.pdf",
        versao=1,
        data_upload=datetime.now(UTC),
    )


async def test_lista_todos_os_materiais_sem_filtro() -> None:
    repositorio = MaterialRepositorioFake()
    repositorio.semear(_material("Grafos"))
    repositorio.semear(_material("Árvores"))

    resultado = await ListarMateriaisUseCase(repositorio).executar(ListarMateriaisInput())

    assert resultado.total_itens == 2
    assert len(resultado.itens) == 2


async def test_filtra_por_titulo_parcial_sem_case_sensitive() -> None:
    repositorio = MaterialRepositorioFake()
    repositorio.semear(_material("Introdução a Grafos"))
    repositorio.semear(_material("Árvores Binárias"))

    resultado = await ListarMateriaisUseCase(repositorio).executar(
        ListarMateriaisInput(titulo="grafos")
    )

    assert resultado.total_itens == 1
    assert resultado.itens[0].titulo == "Introdução a Grafos"


async def test_pagina_corretamente() -> None:
    repositorio = MaterialRepositorioFake()
    for i in range(5):
        repositorio.semear(_material(f"Material {i}"))

    resultado = await ListarMateriaisUseCase(repositorio).executar(
        ListarMateriaisInput(pagina=2, tamanho_pagina=2)
    )

    assert resultado.total_itens == 5
    assert len(resultado.itens) == 2
