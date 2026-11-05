from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.acesso.registrar_acesso import RegistrarAcessoInput, RegistrarAcessoUseCase
from domain.acesso.acesso_material_personalizado import AcessoMaterialPersonalizado
from domain.acesso.status_leitura import StatusLeitura
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import EntradaInvalidaError, RecursoNaoEncontradoError
from tests.unit.application.acesso.fakes import AcessoRepositorioFake
from tests.unit.application.processamento.fakes import (
    MaterialPersonalizadoRepositorioFake,
    ProcessamentoRepositorioFake,
)


def _processamento(aluno_id: object) -> Processamento:
    return Processamento(
        id=uuid4(),
        aluno_id=aluno_id,  # type: ignore[arg-type]
        material_didatico_id=uuid4(),
        perfil_id=uuid4(),
        status=StatusProcessamento.CONCLUIDO,
        modelo_ia="gemini-2.0-flash",
        data_criacao=datetime.now(UTC),
        inicio=datetime.now(UTC),
        fim=datetime.now(UTC),
        erro=None,
    )


def _material(processamento_id: object) -> MaterialPersonalizado:
    return MaterialPersonalizado(
        id=uuid4(),
        processamento_id=processamento_id,  # type: ignore[arg-type]
        titulo="Título Personalizado",
        caminho_pdf="materiais-personalizados/x.pdf",
        resumo="Resumo do material.",
        data_geracao=datetime.now(UTC),
    )


@dataclass
class _Cenario:
    processamentos: ProcessamentoRepositorioFake
    materiais: MaterialPersonalizadoRepositorioFake
    acessos: AcessoRepositorioFake
    processamento: Processamento
    material: MaterialPersonalizado


async def _cenario_base() -> _Cenario:
    aluno_id = uuid4()
    processamento = _processamento(aluno_id)
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    material = _material(processamento.id)
    materiais = MaterialPersonalizadoRepositorioFake()
    await materiais.adicionar(material)
    acessos = AcessoRepositorioFake()
    return _Cenario(processamentos, materiais, acessos, processamento, material)


async def test_primeira_chamada_cria_registro_e_retorna_criado_true() -> None:
    cenario = await _cenario_base()

    resultado = await RegistrarAcessoUseCase(
        cenario.processamentos, cenario.materiais, cenario.acessos
    ).executar(
        RegistrarAcessoInput(
            material_personalizado_id=cenario.material.id,
            aluno_id=cenario.processamento.aluno_id,
            tempo_leitura_incremento_segundos=60,
            porcentagem_leitura=0.2,
            download_realizado=False,
        )
    )

    assert resultado.criado is True
    assert resultado.acesso.quantidade_acessos == 1
    assert resultado.acesso.tempo_total_leitura == 60
    assert resultado.acesso.status_leitura == StatusLeitura.EM_ANDAMENTO
    # data_ultimo_acesso é sempre recalculada, mesmo na primeira chamada; não é garantido
    # que coincida com data_primeiro_acesso, só que não é anterior a ela.
    assert resultado.acesso.data_ultimo_acesso >= resultado.acesso.data_primeiro_acesso


async def test_segunda_chamada_atualiza_registro_e_retorna_criado_false() -> None:
    cenario = await _cenario_base()
    primeiro_acesso = datetime(2026, 1, 1, tzinfo=UTC)
    existente = AcessoMaterialPersonalizado(
        id=uuid4(),
        material_personalizado_id=cenario.material.id,
        aluno_id=cenario.processamento.aluno_id,
        data_primeiro_acesso=primeiro_acesso,
        data_ultimo_acesso=primeiro_acesso,
        tempo_total_leitura=60,
        quantidade_acessos=1,
        porcentagem_leitura=0.2,
        download_realizado=False,
        status_leitura=StatusLeitura.EM_ANDAMENTO,
    )
    cenario.acessos.semear(existente)

    resultado = await RegistrarAcessoUseCase(
        cenario.processamentos, cenario.materiais, cenario.acessos
    ).executar(
        RegistrarAcessoInput(
            material_personalizado_id=cenario.material.id,
            aluno_id=cenario.processamento.aluno_id,
            tempo_leitura_incremento_segundos=120,
            porcentagem_leitura=1.0,
            download_realizado=True,
        )
    )

    assert resultado.criado is False
    assert resultado.acesso.quantidade_acessos == 2
    assert resultado.acesso.tempo_total_leitura == 180
    assert resultado.acesso.status_leitura == StatusLeitura.CONCLUIDO
    assert resultado.acesso.data_primeiro_acesso == primeiro_acesso


async def test_processamento_inexistente_apos_material_valido_registra_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Cenário defensivo: processamento_id é FK NOT NULL de material_personalizado
    # (ondelete=RESTRICT), não deveria ocorrer em uso normal, mas o use case precisa tratar.
    processamentos = ProcessamentoRepositorioFake()
    material = _material(uuid4())
    materiais = MaterialPersonalizadoRepositorioFake()
    await materiais.adicionar(material)
    acessos = AcessoRepositorioFake()

    with caplog.at_level("WARNING"), pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await RegistrarAcessoUseCase(processamentos, materiais, acessos).executar(
            RegistrarAcessoInput(
                material_personalizado_id=material.id,
                aluno_id=uuid4(),
                tempo_leitura_incremento_segundos=10,
                porcentagem_leitura=0.1,
                download_realizado=False,
            )
        )

    assert excinfo.value.code == "PROCESSAMENTO_NAO_ENCONTRADO"
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert str(material.processamento_id) in caplog.text


async def test_material_personalizado_inexistente_levanta_recurso_nao_encontrado() -> None:
    processamentos = ProcessamentoRepositorioFake()
    materiais = MaterialPersonalizadoRepositorioFake()
    acessos = AcessoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await RegistrarAcessoUseCase(processamentos, materiais, acessos).executar(
            RegistrarAcessoInput(
                material_personalizado_id=uuid4(),
                aluno_id=uuid4(),
                tempo_leitura_incremento_segundos=10,
                porcentagem_leitura=0.1,
                download_realizado=False,
            )
        )

    assert excinfo.value.code == "MATERIAL_PERSONALIZADO_NAO_ENCONTRADO"


async def test_aluno_id_diferente_do_dono_do_processamento_levanta_entrada_invalida(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cenario = await _cenario_base()
    aluno_intruso = uuid4()

    with caplog.at_level("WARNING"), pytest.raises(EntradaInvalidaError) as excinfo:
        await RegistrarAcessoUseCase(
            cenario.processamentos, cenario.materiais, cenario.acessos
        ).executar(
            RegistrarAcessoInput(
                material_personalizado_id=cenario.material.id,
                aluno_id=aluno_intruso,
                tempo_leitura_incremento_segundos=10,
                porcentagem_leitura=0.1,
                download_realizado=False,
            )
        )

    assert excinfo.value.code == "ALUNO_ID_INVALIDO"
    # BOLA/IDOR é um evento de segurança relevante para auditoria: precisa
    # ficar registrado, mas sem duplicar o corpo/detalhes já retornados na resposta.
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert str(aluno_intruso) in caplog.text
