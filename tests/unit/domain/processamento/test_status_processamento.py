import pytest

from domain.processamento.status_processamento import StatusProcessamento


def test_aceita_os_quatro_estados() -> None:
    assert StatusProcessamento("pendente") == StatusProcessamento.PENDENTE
    assert StatusProcessamento("em_processamento") == StatusProcessamento.EM_PROCESSAMENTO
    assert StatusProcessamento("concluido") == StatusProcessamento.CONCLUIDO
    assert StatusProcessamento("erro") == StatusProcessamento.ERRO


def test_valor_fora_do_conjunto_e_rejeitado() -> None:
    with pytest.raises(ValueError):
        StatusProcessamento("cancelado")
