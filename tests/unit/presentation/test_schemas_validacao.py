from uuid import uuid4

import pytest
from pydantic import ValidationError

from infrastructure.database.material.material_repository import escapar_curingas_like
from presentation.api.routers.material import nome_de_arquivo_seguro
from presentation.api.schemas.acesso import AcessoAtualizacaoRequest
from presentation.api.schemas.aluno import (
    AlunoAtualizacaoRequest,
    AlunoCadastroRequest,
    AlunoExistenteResponse,
)
from presentation.api.schemas.log import LogCadastroRequest


def _aluno(**campos: object) -> AlunoCadastroRequest:
    base = {"nome": "Maria", "email": "maria@ufma.br", "matricula": "20240001"}
    return AlunoCadastroRequest(**{**base, **campos})


def test_aluno_valido_e_aceito_nos_limites() -> None:
    assert _aluno(nome="n" * 255, matricula="m" * 20).matricula == "m" * 20


@pytest.mark.parametrize(
    "campos",
    [
        {"nome": "n" * 256},
        {"nome": ""},
        {"matricula": "m" * 21},
        {"matricula": ""},
        {"email": "a" * 250 + "@x.com"},
    ],
)
def test_aluno_acima_dos_limites_das_colunas_e_recusado(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _aluno(**campos)


def test_atualizacao_de_aluno_tem_os_mesmos_limites() -> None:
    with pytest.raises(ValidationError):
        AlunoAtualizacaoRequest(nome="n" * 256, email="a@b.com")


def test_log_limita_acao_e_descricao() -> None:
    base = {"aluno_id": uuid4(), "acao": "abriu"}
    assert LogCadastroRequest(**base, descricao="d" * 2000).descricao is not None
    for invalido in ({"acao": "a" * 101}, {"acao": ""}, {"descricao": "d" * 2001}):
        with pytest.raises(ValidationError):
            LogCadastroRequest(**{**base, **invalido})


@pytest.mark.parametrize("tempo", [-1, -(10**12), 86_401, 10**30])
def test_acesso_recusa_incremento_de_tempo_negativo_ou_absurdo(tempo: int) -> None:
    with pytest.raises(ValidationError):
        AcessoAtualizacaoRequest(
            aluno_id=uuid4(),
            tempo_leitura_incremento_segundos=tempo,
            porcentagem_leitura=0.5,
            download_realizado=False,
        )


@pytest.mark.parametrize("tempo", [0, 30, 86_400])
def test_acesso_aceita_incremento_dentro_do_intervalo(tempo: int) -> None:
    pedido = AcessoAtualizacaoRequest(
        aluno_id=uuid4(),
        tempo_leitura_incremento_segundos=tempo,
        porcentagem_leitura=0.5,
        download_realizado=True,
    )
    assert pedido.tempo_leitura_incremento_segundos == tempo


def test_resposta_de_matricula_existente_expoe_somente_id_e_grupo() -> None:
    assert set(AlunoExistenteResponse.model_fields) == {"id", "grupo_experimental"}


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (None, "material.pdf"),
        ("", "material.pdf"),
        ("aula.pdf", "aula.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\aula.pdf", "aula.pdf"),
        ("a\x00b\r\n.pdf", "ab.pdf"),
        ("/", "material.pdf"),
        ("x" * 400 + ".pdf", "x" * 255),
    ],
)
def test_nome_de_arquivo_seguro(entrada: str | None, esperado: str) -> None:
    assert nome_de_arquivo_seguro(entrada) == esperado


def test_curingas_do_like_valem_como_texto() -> None:
    assert escapar_curingas_like("100%_ok\\") == "100\\%\\_ok\\\\"
