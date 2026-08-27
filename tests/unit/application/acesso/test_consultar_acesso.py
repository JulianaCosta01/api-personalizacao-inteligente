from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.acesso.consultar_acesso import ConsultarAcessoUseCase
from domain.acesso.acesso_material_personalizado import AcessoMaterialPersonalizado
from domain.acesso.status_leitura import StatusLeitura
from domain.shared.exceptions import RecursoNaoEncontradoError
from tests.unit.application.acesso.fakes import AcessoRepositorioFake


def _acesso(material_personalizado_id: object) -> AcessoMaterialPersonalizado:
    agora = datetime.now(UTC)
    return AcessoMaterialPersonalizado(
        id=uuid4(),
        material_personalizado_id=material_personalizado_id,  # type: ignore[arg-type]
        aluno_id=uuid4(),
        data_primeiro_acesso=agora,
        data_ultimo_acesso=agora,
        tempo_total_leitura=120,
        quantidade_acessos=2,
        porcentagem_leitura=0.5,
        download_realizado=False,
        status_leitura=StatusLeitura.EM_ANDAMENTO,
    )


async def test_retorna_acesso_existente() -> None:
    material_personalizado_id = uuid4()
    acesso = _acesso(material_personalizado_id)
    acessos = AcessoRepositorioFake()
    acessos.semear(acesso)

    resultado = await ConsultarAcessoUseCase(acessos).executar(material_personalizado_id)

    assert resultado.id == acesso.id


async def test_sem_acesso_registrado_levanta_recurso_nao_encontrado() -> None:
    acessos = AcessoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await ConsultarAcessoUseCase(acessos).executar(uuid4())

    assert excinfo.value.code == "ACESSO_NAO_ENCONTRADO"
