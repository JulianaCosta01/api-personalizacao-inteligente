from datetime import timedelta

import pytest

from application.processamento.politica_de_repeticao import PoliticaDeRepeticao


def test_atraso_cresce_de_forma_exponencial_ate_o_teto() -> None:
    politica = PoliticaDeRepeticao(10, 30.0, 300.0, 0.0)

    atrasos = [politica.atraso_apos(n) for n in range(1, 7)]

    assert atrasos == [timedelta(seconds=s) for s in (30, 60, 120, 240, 300, 300)]


def test_jitter_so_reduz_o_atraso_e_nunca_passa_do_teto() -> None:
    politica = PoliticaDeRepeticao(10, 30.0, 300.0, 0.2)

    sem_reducao = politica.atraso_apos(1, aleatorio=lambda: 0.0)
    maxima_reducao = politica.atraso_apos(1, aleatorio=lambda: 1.0)

    assert sem_reducao == timedelta(seconds=30)
    assert maxima_reducao == timedelta(seconds=24)
    assert politica.atraso_apos(9, aleatorio=lambda: 0.0) <= timedelta(seconds=300)


def test_atraso_nunca_e_zero_nem_negativo() -> None:
    politica = PoliticaDeRepeticao(5, 30.0, 300.0, 0.2)

    assert all(politica.atraso_apos(n, aleatorio=lambda: 0.999) > timedelta(0) for n in range(0, 6))


def test_pior_caso_total_para_tres_reivindicacoes_e_90_segundos() -> None:
    # Duas esperas entre três reivindicações: 30 s + 60 s.
    assert PoliticaDeRepeticao(3, 30.0, 300.0).atraso_maximo_total() == timedelta(seconds=90)


def test_pior_caso_total_respeita_o_teto() -> None:
    assert PoliticaDeRepeticao(6, 30.0, 100.0).atraso_maximo_total() == timedelta(
        seconds=30 + 60 + 100 + 100 + 100
    )


@pytest.mark.parametrize(("realizadas", "permite"), [(0, True), (1, True), (2, True), (3, False)])
def test_permite_nova_tentativa_so_abaixo_do_limite(realizadas: int, permite: bool) -> None:
    assert PoliticaDeRepeticao(3).permite_nova_tentativa(realizadas) is permite


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tentativas_maximas": 0},
        {"tentativas_maximas": 3, "atraso_base_segundos": 0},
        {"tentativas_maximas": 3, "atraso_base_segundos": 60.0, "atraso_maximo_segundos": 30.0},
        {"tentativas_maximas": 3, "jitter_proporcional": 1.0},
        {"tentativas_maximas": 3, "jitter_proporcional": -0.1},
    ],
)
def test_configuracao_invalida_e_rejeitada(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        PoliticaDeRepeticao(**kwargs)  # type: ignore[arg-type]
