import logging
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from application.ports.llm import CategoriaFalhaTransitoria, FalhaTransitoriaDoProvedorError
from application.processamento.politica_de_repeticao import PoliticaDeRepeticao
from application.processamento.processar_personalizacao import ProcessarPersonalizacaoUseCase
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import RecursoNaoEncontradoError
from tests.unit.application.material.fakes import MaterialRepositorioFake, ObjectStorageFake
from tests.unit.application.perfil.fakes import LLMFake, PerfilRepositorioFake

from .fakes import MaterialPersonalizadoRepositorioFake, ProcessamentoRepositorioFake


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


def _perfil(aluno_id: UUID, data_atualizacao: datetime | None = None) -> Perfil:
    return Perfil(
        id=uuid4(),
        aluno_id=aluno_id,
        estilo_processamento=EstiloProcessamento.ATIVO,
        percepcao=Percepcao.SENSORIAL,
        entrada=Entrada.VISUAL,
        compreensao=Compreensao.SEQUENCIAL,
        descricao_llm=None,
        data_atualizacao=data_atualizacao or datetime.now(UTC),
    )


def _processamento(material_id: UUID, perfil_id: UUID, aluno_id: UUID) -> Processamento:
    return Processamento(
        id=uuid4(),
        aluno_id=aluno_id,
        material_didatico_id=material_id,
        perfil_id=perfil_id,
        status=StatusProcessamento.EM_PROCESSAMENTO,
        modelo_ia=None,
        data_criacao=datetime.now(UTC),
        inicio=datetime.now(UTC),
        fim=None,
        erro=None,
    )


async def _cenario_valido() -> tuple[
    ProcessamentoRepositorioFake,
    MaterialRepositorioFake,
    PerfilRepositorioFake,
    MaterialPersonalizadoRepositorioFake,
    ObjectStorageFake,
    LLMFake,
    Processamento,
    MaterialDidatico,
]:
    aluno_id = uuid4()
    material = _material()
    perfil = _perfil(aluno_id)
    processamento = _processamento(material.id, perfil.id, aluno_id)

    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    materiais = MaterialRepositorioFake()
    materiais.semear(material)
    perfis = PerfilRepositorioFake()
    perfis.semear(perfil)
    material_personalizados = MaterialPersonalizadoRepositorioFake()
    storage = ObjectStorageFake()
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    llm = LLMFake()

    return (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        material,
    )


def _caso_de_uso(
    processamentos: ProcessamentoRepositorioFake,
    materiais: MaterialRepositorioFake,
    perfis: PerfilRepositorioFake,
    material_personalizados: MaterialPersonalizadoRepositorioFake,
    storage: ObjectStorageFake,
    llm: LLMFake,
) -> ProcessarPersonalizacaoUseCase:
    return ProcessarPersonalizacaoUseCase(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    )


async def test_processa_com_sucesso_marca_processamento_concluido() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material_didatico,
    ) = await _cenario_valido()

    resultado = await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    assert resultado.status == StatusProcessamento.CONCLUIDO
    assert resultado.fim is not None
    assert resultado.erro is None
    assert len(material_personalizados.adicionados) == 1
    assert material_personalizados.adicionados[0].processamento_id == processamento.id
    assert llm.chamadas_reescrita == 1


async def test_gera_chave_do_storage_no_padrao_esperado() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        material,
    ) = await _cenario_valido()

    await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    chaves_novas = [c for c in storage.salvos if c != material.caminho_storage]
    assert len(chaves_novas) == 1
    assert re.fullmatch(r"materiais-personalizados/[0-9a-f-]{36}\.pdf", chaves_novas[0])


async def test_material_personalizado_aponta_para_pdf_correto() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        material,
    ) = await _cenario_valido()

    await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    chave_gerada = next(c for c in storage.salvos if c != material.caminho_storage)
    assert material_personalizados.adicionados[0].caminho_pdf == chave_gerada
    assert material_personalizados.adicionados[0].resumo == llm.conteudo_reescrito.resumo


async def test_usa_perfil_snapshot_do_processamento_nao_o_mais_recente_do_aluno() -> None:
    aluno_id = uuid4()
    material = _material()
    perfil_antigo = _perfil(aluno_id, datetime.now(UTC))
    perfil_recente = _perfil(aluno_id, datetime.now(UTC))
    perfil_recente.estilo_processamento = EstiloProcessamento.REFLEXIVO
    processamento = _processamento(material.id, perfil_antigo.id, aluno_id)

    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    materiais = MaterialRepositorioFake()
    materiais.semear(material)
    perfis = PerfilRepositorioFake()
    perfis.semear(perfil_antigo)
    perfis.semear(perfil_recente)
    material_personalizados = MaterialPersonalizadoRepositorioFake()
    storage = ObjectStorageFake()
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    llm = LLMFake()

    await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    assert llm.chamadas_reescrita == 1


async def test_processamento_inexistente_levanta_recurso_nao_encontrado() -> None:
    processamentos = ProcessamentoRepositorioFake()
    materiais = MaterialRepositorioFake()
    perfis = PerfilRepositorioFake()
    material_personalizados = MaterialPersonalizadoRepositorioFake()
    storage = ObjectStorageFake()
    llm = LLMFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await _caso_de_uso(
            processamentos, materiais, perfis, material_personalizados, storage, llm
        ).executar(uuid4())

    assert excinfo.value.code == "PROCESSAMENTO_NAO_ENCONTRADO"


async def test_material_inexistente_levanta_recurso_nao_encontrado() -> None:
    aluno_id = uuid4()
    perfil = _perfil(aluno_id)
    processamento = _processamento(uuid4(), perfil.id, aluno_id)
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    materiais = MaterialRepositorioFake()
    perfis = PerfilRepositorioFake()
    perfis.semear(perfil)
    material_personalizados = MaterialPersonalizadoRepositorioFake()
    storage = ObjectStorageFake()
    llm = LLMFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await _caso_de_uso(
            processamentos, materiais, perfis, material_personalizados, storage, llm
        ).executar(processamento.id)

    assert excinfo.value.code == "MATERIAL_NAO_ENCONTRADO"


async def test_perfil_inexistente_levanta_recurso_nao_encontrado() -> None:
    aluno_id = uuid4()
    material = _material()
    processamento = _processamento(material.id, uuid4(), aluno_id)
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    materiais = MaterialRepositorioFake()
    materiais.semear(material)
    perfis = PerfilRepositorioFake()
    material_personalizados = MaterialPersonalizadoRepositorioFake()
    storage = ObjectStorageFake()
    llm = LLMFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await _caso_de_uso(
            processamentos, materiais, perfis, material_personalizados, storage, llm
        ).executar(processamento.id)

    assert excinfo.value.code == "PERFIL_NAO_ENCONTRADO"


async def test_falha_ao_ler_storage_marca_processamento_como_erro() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material_didatico,
    ) = await _cenario_valido()
    storage.falhar_leitura = True

    resultado = await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO
    assert resultado.erro is not None
    assert material_personalizados.adicionados == []


async def test_falha_no_llm_marca_processamento_como_erro() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material_didatico,
    ) = await _cenario_valido()
    llm.levantar_reescrita = True

    resultado = await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO
    assert material_personalizados.adicionados == []


async def test_falha_do_proprio_logging_nao_impede_encerrar_em_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FormatterQuebrado(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            raise RuntimeError("defeito no formatter")

    handler = logging.StreamHandler()
    handler.setFormatter(_FormatterQuebrado())
    raiz = logging.getLogger()
    raiz.addHandler(handler)
    monkeypatch.setattr(logging, "raiseExceptions", False)  # silencia o aviso do próprio logging
    try:
        (
            processamentos,
            materiais,
            perfis,
            material_personalizados,
            storage,
            llm,
            processamento,
            _material_didatico,
        ) = await _cenario_valido()
        llm.levantar_reescrita = True

        resultado = await _caso_de_uso(
            processamentos, materiais, perfis, material_personalizados, storage, llm
        ).executar(processamento.id)
    finally:
        raiz.removeHandler(handler)

    assert resultado.status == StatusProcessamento.ERRO
    assert material_personalizados.adicionados == []


async def test_falha_permanente_registra_traceback_e_mensagem_publica_e_generica(
    caplog: pytest.LogCaptureFixture,
) -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material_didatico,
    ) = await _cenario_valido()
    llm.levantar_reescrita = True

    with caplog.at_level("ERROR"):
        resultado = await _caso_de_uso(
            processamentos, materiais, perfis, material_personalizados, storage, llm
        ).executar(processamento.id)

    # Log interno: traceback completo da exceção original.
    registro = next(r for r in caplog.records if r.exc_info is not None)
    assert registro.exc_info is not None and registro.exc_info[0] is not None
    assert str(processamento.id) in registro.getMessage()
    # O que fica gravado no Processamento (e vai para a API) é só a mensagem genérica.
    assert resultado.erro == "Falha ao processar a personalização do material."


async def test_llm_retorna_none_marca_processamento_como_erro() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material_didatico,
    ) = await _cenario_valido()
    llm.retornar_none_na_reescrita = True

    resultado = await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO


async def test_falha_ao_salvar_pdf_marca_processamento_como_erro() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material_didatico,
    ) = await _cenario_valido()
    storage.falhar_escrita = True

    resultado = await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO
    assert material_personalizados.adicionados == []


async def test_falha_ao_persistir_material_personalizado_marca_processamento_como_erro() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        material,
    ) = await _cenario_valido()
    material_personalizados.falhar_escrita = True

    resultado = await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO


async def test_falha_ao_persistir_material_personalizado_remove_pdf_orfao_do_storage() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        material,
    ) = await _cenario_valido()
    material_personalizados.falhar_escrita = True

    await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    chaves_restantes = [c for c in storage.salvos if c != material.caminho_storage]
    assert chaves_restantes == []
    assert len(storage.removidos) == 1
    assert storage.removidos[0].startswith("materiais-personalizados/")


async def test_falha_no_cleanup_do_storage_nao_esconde_o_erro_original(
    caplog: pytest.LogCaptureFixture,
) -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material_didatico,
    ) = await _cenario_valido()
    material_personalizados.falhar_escrita = True
    storage.falhar_remocao = True

    with caplog.at_level("WARNING"):
        resultado = await _caso_de_uso(
            processamentos, materiais, perfis, material_personalizados, storage, llm
        ).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO
    assert resultado.erro == "Falha ao processar a personalização do material."
    assert "falha simulada" not in resultado.erro


async def test_falha_marca_processamento_como_erro_persiste_a_alteracao() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material_didatico,
    ) = await _cenario_valido()
    llm.levantar_reescrita = True

    await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    persistido = await processamentos.obter_por_id(processamento.id)
    assert persistido is not None
    assert persistido.status == StatusProcessamento.ERRO


# Posse da execução


async def test_posse_perdida_no_sucesso_descarta_o_resultado_e_remove_o_pdf() -> None:
    from application.processamento.processar_personalizacao import PosseDoProcessamentoPerdidaError

    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material,
    ) = await _cenario_valido()
    processamentos.perder_posse = True
    caso = _caso_de_uso(processamentos, materiais, perfis, material_personalizados, storage, llm)

    with pytest.raises(PosseDoProcessamentoPerdidaError):
        await caso.executar(processamento.id)

    # O PDF enviado ao Storage por esta execução foi revertido (nenhum órfão).
    assert caso.chave_pdf_gerada is not None
    assert caso.chave_pdf_gerada not in storage.salvos


async def test_posse_perdida_na_falha_nao_levanta_e_devolve_o_erro_local() -> None:
    (
        processamentos,
        materiais,
        perfis,
        material_personalizados,
        storage,
        llm,
        processamento,
        _material,
    ) = await _cenario_valido()
    processamentos.perder_posse = True
    llm.levantar_reescrita = True  # falha do modelo
    resultado = await _caso_de_uso(
        processamentos, materiais, perfis, material_personalizados, storage, llm
    ).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO


# Falhas transitórias do provedor: repetição controlada

_MENSAGEM_GENERICA = "Falha ao processar a personalização do material."


def _falha_transitoria(
    categoria: CategoriaFalhaTransitoria = CategoriaFalhaTransitoria.HTTP_5XX,
    status: int | None = 503,
) -> FalhaTransitoriaDoProvedorError:
    return FalhaTransitoriaDoProvedorError(categoria, status)


def _caso_com_politica(
    cenario: tuple[
        ProcessamentoRepositorioFake,
        MaterialRepositorioFake,
        PerfilRepositorioFake,
        MaterialPersonalizadoRepositorioFake,
        ObjectStorageFake,
        LLMFake,
        Processamento,
        MaterialDidatico,
    ],
    politica: PoliticaDeRepeticao | None,
) -> ProcessarPersonalizacaoUseCase:
    processamentos, materiais, perfis, material_personalizados, storage, llm, _p, _m = cenario
    return ProcessarPersonalizacaoUseCase(
        processamentos, materiais, perfis, material_personalizados, storage, llm, politica
    )


async def test_falha_transitoria_com_tentativas_restantes_devolve_o_job_a_pendente() -> None:
    cenario = await _cenario_valido()
    processamentos, _m, _pf, material_personalizados, storage, llm, processamento, _mat = cenario
    processamento.tentativas = 1
    llm.falha_transitoria_na_reescrita = _falha_transitoria()
    antes = datetime.now(UTC)

    resultado = await _caso_com_politica(cenario, PoliticaDeRepeticao(3)).executar(processamento.id)

    assert resultado.status == StatusProcessamento.PENDENTE
    assert resultado.erro is None
    assert resultado.fim is None
    assert resultado.disponivel_em is not None and resultado.disponivel_em > antes
    assert processamentos.devolvidos[0][0] == processamento.id
    assert processamentos.devolvidos[0][2] == 3  # o limite vai junto, para a guarda no SQL
    # Nada foi gravado: nem material, nem PDF novo no Storage.
    assert material_personalizados.adicionados == []
    assert list(storage.salvos) == ["materiais/a1b2c3.pdf"]


async def test_falha_transitoria_na_ultima_tentativa_encerra_em_erro() -> None:
    cenario = await _cenario_valido()
    processamentos, _m, _pf, _mp, _s, llm, processamento, _mat = cenario
    processamento.tentativas = 3  # terceira reivindicação de um limite de 3
    llm.falha_transitoria_na_reescrita = _falha_transitoria()

    resultado = await _caso_com_politica(cenario, PoliticaDeRepeticao(3)).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO
    assert resultado.erro == _MENSAGEM_GENERICA
    assert resultado.fim is not None
    assert processamentos.devolvidos == []


@pytest.mark.parametrize(("tentativas", "devolve"), [(1, True), (2, True), (3, False), (4, False)])
async def test_limite_de_tentativas_nunca_e_ultrapassado(tentativas: int, devolve: bool) -> None:
    cenario = await _cenario_valido()
    processamentos, _m, _pf, _mp, _s, llm, processamento, _mat = cenario
    processamento.tentativas = tentativas
    llm.falha_transitoria_na_reescrita = _falha_transitoria()

    resultado = await _caso_com_politica(cenario, PoliticaDeRepeticao(3)).executar(processamento.id)

    assert (resultado.status == StatusProcessamento.PENDENTE) is devolve
    assert (len(processamentos.devolvidos) == 1) is devolve


async def test_sem_politica_a_falha_transitoria_encerra_em_erro() -> None:
    cenario = await _cenario_valido()
    processamentos, _m, _pf, _mp, _s, llm, processamento, _mat = cenario
    processamento.tentativas = 1
    llm.falha_transitoria_na_reescrita = _falha_transitoria()

    resultado = await _caso_com_politica(cenario, None).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO
    assert processamentos.devolvidos == []


@pytest.mark.parametrize(
    "ajuste",
    ["none", "excecao_generica", "storage"],
)
async def test_falhas_permanentes_nao_sao_devolvidas_a_fila(ajuste: str) -> None:
    # Resposta vazia/None, erro de código/PDF e falha de Storage encerram em erro, mesmo com
    # tentativas sobrando: não são falhas transitórias do provedor de IA.
    cenario = await _cenario_valido()
    processamentos, _m, _pf, _mp, storage, llm, processamento, _mat = cenario
    processamento.tentativas = 1
    if ajuste == "none":
        llm.retornar_none_na_reescrita = True
    elif ajuste == "excecao_generica":
        llm.levantar_reescrita = True
    else:
        storage.falhar_leitura = True

    resultado = await _caso_com_politica(cenario, PoliticaDeRepeticao(3)).executar(processamento.id)

    assert resultado.status == StatusProcessamento.ERRO
    assert resultado.erro == _MENSAGEM_GENERICA
    assert processamentos.devolvidos == []


async def test_posse_perdida_ao_devolver_nao_sobrescreve_nem_levanta() -> None:
    cenario = await _cenario_valido()
    processamentos, _m, _pf, material_personalizados, _s, llm, processamento, _mat = cenario
    processamento.tentativas = 1
    processamentos.perder_posse = True
    llm.falha_transitoria_na_reescrita = _falha_transitoria()

    resultado = await _caso_com_politica(cenario, PoliticaDeRepeticao(3)).executar(processamento.id)

    # Nada foi gravado como devolução; o erro local também não foi persistido (sem posse).
    assert processamentos.devolvidos == []
    assert resultado.status == StatusProcessamento.ERRO
    assert material_personalizados.adicionados == []


@pytest.mark.parametrize(("tentativas", "minimo", "maximo"), [(1, 24.0, 30.0), (2, 48.0, 60.0)])
async def test_espera_respeita_o_backoff_progressivo(
    tentativas: int, minimo: float, maximo: float
) -> None:
    cenario = await _cenario_valido()
    processamentos, _m, _pf, _mp, _s, llm, processamento, _mat = cenario
    processamento.tentativas = tentativas
    llm.falha_transitoria_na_reescrita = _falha_transitoria()
    antes = datetime.now(UTC)

    await _caso_com_politica(cenario, PoliticaDeRepeticao(3)).executar(processamento.id)

    espera = (processamentos.devolvidos[0][1] - antes).total_seconds()
    assert minimo - 1 <= espera <= maximo + 1


async def test_falha_transitoria_registra_so_categoria_e_codigo_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cenario = await _cenario_valido()
    _pr, _m, _pf, _mp, _s, llm, processamento, _mat = cenario
    processamento.tentativas = 1
    llm.falha_transitoria_na_reescrita = _falha_transitoria(CategoriaFalhaTransitoria.HTTP_429, 429)

    with caplog.at_level("WARNING"):
        await _caso_com_politica(cenario, PoliticaDeRepeticao(3)).executar(processamento.id)

    assert "http_429" in caplog.text
    assert "tentativa 1 de 3" in caplog.text
    assert str(processamento.id) in caplog.text
    assert "Traceback" not in caplog.text
