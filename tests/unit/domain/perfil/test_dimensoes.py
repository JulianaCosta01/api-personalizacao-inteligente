from enum import StrEnum

import pytest

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao


def test_estilo_processamento_aceita_os_dois_polos() -> None:
    assert EstiloProcessamento("Ativo") == EstiloProcessamento.ATIVO
    assert EstiloProcessamento("Reflexivo") == EstiloProcessamento.REFLEXIVO


def test_percepcao_aceita_os_dois_polos() -> None:
    assert Percepcao("Sensorial") == Percepcao.SENSORIAL
    assert Percepcao("Intuitivo") == Percepcao.INTUITIVO


def test_entrada_aceita_os_dois_polos() -> None:
    assert Entrada("Visual") == Entrada.VISUAL
    assert Entrada("Verbal") == Entrada.VERBAL


def test_compreensao_aceita_os_dois_polos() -> None:
    assert Compreensao("Sequencial") == Compreensao.SEQUENCIAL
    assert Compreensao("Global") == Compreensao.GLOBAL


@pytest.mark.parametrize("enum_cls", [EstiloProcessamento, Percepcao, Entrada, Compreensao])
def test_valor_fora_do_par_valido_e_rejeitado(enum_cls: type[StrEnum]) -> None:
    with pytest.raises(ValueError):
        enum_cls("valor_invalido")
