from datetime import UTC, datetime
from uuid import uuid4

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil


def _perfil(descricao_llm: str | None = None) -> Perfil:
    return Perfil(
        id=uuid4(),
        aluno_id=uuid4(),
        estilo_processamento=EstiloProcessamento.ATIVO,
        percepcao=Percepcao.SENSORIAL,
        entrada=Entrada.VISUAL,
        compreensao=Compreensao.SEQUENCIAL,
        descricao_llm=descricao_llm,
        data_atualizacao=datetime.now(UTC),
    )


def test_perfil_e_criado_com_as_quatro_dimensoes() -> None:
    perfil = _perfil()

    assert perfil.estilo_processamento == EstiloProcessamento.ATIVO
    assert perfil.percepcao == Percepcao.SENSORIAL
    assert perfil.entrada == Entrada.VISUAL
    assert perfil.compreensao == Compreensao.SEQUENCIAL


def test_perfil_aceita_descricao_llm_nula() -> None:
    perfil = _perfil(descricao_llm=None)

    assert perfil.descricao_llm is None


def test_perfil_aceita_descricao_llm_preenchida() -> None:
    perfil = _perfil(descricao_llm="Perfil com forte tendência à experimentação prática.")

    assert perfil.descricao_llm == "Perfil com forte tendência à experimentação prática."
