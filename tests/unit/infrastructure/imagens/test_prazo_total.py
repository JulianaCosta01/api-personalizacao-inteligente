import time

import pytest

from infrastructure.imagens.prazo_total import MARGEM_MINIMA_PARA_INICIAR_SEGUNDOS, PrazoTotal


class _Relogio:
    def __init__(self, inicio: float = 1000.0) -> None:
        self.agora = inicio
        self.leituras = 0

    def __call__(self) -> float:
        self.leituras += 1
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


def test_margem_minima_para_iniciar_e_de_dez_segundos() -> None:
    assert MARGEM_MINIMA_PARA_INICIAR_SEGUNDOS == 10.0


def test_prazo_novo_tem_o_total_restante_e_nao_esta_esgotado() -> None:
    prazo = PrazoTotal(150, _Relogio())
    assert prazo.total == 150.0
    assert prazo.restante() == 150.0
    assert prazo.esgotado() is False


def test_o_restante_diminui_com_o_tempo_e_e_compartilhado_entre_consultas() -> None:
    relogio = _Relogio()
    prazo = PrazoTotal(150, relogio)
    relogio.avancar(40)
    assert prazo.restante() == 110.0
    relogio.avancar(60)
    assert prazo.restante() == 50.0
    assert prazo.restante() == 50.0  # consultar não consome nem reinicia


def test_o_inicio_e_lido_uma_unica_vez_na_criacao() -> None:
    relogio = _Relogio()
    prazo = PrazoTotal(100, relogio)
    assert relogio.leituras == 1
    relogio.avancar(30)
    prazo.restante()
    prazo.esgotado()
    relogio.avancar(30)
    assert prazo.restante() == 40.0  # nunca reiniciou a partir de uma nova consulta


def test_prazo_esgota_exatamente_no_limite() -> None:
    relogio = _Relogio()
    prazo = PrazoTotal(10, relogio)
    relogio.avancar(9.999)
    assert prazo.esgotado() is False
    relogio.avancar(0.001)
    assert prazo.restante() == 0.0
    assert prazo.esgotado() is True


def test_depois_de_esgotado_o_restante_fica_em_zero_e_nao_fica_negativo() -> None:
    relogio = _Relogio()
    prazo = PrazoTotal(10, relogio)
    relogio.avancar(1_000_000)
    assert prazo.restante() == 0.0
    assert prazo.esgotado() is True


def test_relogio_que_anda_para_tras_nao_devolve_tempo() -> None:
    relogio = _Relogio()
    prazo = PrazoTotal(100, relogio)
    relogio.avancar(-50)
    assert prazo.restante() == 100.0  # nunca passa do total
    relogio.avancar(50 + 30)
    assert prazo.restante() == 70.0


def test_prazo_aceita_inteiro_e_decimal() -> None:
    assert PrazoTotal(5, _Relogio()).total == 5.0
    assert PrazoTotal(0.5, _Relogio()).total == 0.5


@pytest.mark.parametrize("valor", [0, -1, -0.001, float("nan"), float("inf"), float("-inf")])
def test_prazo_invalido_e_rejeitado(valor: float) -> None:
    with pytest.raises(ValueError):
        PrazoTotal(valor, _Relogio())


@pytest.mark.parametrize("valor", ["10", None, True])
def test_prazo_nao_numerico_e_rejeitado(valor: object) -> None:
    with pytest.raises(TypeError):
        PrazoTotal(valor, _Relogio())  # type: ignore[arg-type]


def test_relogio_padrao_e_o_monotonic_e_o_prazo_expira_de_verdade() -> None:
    prazo = PrazoTotal(0.05)
    assert prazo.esgotado() is False
    time.sleep(0.08)
    assert prazo.esgotado() is True
