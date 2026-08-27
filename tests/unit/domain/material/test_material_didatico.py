from datetime import UTC, datetime
from uuid import uuid4

from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo


def _material() -> MaterialDidatico:
    return MaterialDidatico(
        id=uuid4(),
        titulo="Introdução a Grafos",
        nome_arquivo="a1b2c3.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage="materiais/a1b2c3.pdf",
        versao=1,
        data_upload=datetime.now(UTC),
    )


def test_revisar_incrementa_versao_e_atualiza_arquivo() -> None:
    material = _material()
    nova_data = datetime.now(UTC)

    material.revisar(
        nome_arquivo="novo.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage="materiais/novo.pdf",
        data_upload=nova_data,
    )

    assert material.versao == 2
    assert material.nome_arquivo == "novo.pdf"
    assert material.caminho_storage == "materiais/novo.pdf"
    assert material.data_upload == nova_data


def test_revisar_preserva_id_e_titulo() -> None:
    material = _material()
    id_original = material.id
    titulo_original = material.titulo

    material.revisar(
        nome_arquivo="novo.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage="materiais/novo.pdf",
        data_upload=datetime.now(UTC),
    )

    assert material.id == id_original
    assert material.titulo == titulo_original


def test_revisoes_sucessivas_incrementam_versao_cumulativamente() -> None:
    material = _material()

    material.revisar("a.pdf", TipoArquivo.PDF, "materiais/a.pdf", datetime.now(UTC))
    material.revisar("b.pdf", TipoArquivo.PDF, "materiais/b.pdf", datetime.now(UTC))

    assert material.versao == 3
