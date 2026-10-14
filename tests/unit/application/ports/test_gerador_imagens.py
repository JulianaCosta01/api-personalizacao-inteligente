import dataclasses

import pytest

from application.ports.gerador_imagens import (
    TAMANHO_MAXIMO_DA_DESCRICAO,
    TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES,
    TAMANHO_MAXIMO_DO_TEXTO_ALTERNATIVO,
    ConceitoVisual,
    FalhaGeracaoImagem,
    IGeradorDeImagens,
    ImagemGerada,
    MotivoFalhaImagem,
    OrigemImagem,
    ResultadoGeracaoImagem,
)
from domain.shared.exceptions import EntradaInvalidaError
from tests.unit.application.ports.imagens_fixture import jpeg_valido, png_valido

_PNG = png_valido()
_JPEG = jpeg_valido()


def _conceito(**alteracoes: str) -> ConceitoVisual:
    dados = {"identificador": "c1", "descricao": "Grafo com três nós ligados", "ancora": "img-1"}
    return ConceitoVisual(**{**dados, **alteracoes})


def test_conceito_valido_guarda_os_tres_campos() -> None:
    conceito = _conceito()
    assert (conceito.identificador, conceito.ancora) == ("c1", "img-1")
    assert conceito.descricao == "Grafo com três nós ligados"


def test_conceito_e_imutavel() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _conceito().descricao = "outra"  # type: ignore[misc]


@pytest.mark.parametrize("campo", ["identificador", "ancora"])
@pytest.mark.parametrize(
    "valor",
    ["", " ", "a b", "-inicio", "com/barra", "<script>", "x" * 65, "acentuação", "a\nb", "a\x00b"],
)
def test_identificador_e_ancora_invalidos_sao_rejeitados(campo: str, valor: str) -> None:
    with pytest.raises(EntradaInvalidaError) as erro:
        _conceito(**{campo: valor})
    assert erro.value.code == "CONCEITO_VISUAL_INVALIDO"


@pytest.mark.parametrize("valor", ["a", "A1", "conceito_1", "img-2", "x" * 64])
def test_identificadores_validos_sao_aceitos(valor: str) -> None:
    assert _conceito(identificador=valor, ancora=valor).identificador == valor


@pytest.mark.parametrize(
    "descricao",
    [
        "",
        " ",
        " com espaço na ponta",
        "com espaço na ponta ",
        "linha1\nlinha2",
        "tab\taqui",
        "a\x00b",
    ],
)
def test_descricao_invalida_e_rejeitada(descricao: str) -> None:
    with pytest.raises(EntradaInvalidaError):
        _conceito(descricao=descricao)


def test_descricao_respeita_o_tamanho_maximo() -> None:
    assert _conceito(descricao="d" * TAMANHO_MAXIMO_DA_DESCRICAO)
    with pytest.raises(EntradaInvalidaError):
        _conceito(descricao="d" * (TAMANHO_MAXIMO_DA_DESCRICAO + 1))


def test_descricao_aceita_acentos_e_pontuacao() -> None:
    assert _conceito(descricao="Árvore binária: raiz, filhos (esq./dir.)")


def test_imagem_png_e_jpeg_validas_com_origem_gerada_por_padrao() -> None:
    png = ImagemGerada(_PNG, "Diagrama de um grafo")
    jpeg = ImagemGerada(_JPEG, "Foto ilustrativa")
    assert (png.origem, jpeg.origem) == (OrigemImagem.GERADA, OrigemImagem.GERADA)
    assert (png.extensao, jpeg.extensao) == ("png", "jpeg")


def test_imagem_e_imutavel() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        ImagemGerada(_PNG, "alt").texto_alternativo = "outro"  # type: ignore[misc]


@pytest.mark.parametrize(
    "conteudo",
    [b"", b"GIF89a....", b"<svg onload=alert(1)></svg>", b"%PDF-1.7", b"\x89PNG", b"texto"],
)
def test_conteudo_vazio_ou_de_formato_nao_suportado_e_rejeitado(conteudo: bytes) -> None:
    with pytest.raises(EntradaInvalidaError) as erro:
        ImagemGerada(conteudo, "alt")
    assert erro.value.code == "IMAGEM_GERADA_INVALIDA"


def test_conteudo_que_nao_e_bytes_e_rejeitado() -> None:
    with pytest.raises(EntradaInvalidaError):
        ImagemGerada("não é bytes", "alt")  # type: ignore[arg-type]


def test_imagem_respeita_o_tamanho_maximo() -> None:
    limite = png_valido(tamanho_total=TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES)
    assert len(limite) == TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES
    assert ImagemGerada(limite, "alt")
    with pytest.raises(EntradaInvalidaError):
        ImagemGerada(limite + b"0", "alt")


@pytest.mark.parametrize("alt", ["", " ", " alt", "alt ", "a\nb", "a\x00b"])
def test_texto_alternativo_invalido_e_rejeitado(alt: str) -> None:
    with pytest.raises(EntradaInvalidaError):
        ImagemGerada(_PNG, alt)


def test_texto_alternativo_respeita_o_tamanho_maximo() -> None:
    assert ImagemGerada(_PNG, "a" * TAMANHO_MAXIMO_DO_TEXTO_ALTERNATIVO)
    with pytest.raises(EntradaInvalidaError):
        ImagemGerada(_PNG, "a" * (TAMANHO_MAXIMO_DO_TEXTO_ALTERNATIVO + 1))


def test_origem_so_aceita_gerada() -> None:
    assert list(OrigemImagem) == [OrigemImagem.GERADA]
    with pytest.raises(EntradaInvalidaError):
        ImagemGerada(_PNG, "alt", origem="original")  # type: ignore[arg-type]


def test_falha_guarda_o_conceito_e_um_motivo_fechado() -> None:
    falha = FalhaGeracaoImagem("c1", MotivoFalhaImagem.TIMEOUT)
    assert falha.identificador_do_conceito == "c1"
    assert falha.motivo is MotivoFalhaImagem.TIMEOUT


def test_todos_os_motivos_existem_e_sao_texto_estavel() -> None:
    assert {m.value for m in MotivoFalhaImagem} == {
        "timeout",
        "indisponivel",
        "limite_excedido",
        "conteudo_recusado",
        "resposta_invalida",
        "orcamento_esgotado",
    }


@pytest.mark.parametrize("identificador", ["", "a b", "<x>", "x" * 65])
def test_falha_com_identificador_invalido_e_rejeitada(identificador: str) -> None:
    with pytest.raises(EntradaInvalidaError) as erro:
        FalhaGeracaoImagem(identificador, MotivoFalhaImagem.TIMEOUT)
    assert erro.value.code == "FALHA_DE_IMAGEM_INVALIDA"


def test_falha_com_motivo_em_texto_livre_e_rejeitada() -> None:
    with pytest.raises(EntradaInvalidaError):
        FalhaGeracaoImagem("c1", "erro 500 com detalhes da requisição")  # type: ignore[arg-type]


class _GeradorFalso:
    def __init__(self, resultado: ResultadoGeracaoImagem) -> None:
        self._resultado = resultado
        self.recebidos: list[ConceitoVisual] = []

    async def gerar(self, conceito: ConceitoVisual) -> ResultadoGeracaoImagem:
        self.recebidos.append(conceito)
        return self._resultado


async def test_contrato_devolve_imagem_em_caso_de_sucesso() -> None:
    gerador: IGeradorDeImagens = _GeradorFalso(ImagemGerada(_PNG, "alt"))
    resultado = await gerador.gerar(_conceito())
    assert isinstance(resultado, ImagemGerada)


async def test_contrato_representa_falha_sem_lancar_excecao() -> None:
    gerador: IGeradorDeImagens = _GeradorFalso(FalhaGeracaoImagem("c1", MotivoFalhaImagem.TIMEOUT))
    resultado = await gerador.gerar(_conceito())
    assert isinstance(resultado, FalhaGeracaoImagem)
    assert resultado.motivo is MotivoFalhaImagem.TIMEOUT
