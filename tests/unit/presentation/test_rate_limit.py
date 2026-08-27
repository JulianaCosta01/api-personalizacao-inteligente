from presentation.api.rate_limit import LimitadorDeTaxa


class _RelogioFalso:
    def __init__(self, inicio: float = 0.0) -> None:
        self.agora = inicio

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


def test_permite_ate_o_limite_dentro_da_janela() -> None:
    relogio = _RelogioFalso()
    limitador = LimitadorDeTaxa(limite=3, janela_segundos=60.0, relogio=relogio)

    assert limitador.permitir("token-x") is True
    assert limitador.permitir("token-x") is True
    assert limitador.permitir("token-x") is True


def test_bloqueia_a_requisicao_que_excede_o_limite() -> None:
    relogio = _RelogioFalso()
    limitador = LimitadorDeTaxa(limite=2, janela_segundos=60.0, relogio=relogio)

    assert limitador.permitir("token-x") is True
    assert limitador.permitir("token-x") is True
    assert limitador.permitir("token-x") is False


def test_janela_expira_e_libera_novas_requisicoes() -> None:
    relogio = _RelogioFalso()
    limitador = LimitadorDeTaxa(limite=1, janela_segundos=60.0, relogio=relogio)

    assert limitador.permitir("token-x") is True
    assert limitador.permitir("token-x") is False

    relogio.avancar(60.0)  # janela seguinte

    assert limitador.permitir("token-x") is True


def test_janela_nao_expira_um_instante_antes_do_limite_de_tempo() -> None:
    relogio = _RelogioFalso()
    limitador = LimitadorDeTaxa(limite=1, janela_segundos=60.0, relogio=relogio)

    assert limitador.permitir("token-x") is True

    relogio.avancar(59.999)

    assert limitador.permitir("token-x") is False


def test_chaves_diferentes_tem_contadores_independentes() -> None:
    relogio = _RelogioFalso()
    limitador = LimitadorDeTaxa(limite=1, janela_segundos=60.0, relogio=relogio)

    assert limitador.permitir("token-a") is True
    assert limitador.permitir("token-b") is True
    # token-a já esgotou o próprio limite; token-b não é afetado por isso.
    assert limitador.permitir("token-a") is False
    assert limitador.permitir("token-b") is False
