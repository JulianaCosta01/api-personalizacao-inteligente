import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import pytest

from application.ports.gerador_imagens import (
    ConceitoVisual,
    FalhaGeracaoImagem,
    ImagemGerada,
    MotivoFalhaImagem,
    ResultadoGeracaoImagem,
)
from infrastructure.imagens import gerador_do_material
from infrastructure.imagens.gerador_do_material import GeradorDeImagensDoMaterial
from infrastructure.imagens.prazo_total import PrazoTotal
from tests.unit.application.ports.imagens_fixture import png_valido

_DESCRICAO_SECRETA = "Descricao-visual-que-nao-pode-ir-para-o-log"


class _Relogio:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


def _conceito(identificador: str) -> ConceitoVisual:
    return ConceitoVisual(identificador, _DESCRICAO_SECRETA, identificador)


def _conceitos(*identificadores: str) -> list[ConceitoVisual]:
    return [_conceito(i) for i in identificadores]


def _imagem() -> ImagemGerada:
    return ImagemGerada(png_valido(), "texto alternativo")


class _GeradorFalso:
    """Gerador simulado: cada chamada consome o próximo comportamento da lista.

    Um comportamento é um valor pronto, uma função (conceito) -> resultado ou "travar".
    """

    def __init__(self, *comportamentos: Any, relogio: _Relogio | None = None, custo: float = 0):
        self._comportamentos = list(comportamentos)
        self._relogio = relogio
        self._custo = custo
        self.chamadas: list[str] = []
        self.iniciou = asyncio.Event()

    async def gerar(self, conceito: ConceitoVisual) -> ResultadoGeracaoImagem:
        self.chamadas.append(conceito.identificador)
        self.iniciou.set()
        if self._relogio is not None:
            self._relogio.avancar(self._custo)
        comportamento = self._comportamentos.pop(0) if self._comportamentos else _imagem()
        if comportamento == "travar":
            await asyncio.Event().wait()
        if callable(comportamento):
            return comportamento(conceito)
        return comportamento


@pytest.fixture
def limites_aplicados(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    # Registra o timeout efetivo passado a cada chamada, sem alterar o comportamento.
    registrados: list[float] = []
    original = asyncio.wait_for

    async def espiao(aw: Any, timeout: float | None = None) -> Any:
        assert timeout is not None
        registrados.append(timeout)
        return await original(aw, timeout=timeout)

    monkeypatch.setattr(gerador_do_material.asyncio, "wait_for", espiao)
    return registrados


def _orquestrador(
    gerador: _GeradorFalso,
    prazo: PrazoTotal,
    *,
    maximo: int = 5,
    por_imagem: float = 60.0,
    individual: float | None = None,
    margem: float = 10.0,
) -> GeradorDeImagensDoMaterial:
    return GeradorDeImagensDoMaterial(gerador, prazo, maximo, por_imagem, individual, margem)


def _motivos(resultados: tuple[ResultadoGeracaoImagem, ...]) -> list[str]:
    return [r.motivo.value if isinstance(r, FalhaGeracaoImagem) else "ok" for r in resultados]


# --- orçamento compartilhado -------------------------------------------------------------------


async def test_o_orcamento_e_compartilhado_entre_as_imagens(limites_aplicados: list[float]) -> None:
    relogio = _Relogio()
    gerador = _GeradorFalso(relogio=relogio, custo=30)
    orq = _orquestrador(gerador, PrazoTotal(100, relogio))

    resultados = await orq.gerar(_conceitos("a", "b", "c"))

    assert _motivos(resultados) == ["ok", "ok", "ok"]
    # 100 -> 70 -> 40: o limite de cada chamada é o que sobra do MESMO prazo (teto de 60 s).
    assert limites_aplicados == [60.0, 60.0, 40.0]


async def test_o_prazo_nao_reinicia_a_cada_imagem(limites_aplicados: list[float]) -> None:
    relogio = _Relogio()
    gerador = _GeradorFalso(relogio=relogio, custo=40)
    orq = _orquestrador(gerador, PrazoTotal(100, relogio))

    resultados = await orq.gerar(_conceitos("a", "b", "c", "d"))

    # 100 -> 60 -> 20 -> (restam -20): a terceira ainda cabe; a quarta já não.
    assert gerador.chamadas == ["a", "b", "c"]
    assert limites_aplicados == [60.0, 60.0, 20.0]
    assert _motivos(resultados) == ["ok", "ok", "ok", "orcamento_esgotado"]


async def test_orcamento_esgotado_antes_da_primeira_chamada() -> None:
    relogio = _Relogio()
    prazo = PrazoTotal(100, relogio)
    relogio.avancar(100)
    gerador = _GeradorFalso()

    resultados = await _orquestrador(gerador, prazo).gerar(_conceitos("a", "b"))

    assert gerador.chamadas == []
    assert _motivos(resultados) == ["orcamento_esgotado", "orcamento_esgotado"]
    assert [
        r.identificador_do_conceito for r in resultados if isinstance(r, FalhaGeracaoImagem)
    ] == [
        "a",
        "b",
    ]


async def test_chamada_em_curso_e_interrompida_quando_o_orcamento_expira() -> None:
    gerador = _GeradorFalso("travar")
    orq = _orquestrador(gerador, PrazoTotal(0.2), por_imagem=30, margem=0.01)

    inicio = time.monotonic()
    resultados = await orq.gerar(_conceitos("a", "b"))

    assert time.monotonic() - inicio < 2
    assert gerador.chamadas == ["a"]  # a segunda nem foi iniciada
    assert _motivos(resultados) == ["orcamento_esgotado", "orcamento_esgotado"]


async def test_estouro_do_limite_da_propria_imagem_e_timeout_e_segue_para_a_proxima() -> None:
    gerador = _GeradorFalso("travar")
    orq = _orquestrador(gerador, PrazoTotal(100), por_imagem=0.05, margem=0.01)

    resultados = await orq.gerar(_conceitos("a", "b"))

    assert gerador.chamadas == ["a", "b"]
    assert _motivos(resultados) == ["timeout", "ok"]


async def test_relogio_que_avanca_durante_a_chamada_preserva_a_imagem_gerada() -> None:
    relogio = _Relogio()
    gerador = _GeradorFalso(relogio=relogio, custo=500)  # estoura o prazo dentro da 1ª chamada
    orq = _orquestrador(gerador, PrazoTotal(100, relogio))

    resultados = await orq.gerar(_conceitos("a", "b"))

    assert gerador.chamadas == ["a"]
    assert _motivos(resultados) == ["ok", "orcamento_esgotado"]
    assert isinstance(resultados[0], ImagemGerada)


# --- limites antes de chamar o provedor --------------------------------------------------------


async def test_maximo_e_aplicado_antes_de_qualquer_chamada() -> None:
    gerador = _GeradorFalso()
    orq = _orquestrador(gerador, PrazoTotal(100, _Relogio()), maximo=2)

    resultados = await orq.gerar(_conceitos("a", "b", "c", "d", "e"))

    assert gerador.chamadas == ["a", "b"]
    assert len(resultados) == 2  # os excedentes nem viram resultado


async def test_conceitos_duplicados_sao_removidos_antes_das_chamadas() -> None:
    gerador = _GeradorFalso()
    orq = _orquestrador(gerador, PrazoTotal(100, _Relogio()), maximo=5)

    resultados = await orq.gerar(_conceitos("a", "a", "b", "a", "b", "c"))

    assert gerador.chamadas == ["a", "b", "c"]
    assert len(resultados) == 3


async def test_duplicados_nao_consomem_vagas_do_maximo() -> None:
    gerador = _GeradorFalso()
    orq = _orquestrador(gerador, PrazoTotal(100, _Relogio()), maximo=2)

    await orq.gerar(_conceitos("a", "a", "b", "c"))

    assert gerador.chamadas == ["a", "b"]


@pytest.mark.parametrize("maximo", [0, -1, -10])
async def test_maximo_menor_que_um_nao_chama_o_provedor(maximo: int) -> None:
    gerador = _GeradorFalso()
    orq = _orquestrador(gerador, PrazoTotal(100, _Relogio()), maximo=maximo)

    assert await orq.gerar(_conceitos("a", "b")) == ()
    assert gerador.chamadas == []


async def test_lista_vazia_nao_chama_o_provedor() -> None:
    gerador = _GeradorFalso()
    assert await _orquestrador(gerador, PrazoTotal(100, _Relogio())).gerar([]) == ()
    assert gerador.chamadas == []


async def test_menos_de_dez_segundos_restantes_nao_inicia_a_imagem() -> None:
    relogio = _Relogio()
    prazo = PrazoTotal(100, relogio)
    relogio.avancar(91)  # restam 9 s
    gerador = _GeradorFalso()
    orq = GeradorDeImagensDoMaterial(gerador, prazo, 5, 60.0)  # margem padrão

    resultados = await orq.gerar(_conceitos("a"))

    assert gerador.chamadas == []
    assert _motivos(resultados) == ["orcamento_esgotado"]


async def test_exatamente_dez_segundos_restantes_ainda_inicia(
    limites_aplicados: list[float],
) -> None:
    relogio = _Relogio()
    prazo = PrazoTotal(100, relogio)
    relogio.avancar(90)  # restam 10 s
    gerador = _GeradorFalso()
    orq = GeradorDeImagensDoMaterial(gerador, prazo, 5, 60.0)

    resultados = await orq.gerar(_conceitos("a"))

    assert gerador.chamadas == ["a"]
    assert limites_aplicados == [10.0]
    assert _motivos(resultados) == ["ok"]


async def test_o_limite_da_chamada_e_o_menor_entre_restante_total_e_individual(
    limites_aplicados: list[float],
) -> None:
    relogio = _Relogio()
    gerador = _GeradorFalso()
    orq = _orquestrador(gerador, PrazoTotal(100, relogio), por_imagem=60, individual=25)
    await orq.gerar(_conceitos("a"))

    orq2 = _orquestrador(_GeradorFalso(), PrazoTotal(100, relogio), por_imagem=60, individual=90)
    await orq2.gerar(_conceitos("a"))

    orq3 = _orquestrador(_GeradorFalso(), PrazoTotal(30, relogio), por_imagem=60, individual=90)
    await orq3.gerar(_conceitos("a"))

    assert limites_aplicados == [25.0, 60.0, 30.0]


# --- falhas ------------------------------------------------------------------------------------


async def test_falha_individual_nao_apaga_os_resultados_anteriores_nem_os_seguintes() -> None:
    falha = FalhaGeracaoImagem("b", MotivoFalhaImagem.INDISPONIVEL)
    gerador = _GeradorFalso(_imagem(), falha, _imagem())
    orq = _orquestrador(gerador, PrazoTotal(100, _Relogio()))

    resultados = await orq.gerar(_conceitos("a", "b", "c"))

    assert gerador.chamadas == ["a", "b", "c"]
    assert _motivos(resultados) == ["ok", "indisponivel", "ok"]
    assert isinstance(resultados[0], ImagemGerada) and isinstance(resultados[2], ImagemGerada)


async def test_cancelamento_externo_e_propagado() -> None:
    gerador = _GeradorFalso("travar")
    orq = _orquestrador(gerador, PrazoTotal(100), por_imagem=30)

    tarefa = asyncio.create_task(orq.gerar(_conceitos("a", "b")))
    await asyncio.wait_for(gerador.iniciou.wait(), timeout=2)
    tarefa.cancel()

    with pytest.raises(asyncio.CancelledError):
        await tarefa
    assert gerador.chamadas == ["a"]  # nada foi iniciado depois do cancelamento


async def test_erro_de_programacao_do_gerador_nao_e_escondido() -> None:
    def quebra(_: ConceitoVisual) -> ResultadoGeracaoImagem:
        raise RuntimeError("defeito")

    orq = _orquestrador(_GeradorFalso(quebra), PrazoTotal(100, _Relogio()))
    with pytest.raises(RuntimeError, match="defeito"):
        await orq.gerar(_conceitos("a"))


async def test_resultado_fora_do_contrato_e_um_erro_de_programacao() -> None:
    orq = _orquestrador(_GeradorFalso("texto qualquer"), PrazoTotal(100, _Relogio()))
    with pytest.raises(TypeError):
        await orq.gerar(_conceitos("a"))


# --- logs --------------------------------------------------------------------------------------


async def test_logs_nao_trazem_descricao_nem_conteudo(caplog: pytest.LogCaptureFixture) -> None:
    falha = FalhaGeracaoImagem("b", MotivoFalhaImagem.CONTEUDO_RECUSADO)
    gerador = _GeradorFalso(_imagem(), falha, "travar")
    orq = _orquestrador(gerador, PrazoTotal(100), por_imagem=0.05, margem=0.01)

    with caplog.at_level(logging.DEBUG):
        await orq.gerar(_conceitos("a", "b", "c"))

    assert _DESCRICAO_SECRETA not in caplog.text
    assert "texto alternativo" not in caplog.text
    assert "1 gerada(s), 2 falha(s)" in caplog.text


# --- configuração do orquestrador --------------------------------------------------------------


@pytest.mark.parametrize(
    "ajuste",
    [
        lambda: {"por_imagem": 0},
        lambda: {"por_imagem": -1},
        lambda: {"individual": 0},
        lambda: {"individual": -5},
        lambda: {"margem": -1},
    ],
)
def test_parametros_invalidos_sao_rejeitados(ajuste: Callable[[], dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        _orquestrador(_GeradorFalso(), PrazoTotal(100, _Relogio()), **ajuste())
