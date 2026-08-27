import pytest

from domain.acesso.status_leitura import StatusLeitura


def test_aceita_os_tres_estados() -> None:
    assert StatusLeitura("NAO_INICIADO") == StatusLeitura.NAO_INICIADO
    assert StatusLeitura("EM_ANDAMENTO") == StatusLeitura.EM_ANDAMENTO
    assert StatusLeitura("CONCLUIDO") == StatusLeitura.CONCLUIDO


def test_valor_fora_do_conjunto_e_rejeitado() -> None:
    with pytest.raises(ValueError):
        StatusLeitura("PAUSADO")
