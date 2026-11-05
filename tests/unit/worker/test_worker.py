import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from application.processamento.processar_personalizacao import PosseDoProcessamentoPerdidaError
from core.logging import JsonFormatter, request_id_var
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.llm.gemini_adapter import GeminiAdapter
from worker.worker import (
    _construir_ciclo_com_recuperacao_periodica,
    executar_ciclo,
    executar_worker,
    processar_reivindicado,
    recuperar_processamentos_presos,
)


async def test_ciclo_nao_processa_quando_nao_ha_nada_para_reivindicar() -> None:
    with (
        patch("worker.worker.reivindicar_processamento", new=AsyncMock(return_value=None)),
        patch("worker.worker.processar_reivindicado", new=AsyncMock()) as processar_mock,
    ):
        await executar_ciclo()

    processar_mock.assert_not_awaited()


async def test_ciclo_processa_o_processamento_reivindicado() -> None:
    processamento_id = uuid4()
    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch("worker.worker.processar_reivindicado", new=AsyncMock()) as processar_mock,
    ):
        await executar_ciclo()

    processar_mock.assert_awaited_once_with(processamento_id)


async def test_ciclo_com_recuperacao_periodica_nao_recupera_antes_do_intervalo() -> None:
    # Logo após construído (equivalente a logo após a recuperação da inicialização do Worker),
    # nenhuma chamada deveria dever recuperação: o intervalo configurado ainda não passou.
    with (
        patch("worker.worker.reivindicar_processamento", new=AsyncMock(return_value=None)),
        patch("worker.worker.recuperar_processamentos_presos", new=AsyncMock()) as recuperar_mock,
    ):
        ciclo = _construir_ciclo_com_recuperacao_periodica(600.0)
        await ciclo()
        await ciclo()
        await ciclo()

    recuperar_mock.assert_not_awaited()


async def test_ciclo_com_recuperacao_periodica_dispara_apos_intervalo_decorrido() -> None:
    # Com intervalo 0.0, toda iteração já está "vencida": prova que a recuperação periódica
    # dispara quando o tempo configurado passa, sem depender de nenhum scheduler externo.
    with (
        patch("worker.worker.reivindicar_processamento", new=AsyncMock(return_value=None)),
        patch("worker.worker.recuperar_processamentos_presos", new=AsyncMock()) as recuperar_mock,
    ):
        ciclo = _construir_ciclo_com_recuperacao_periodica(0.0)
        await ciclo()
        await ciclo()
        await ciclo()

    assert recuperar_mock.await_count == 3


async def test_ciclo_com_recuperacao_periodica_nao_interfere_no_polling_normal() -> None:
    # A recuperação periódica é uma etapa A MAIS dentro do ciclo, nunca no lugar do
    # claim/processamento normal: reivindicar/processar continuam sendo chamados sempre.
    processamento_id = uuid4()
    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch("worker.worker.processar_reivindicado", new=AsyncMock()) as processar_mock,
        patch("worker.worker.recuperar_processamentos_presos", new=AsyncMock()) as recuperar_mock,
    ):
        ciclo = _construir_ciclo_com_recuperacao_periodica(0.0)
        await ciclo()
        await ciclo()

    assert processar_mock.await_count == 2
    assert recuperar_mock.await_count == 2


async def test_ciclo_define_request_id_var_com_processamento_id_durante_o_processamento() -> None:
    processamento_id = uuid4()
    capturado: list[str | None] = []

    async def _processar_capturando_contexto(_id: object) -> None:
        capturado.append(request_id_var.get())

    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch(
            "worker.worker.processar_reivindicado",
            new=AsyncMock(side_effect=_processar_capturando_contexto),
        ),
    ):
        await executar_ciclo()

    assert capturado == [str(processamento_id)]


async def test_ciclo_restaura_o_contexto_apos_o_processamento() -> None:
    processamento_id = uuid4()

    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch("worker.worker.processar_reivindicado", new=AsyncMock()),
    ):
        await executar_ciclo()

    assert request_id_var.get() is None


async def test_ciclo_restaura_o_contexto_mesmo_quando_processar_reivindicado_lanca_excecao() -> (
    None
):
    processamento_id = uuid4()

    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch(
            "worker.worker.processar_reivindicado",
            new=AsyncMock(side_effect=RuntimeError("falha simulada no processamento")),
        ),
        pytest.raises(RuntimeError, match="falha simulada no processamento"),
    ):
        await executar_ciclo()

    assert request_id_var.get() is None


async def test_dois_processamentos_consecutivos_nao_compartilham_o_mesmo_request_id() -> None:
    primeiro_id = uuid4()
    segundo_id = uuid4()
    capturado: list[str | None] = []

    async def _processar_capturando_contexto(_id: object) -> None:
        capturado.append(request_id_var.get())

    with patch(
        "worker.worker.processar_reivindicado",
        new=AsyncMock(side_effect=_processar_capturando_contexto),
    ):
        with patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=primeiro_id),
        ):
            await executar_ciclo()

        # Nada de request_id vazado do primeiro ciclo antes do segundo começar.
        assert request_id_var.get() is None

        with patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=segundo_id),
        ):
            await executar_ciclo()

    assert capturado == [str(primeiro_id), str(segundo_id)]
    assert capturado[0] != capturado[1]


async def test_logs_emitidos_durante_o_processamento_carregam_o_mesmo_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Prova a integração real: um logger arbitrário é formatado pelo JsonFormatter de verdade
    # e carrega o processamento_id. Formatação precisa ocorrer dentro do contexto, no side_effect.
    processamento_id = uuid4()
    logger_do_pipeline = logging.getLogger("worker.teste_pipeline")
    payloads_formatados: list[dict[str, str]] = []

    async def _processar_logando(_id: object) -> None:
        logger_do_pipeline.info("Processando material personalizado.")
        payloads_formatados.append(json.loads(JsonFormatter().format(caplog.records[-1])))

    with (
        caplog.at_level(logging.INFO, logger="worker.teste_pipeline"),
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch(
            "worker.worker.processar_reivindicado",
            new=AsyncMock(side_effect=_processar_logando),
        ),
    ):
        await executar_ciclo()

    assert len(payloads_formatados) == 1
    assert payloads_formatados[0]["request_id"] == str(processamento_id)


async def test_executar_worker_configura_logging_json_no_nivel_das_settings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raiz = logging.getLogger()
    anteriores, nivel_anterior = raiz.handlers[:], raiz.level
    raiz.handlers, raiz.level = [], logging.WARNING  # estado padrão de um processo sem config
    try:
        with (
            patch("worker.worker.recuperar_processamentos_presos", new=AsyncMock()),
            patch("worker.worker.executar_loop", new=AsyncMock()),
            patch("worker.worker.get_settings") as settings,
        ):
            settings.return_value.log_level = "INFO"
            settings.return_value.worker_idade_maxima_presos_segundos = 600.0
            settings.return_value.worker_intervalo_polling_segundos = 5.0
            settings.return_value.worker_tentativas_maximas = 3
            settings.return_value.worker_prazo_maximo_job_segundos = 420.0
            await executar_worker()

        assert raiz.level == logging.INFO
        assert any(isinstance(h.formatter, JsonFormatter) for h in raiz.handlers)
        # Um Worker ocioso precisa deixar rastro de que o logging está ativo.
        inicio = json.loads(capsys.readouterr().err.strip().splitlines()[0])
        assert inicio["level"] == "INFO" and "Worker iniciado" in inicio["message"]
        assert "tentativas máximas=3" in inicio["message"]
        logging.getLogger("worker.claim").info("Processamento de teste reivindicado.")
        linha = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
        assert linha["level"] == "INFO" and "reivindicado" in linha["message"]
    finally:
        raiz.handlers, raiz.level = anteriores, nivel_anterior


# Prazo máximo por job, posse e tentativas


class _CasoDeUsoLento:
    def __init__(self, chave: str | None = None) -> None:
        self.chave_pdf_gerada = chave
        self.revertidos: list[str] = []

    async def executar(self, processamento_id: object) -> object:
        await asyncio.sleep(3600)
        raise AssertionError("não deveria terminar")

    async def reverter_upload(self, chave: str) -> None:
        self.revertidos.append(chave)


@contextlib.contextmanager
def _sessao_falsa() -> Iterator[None]:
    @contextlib.asynccontextmanager
    async def sessao() -> AsyncIterator[object]:
        yield object()

    with patch("worker.worker.sessao_transacional", sessao):
        yield


async def test_job_que_excede_o_prazo_termina_em_erro_e_reverte_o_pdf() -> None:
    caso = _CasoDeUsoLento(chave="materiais-personalizados/x.pdf")
    with (
        _sessao_falsa(),
        patch("worker.worker.get_settings") as settings,
        patch("worker.worker.encerrar_por_prazo_excedido", new=AsyncMock()) as encerrar,
    ):
        settings.return_value.worker_prazo_maximo_job_segundos = 0.05
        id_ = uuid4()
        status = await processar_reivindicado(id_, lambda _sessao: caso)  # type: ignore[arg-type,return-value]

    assert status == StatusProcessamento.ERRO
    assert caso.revertidos == ["materiais-personalizados/x.pdf"]
    encerrar.assert_awaited_once_with(id_)


async def test_cancelamento_externo_do_job_nao_e_confundido_com_prazo() -> None:
    caso = _CasoDeUsoLento()
    with (
        _sessao_falsa(),
        patch("worker.worker.get_settings") as settings,
        patch("worker.worker.encerrar_por_prazo_excedido", new=AsyncMock()) as encerrar,
    ):
        settings.return_value.worker_prazo_maximo_job_segundos = 60.0
        tarefa = asyncio.create_task(processar_reivindicado(uuid4(), lambda _s: caso))  # type: ignore[arg-type,return-value]
        await asyncio.sleep(0.05)
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa
    encerrar.assert_not_awaited()


async def test_posse_perdida_nao_e_tratada_como_sucesso_nem_como_erro_do_job() -> None:
    class _Caso:
        chave_pdf_gerada = None

        async def executar(self, processamento_id: object) -> object:
            raise PosseDoProcessamentoPerdidaError("x")

    with (
        _sessao_falsa(),
        patch("worker.worker.get_settings") as settings,
        patch("worker.worker.encerrar_por_prazo_excedido", new=AsyncMock()) as encerrar,
    ):
        settings.return_value.worker_prazo_maximo_job_segundos = 5.0
        status = await processar_reivindicado(uuid4(), lambda _s: _Caso())  # type: ignore[arg-type,return-value]

    assert status == StatusProcessamento.EM_PROCESSAMENTO
    encerrar.assert_not_awaited()


async def test_recuperacao_encerra_primeiro_os_sem_tentativas_e_depois_libera_os_demais() -> None:
    chamadas: list[str] = []

    class _Repo:
        def __init__(self, _sessao: object) -> None: ...

        async def esgotar_tentativas_dos_presos(self, idade: object, maximo: int) -> list[object]:
            chamadas.append(f"esgotar:{maximo}")
            return [uuid4()]

        async def liberar_presos(self, idade: object, maximo: int | None = None) -> list[object]:
            chamadas.append(f"liberar:{maximo}")
            return []

    with (
        _sessao_falsa(),
        patch("worker.worker.ProcessamentoRepositorySQLAlchemy", _Repo),
        patch("worker.worker.get_settings") as settings,
    ):
        settings.return_value.worker_idade_maxima_presos_segundos = 600.0
        settings.return_value.worker_tentativas_maximas = 3
        await recuperar_processamentos_presos()

    assert chamadas == ["esgotar:3", "liberar:3"]


# Política de repetição por falha transitória


def test_caso_de_uso_do_worker_recebe_a_politica_das_settings() -> None:
    from types import SimpleNamespace

    from worker.worker import _construir_caso_de_uso

    settings = SimpleNamespace(
        storage_bucket_materiais="bucket-de-teste",
        gemini_model="modelo-de-teste",
        gemini_timeout_segundos=5.0,
        gemini_timeout_total_segundos=45.0,
        gemini_reescrita_complemento_tentativas=1,
        gemini_reescrita_proporcao_minima=0.8,
        pdf_anexar_imagens_originais=False,
        worker_tentativas_maximas=3,
        worker_repeticao_atraso_base_segundos=30.0,
        worker_repeticao_atraso_maximo_segundos=300.0,
        imagens_geradas_habilitadas=False,
        imagens_max_por_material=1,
        imagens_orcamento_total_segundos=150.0,
        imagens_timeout_total_segundos=120.0,
        pipeline_timeout_extracao_segundos=30.0,
        pipeline_timeout_pdf_segundos=60.0,
    )
    with (
        patch("worker.worker.get_settings", return_value=settings),
        patch("worker.worker.get_storage_client"),
        patch("worker.worker.get_gemini_client"),
    ):
        caso = _construir_caso_de_uso(object())  # type: ignore[arg-type]

    politica = caso._politica_de_repeticao
    assert politica is not None
    assert (politica.tentativas_maximas, politica.atraso_base_segundos) == (3, 30.0)
    assert politica.atraso_maximo_segundos == 300.0


def _gemini_do(caso: object) -> GeminiAdapter:
    adaptador = getattr(caso, "_llm")  # noqa: B009 - atributo privado, só para inspeção em teste
    assert isinstance(adaptador, GeminiAdapter)
    return adaptador


def _settings_de_imagens(habilitadas: bool) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        storage_bucket_materiais="bucket-de-teste",
        gemini_model="modelo-de-teste",
        gemini_timeout_segundos=5.0,
        gemini_timeout_total_segundos=45.0,
        gemini_reescrita_complemento_tentativas=1,
        gemini_reescrita_proporcao_minima=0.8,
        pdf_anexar_imagens_originais=False,
        worker_tentativas_maximas=3,
        worker_repeticao_atraso_base_segundos=30.0,
        worker_repeticao_atraso_maximo_segundos=300.0,
        imagens_geradas_habilitadas=habilitadas,
        imagens_max_por_material=2,
        imagens_orcamento_total_segundos=140.0,
        imagens_timeout_total_segundos=90.0,
        pipeline_timeout_extracao_segundos=25.0,
        pipeline_timeout_pdf_segundos=55.0,
    )


@pytest.fixture
def _sem_gerador_em_cache() -> Iterator[None]:
    from worker.worker import _obter_gerador_de_imagens

    _obter_gerador_de_imagens.cache_clear()
    yield
    _obter_gerador_de_imagens.cache_clear()


def test_imagens_desligadas_nao_criam_gerador_e_mantem_o_comportamento_atual(
    _sem_gerador_em_cache: None,
) -> None:
    from worker.worker import _construir_caso_de_uso

    with (
        patch("worker.worker.get_settings", return_value=_settings_de_imagens(False)),
        patch("worker.worker.get_storage_client"),
        patch("worker.worker.get_gemini_client"),
        patch("worker.worker.CloudflareImageAdapter") as cloudflare,
    ):
        caso = _construir_caso_de_uso(object())  # type: ignore[arg-type]

    cloudflare.a_partir_de_settings.assert_not_called()
    adaptador = _gemini_do(caso)
    assert adaptador._gerador_de_imagens is None
    assert adaptador._imagens_geradas_habilitadas is False
    assert adaptador._complemento_de_imagens_ativo() is False
    # Limites das etapas locais chegam ao adaptador, separados do timeout do Gemini.
    assert adaptador._timeout_segundos == 5.0
    assert adaptador._timeout_extracao_segundos == 25.0
    assert adaptador._timeout_pdf_segundos == 55.0
    # Sem o complemento, a instrução enviada ao Gemini é exatamente a original.
    assert "IMAGEM" not in adaptador._instrucao_de_reescrita()


def test_imagens_ligadas_injetam_o_gerador_e_as_configuracoes_no_gemini(
    _sem_gerador_em_cache: None,
) -> None:
    from worker.worker import _construir_caso_de_uso

    settings = _settings_de_imagens(True)
    with (
        patch("worker.worker.get_settings", return_value=settings),
        patch("worker.worker.get_storage_client"),
        patch("worker.worker.get_gemini_client"),
        patch("worker.worker.CloudflareImageAdapter") as cloudflare,
    ):
        caso = _construir_caso_de_uso(object())  # type: ignore[arg-type]

    cloudflare.a_partir_de_settings.assert_called_once_with(settings)
    adaptador = _gemini_do(caso)
    assert adaptador._gerador_de_imagens is cloudflare.a_partir_de_settings.return_value
    assert adaptador._imagens_geradas_habilitadas is True
    assert adaptador._imagens_max_por_material == 2
    assert adaptador._imagens_orcamento_total_segundos == 140.0
    assert adaptador._imagens_timeout_total_segundos == 90.0
    assert adaptador._complemento_de_imagens_ativo() is True
    # As imagens do PDF de origem não são anexadas por padrão, nem com as ilustrações ligadas.
    assert adaptador._anexar_imagens_originais is False


def test_gerador_de_imagens_e_reaproveitado_entre_jobs(_sem_gerador_em_cache: None) -> None:
    from worker.worker import _construir_caso_de_uso

    with (
        patch("worker.worker.get_settings", return_value=_settings_de_imagens(True)),
        patch("worker.worker.get_storage_client"),
        patch("worker.worker.get_gemini_client"),
        patch("worker.worker.CloudflareImageAdapter") as cloudflare,
    ):
        _construir_caso_de_uso(object())  # type: ignore[arg-type]
        _construir_caso_de_uso(object())  # type: ignore[arg-type]

    assert cloudflare.a_partir_de_settings.call_count == 1


def test_worker_monta_o_adaptador_real_da_cloudflare_a_partir_das_settings(
    _sem_gerador_em_cache: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sem mocks do adaptador: Settings reais (sem .env) com o provedor `cloudflare`. Nenhuma rede.
    from infrastructure.config.settings import Settings
    from infrastructure.imagens.cloudflare_adapter import CloudflareImageAdapter
    from worker.worker import _construir_caso_de_uso

    for nome in ("IMAGENS_GERADAS_HABILITADAS", "IMAGENS_PROVEDOR", "CLOUDFLARE_IMAGE_STEPS"):
        monkeypatch.delenv(nome, raising=False)
    settings = Settings(
        _env_file=None,
        imagens_geradas_habilitadas=True,
        imagens_provedor="cloudflare",
        cloudflare_account_id="0123456789abcdef0123456789abcdef",
        cloudflare_api_token="cf-token-de-teste-que-nao-pode-vazar",
        cloudflare_image_model="@cf/black-forest-labs/flux-1-schnell",
    )
    with (
        patch("worker.worker.get_settings", return_value=settings),
        patch("worker.worker.get_storage_client"),
        patch("worker.worker.get_gemini_client"),
    ):
        caso = _construir_caso_de_uso(object())  # type: ignore[arg-type]

    gerador = _gemini_do(caso)._gerador_de_imagens
    assert isinstance(gerador, CloudflareImageAdapter)
    assert gerador._passos == 4
    assert str(gerador._cliente.base_url).rstrip("/") == "https://api.cloudflare.com/client/v4"
    assert gerador._cliente.follow_redirects is False
    assert _gemini_do(caso)._imagens_geradas_habilitadas is True


def test_worker_nao_sobe_com_cloudflare_ligada_e_id_de_conta_incompleto() -> None:
    from pydantic import ValidationError

    from infrastructure.config.settings import Settings

    with pytest.raises(ValidationError, match="32 caracteres"):
        Settings(
            _env_file=None,
            imagens_geradas_habilitadas=True,
            imagens_provedor="cloudflare",
            cloudflare_account_id="0123456789abcdef0123456789abc",
            cloudflare_api_token="x",
            cloudflare_image_model="@cf/black-forest-labs/flux-1-schnell",
        )


async def test_job_devolvido_a_pendente_preserva_a_mensagem_da_fila() -> None:
    # PENDENTE (falha transitória) NÃO remove a mensagem: o claim depende dela.
    class _Caso:
        chave_pdf_gerada = None

        async def executar(self, processamento_id: object) -> object:
            from types import SimpleNamespace

            return SimpleNamespace(status=StatusProcessamento.PENDENTE)

    with (
        _sessao_falsa(),
        patch("worker.worker.get_settings") as settings,
        patch("worker.worker.FilaPostgres") as fila,
    ):
        settings.return_value.worker_prazo_maximo_job_segundos = 5.0
        status = await processar_reivindicado(uuid4(), lambda _s: _Caso())  # type: ignore[arg-type,return-value]

    assert status == StatusProcessamento.PENDENTE
    fila.assert_not_called()


async def test_job_concluido_remove_a_mensagem_da_fila() -> None:
    class _Caso:
        chave_pdf_gerada = None

        async def executar(self, processamento_id: object) -> object:
            from types import SimpleNamespace

            return SimpleNamespace(status=StatusProcessamento.CONCLUIDO)

    with (
        _sessao_falsa(),
        patch("worker.worker.get_settings") as settings,
        patch("worker.worker.FilaPostgres") as fila,
    ):
        fila.return_value.remover = AsyncMock()
        settings.return_value.worker_prazo_maximo_job_segundos = 5.0
        id_ = uuid4()
        status = await processar_reivindicado(id_, lambda _s: _Caso())  # type: ignore[arg-type,return-value]

    assert status == StatusProcessamento.CONCLUIDO
    fila.return_value.remover.assert_awaited_once_with(id_)
