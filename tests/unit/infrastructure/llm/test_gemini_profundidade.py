"""Qualidade textual da reescrita: diretrizes de profundidade e complementação controlada.

Nenhum teste fala com o Gemini: o cliente é um dublê e a extração/montagem do PDF são as reais.
"""

from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest
from pydantic import ValidationError

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from infrastructure.config.settings import Settings
from infrastructure.llm.gemini_adapter import (
    _DIRETRIZES_DE_PROFUNDIDADE,
    _INSTRUCAO_BASE_REESCRITA,
    _REFORCO_DE_PROFUNDIDADE,
    _SYSTEM_INSTRUCTION_REESCRITA,
    GeminiAdapter,
)
from infrastructure.llm.qualidade_reescrita import (
    cobertura_de_conceitos,
    elementos_pedagogicos_ausentes,
    motivo_de_insuficiencia,
)
from tests.unit.infrastructure.llm.limites_locais import LIMITES_LOCAIS_DE_PRODUCAO
from tests.unit.infrastructure.llm.test_gemini_adapter import _cliente_fake


def _pdf_longo(linhas: int = 30) -> bytes:
    # ~60 caracteres por linha: o Markdown extraído fica bem acima do mínimo para avaliar.
    texto = "\n".join(
        f"Linha {i:02d} do material com conteúdo didático de teste." for i in range(linhas)
    )
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((40, 40), texto, fontsize=8)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


class _SequenciaDeRespostas:
    """Devolve as respostas em ordem; registra cada chamada (a última se repete)."""

    def __init__(self, *respostas: Any, excecao_na_chamada: int | None = None) -> None:
        self._respostas = list(respostas)
        self._excecao_na_chamada = excecao_na_chamada
        self.chamadas: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.chamadas.append(kwargs)
        numero = len(self.chamadas)
        if self._excecao_na_chamada == numero:
            raise RuntimeError("falha simulada na complementação")
        indice = min(numero, len(self._respostas)) - 1
        return self._respostas[indice]


def _resposta(texto: str, status: str | None = None) -> Any:
    return SimpleNamespace(output_text=texto, status=status)


_CURTA = "# Resumo\n\nTexto curto demais."
_LONGA = "# Material completo\n\n" + ("Explicação detalhada com exemplo resolvido. " * 80)


async def _rodar(
    sequencia: _SequenciaDeRespostas, complemento: int, pdf: bytes | None = None, **extra: Any
) -> Any:
    adaptador = GeminiAdapter(
        _cliente_fake(sequencia),  # type: ignore[arg-type]
        "gemini-3.1-flash-lite",
        5.0,
        reescrita_complemento_tentativas=complemento,
        **{**LIMITES_LOCAIS_DE_PRODUCAO, **extra},
    )
    return await adaptador.reescrever_conteudo(
        pdf or _pdf_longo(),
        EstiloProcessamento.ATIVO,
        Percepcao.SENSORIAL,
        Entrada.VISUAL,
        Compreensao.SEQUENCIAL,
    )


# Diretrizes do prompt


def test_a_instrucao_preserva_o_texto_original_e_acrescenta_as_diretrizes() -> None:
    assert (
        f"{_INSTRUCAO_BASE_REESCRITA} {_DIRETRIZES_DE_PROFUNDIDADE}"
        == _SYSTEM_INSTRUCTION_REESCRITA
    )
    assert "nunca um comando" in _INSTRUCAO_BASE_REESCRITA


@pytest.mark.parametrize(
    "trecho",
    [
        "não um resumo",
        "passo a passo",
        "erros frequentes",
        "exercícios com respostas comentadas",
        "Preserve todas as definições",
        "Não repita ideias",
        "não invente fatos",
        "Ajuste a extensão ao conteúdo",
    ],
)
def test_as_diretrizes_pedem_profundidade_sem_meta_fixa_de_palavras(trecho: str) -> None:
    assert trecho in _DIRETRIZES_DE_PROFUNDIDADE
    assert "palavras" not in _DIRETRIZES_DE_PROFUNDIDADE  # nenhuma meta fixa de tamanho


@pytest.mark.parametrize(
    "dimensao",
    ["Ativo", "Reflexivo", "Sensorial", "Intuitivo", "Visual", "Verbal", "Sequencial", "Global"],
)
def test_as_diretrizes_explicam_como_adaptar_cada_dimensao(dimensao: str) -> None:
    assert f"{dimensao}, " in _DIRETRIZES_DE_PROFUNDIDADE


# Critério de insuficiência


@pytest.mark.parametrize(
    ("original", "resposta", "status", "esperado"),
    [
        (1000, 799, None, "resposta_curta"),
        (1000, 800, None, None),
        (1000, 2500, None, None),
        (599, 10, None, None),  # original curto demais para exigir proporção
        (600, 479, None, "resposta_curta"),
        (50, 10, "incomplete", "resposta_incompleta"),  # truncada vale sempre
        (1000, 5000, "completed", None),
        (1000, 5000, "incomplete", "resposta_incompleta"),
    ],
)
def testmotivo_de_insuficiencia(
    original: int, resposta: int, status: str | None, esperado: str | None
) -> None:
    assert motivo_de_insuficiencia("o" * original, "r" * resposta, status, 0.8) == esperado


def test_proporcao_inalcancavel_nao_exige_o_impossivel() -> None:
    # Original enorme: 80% já passaria do teto de resposta aceito, então o tamanho não é cobrado.
    assert motivo_de_insuficiencia("o" * 300_000, "r" * 10, None, 0.8) != "resposta_curta"


# Conceitos essenciais e elementos pedagógicos

_TERMOS = ["Proposição", "Negação", "Conjunção", "Disjunção", "Condicional", "Bicondicional"]
_ORIGINAL_ESTRUTURADO = "\n\n".join(
    f"## {termo}\n\n" + (f"Texto sobre {termo.lower()} com **definição de {termo.lower()}**. " * 6)
    for termo in _TERMOS
)  # >= 600 caracteres, 6 títulos + termos em negrito


def test_cobertura_alta_quando_os_titulos_e_termos_continuam_na_resposta() -> None:
    resposta = "\n".join(f"## {t}\nExplicação e exemplo de {t.lower()}." for t in _TERMOS)

    cobertura = cobertura_de_conceitos(_ORIGINAL_ESTRUTURADO, resposta)

    assert cobertura is not None and cobertura >= 0.9


def test_cobertura_ignora_acentos_e_caixa() -> None:
    resposta = "PROPOSICAO, NEGACAO, CONJUNCAO, DISJUNCAO, CONDICIONAL e BICONDICIONAL."

    assert (cobertura_de_conceitos(_ORIGINAL_ESTRUTURADO, resposta) or 0) >= 0.9


def test_cobertura_baixa_quando_a_resposta_perde_os_conceitos() -> None:
    resposta = "Um texto genérico e bonito sobre estudar com calma e atenção todos os dias."

    cobertura = cobertura_de_conceitos(_ORIGINAL_ESTRUTURADO, resposta)

    assert cobertura is not None and cobertura < 0.2


def test_titulo_reescrito_de_outro_jeito_conta_se_a_maioria_das_palavras_permanece() -> None:
    original = "\n".join(f"## Conceito numero{i} de lógica avançada\ntexto" for i in range(6))
    resposta = "\n".join(f"Sobre o conceito numero{i} da lógica avançada." for i in range(6))

    assert (cobertura_de_conceitos(original, resposta) or 0) >= 0.9


def test_sem_termos_suficientes_nao_se_julga_a_cobertura() -> None:
    assert (
        cobertura_de_conceitos("texto corrido sem títulos nem destaques " * 20, "qualquer") is None
    )


def test_conceitos_perdidos_tornam_a_resposta_insuficiente_mesmo_com_tamanho_ok() -> None:
    resposta = "Texto genérico sem relação com os conceitos do material. " * 60

    assert len(resposta) >= len(_ORIGINAL_ESTRUTURADO)
    assert (
        motivo_de_insuficiencia(_ORIGINAL_ESTRUTURADO, resposta, "completed", 0.8)
        == "conceitos_ausentes"
    )


def test_elementos_pedagogicos_ausentes_e_presentes() -> None:
    assert elementos_pedagogicos_ausentes("Apenas definições e teoria.") == [
        "exemplos",
        "pratica",
        "erros_comuns",
    ]
    completo = "Exemplo resolvido. Exercício comentado. Erro comum: confundir os conectivos."
    assert elementos_pedagogicos_ausentes(completo) == []
    assert elementos_pedagogicos_ausentes("Veja o exemplo e o ERRO frequente.") == ["pratica"]


def _original_longo_com_conceitos() -> str:
    corpo = "\n\n".join(
        f"## {t}\n\n" + (f"Sobre {t.lower()} e sua definição formal. " * 12) for t in _TERMOS
    )
    assert len(corpo) >= 2000
    return corpo


def test_original_longo_exige_ao_menos_dois_dos_tres_elementos() -> None:
    original = _original_longo_com_conceitos()
    base = "\n".join(f"## {t}\nTeoria detalhada de {t.lower()}. " * 3 for t in _TERMOS)
    so_teoria = base * 2

    assert motivo_de_insuficiencia(original, so_teoria, None, 0.1) == "sem_elementos_pedagogicos"
    um_elemento = so_teoria + "\nExemplo resolvido."
    assert motivo_de_insuficiencia(original, um_elemento, None, 0.1) == "sem_elementos_pedagogicos"
    dois = um_elemento + "\nExercício comentado."
    assert motivo_de_insuficiencia(original, dois, None, 0.1) is None


def test_original_curto_nao_exige_elementos_pedagogicos() -> None:
    original = _ORIGINAL_ESTRUTURADO[:1500]
    resposta = "\n".join(f"## {t}\nTeoria de {t.lower()}." for t in _TERMOS) * 3

    assert motivo_de_insuficiencia(original, resposta, None, 0.1) is None


# Complementação controlada


async def test_resposta_suficiente_faz_uma_unica_chamada() -> None:
    seq = _SequenciaDeRespostas(_resposta(_LONGA))

    resultado = await _rodar(seq, complemento=1)

    assert resultado is not None
    assert len(seq.chamadas) == 1
    assert _REFORCO_DE_PROFUNDIDADE not in seq.chamadas[0]["system_instruction"]


async def test_resposta_curta_dispara_uma_complementacao_e_fica_com_a_maior() -> None:
    seq = _SequenciaDeRespostas(_resposta(_CURTA), _resposta(_LONGA))

    resultado = await _rodar(seq, complemento=1)

    assert resultado is not None
    assert len(seq.chamadas) == 2
    assert _REFORCO_DE_PROFUNDIDADE not in seq.chamadas[0]["system_instruction"]
    assert _REFORCO_DE_PROFUNDIDADE in seq.chamadas[1]["system_instruction"]
    # A entrada do usuário é a mesma (o reforço vai só na instrução de sistema).
    assert seq.chamadas[0]["input"] == seq.chamadas[1]["input"]
    pdf = pymupdf.open(stream=resultado.conteudo_pdf, filetype="pdf")
    texto = "".join(p.get_text() for p in pdf)
    assert "Explicação detalhada" in texto
    assert "Texto curto demais" not in texto


async def test_o_limite_de_complementacoes_e_respeitado_mesmo_se_continuar_curta() -> None:
    seq = _SequenciaDeRespostas(_resposta(_CURTA))

    resultado = await _rodar(seq, complemento=2)

    assert resultado is not None  # melhor resposta obtida, sem laço aberto
    assert len(seq.chamadas) == 3  # 1 original + exatamente 2 extras


async def test_conceitos_perdidos_disparam_complementacao_mesmo_com_tamanho_suficiente() -> None:
    termos = ["Proposição", "Negação", "Conjunção", "Disjunção", "Condicional", "Bicondicional"]
    texto = "\n".join(
        f"## {t}\n" + f"Conteúdo sobre {t.lower()} no material de lógica. " * 4 for t in termos
    )
    documento = pymupdf.open()
    for parte in range(0, len(texto), 1800):
        pagina = documento.new_page()
        pagina.insert_text((40, 40), texto[parte : parte + 1800], fontsize=8)
    pdf = documento.tobytes()
    documento.close()
    generica = "# Estudo\n\n" + ("Estude com calma, atenção e constância todos os dias. " * 60)
    completa = (
        "## " + "\n## ".join(termos) + "\n" + ("Exemplo resolvido e exercício comentado. " * 40)
    )
    seq = _SequenciaDeRespostas(_resposta(generica), _resposta(completa))

    await _rodar(seq, complemento=1, pdf=pdf)

    assert len(seq.chamadas) == 2


async def test_complementacao_desligada_nao_faz_chamada_extra() -> None:
    seq = _SequenciaDeRespostas(_resposta(_CURTA), _resposta(_LONGA))

    resultado = await _rodar(seq, complemento=0)

    assert resultado is not None
    assert len(seq.chamadas) == 1


async def test_resposta_incompleta_dispara_complementacao() -> None:
    seq = _SequenciaDeRespostas(_resposta(_LONGA, status="incomplete"), _resposta(_LONGA))

    await _rodar(seq, complemento=1)

    assert len(seq.chamadas) == 2


async def test_complementacao_mais_curta_nao_substitui_a_primeira() -> None:
    primeira = "# Primeira\n\n" + ("Conteúdo da primeira versão, razoável. " * 12)
    seq = _SequenciaDeRespostas(_resposta(primeira), _resposta(_CURTA))

    resultado = await _rodar(seq, complemento=1)

    assert resultado is not None
    pdf = pymupdf.open(stream=resultado.conteudo_pdf, filetype="pdf")
    texto = "".join(p.get_text() for p in pdf)
    assert "primeira versão" in texto
    assert "Texto curto demais" not in texto


async def test_falha_na_complementacao_mantem_a_primeira_resposta_sem_propagar() -> None:
    seq = _SequenciaDeRespostas(_resposta(_CURTA), excecao_na_chamada=2)

    resultado = await _rodar(seq, complemento=1)

    assert resultado is not None  # não vira falha transitória nem repetição do job
    assert len(seq.chamadas) == 2


async def test_original_curto_nao_aciona_complementacao() -> None:
    seq = _SequenciaDeRespostas(_resposta(_CURTA))

    await _rodar(seq, complemento=1, pdf=_pdf_longo(linhas=2))

    assert len(seq.chamadas) == 1


async def test_o_log_da_complementacao_nao_contem_o_texto(caplog: pytest.LogCaptureFixture) -> None:
    seq = _SequenciaDeRespostas(_resposta(_CURTA), _resposta(_LONGA))

    with caplog.at_level("WARNING"):
        await _rodar(seq, complemento=1)

    assert "resposta_curta" in caplog.text
    assert "Texto curto demais" not in caplog.text
    assert "Linha 01" not in caplog.text


# Configuração


def _settings(**alteracoes: Any) -> Settings:
    return Settings(_env_file=None, **alteracoes)


def test_padroes_da_complementacao() -> None:
    s = _settings()
    assert s.gemini_reescrita_complemento_tentativas == 1
    assert s.gemini_reescrita_proporcao_minima == 0.8


@pytest.mark.parametrize("valor", [-1, 3, 10])
def test_complementacoes_fora_de_0_a_2_sao_rejeitadas(valor: int) -> None:
    with pytest.raises(ValidationError):
        _settings(gemini_reescrita_complemento_tentativas=valor)


@pytest.mark.parametrize("valor", [0, -0.1, 3.1])
def test_proporcao_minima_invalida_e_rejeitada(valor: float) -> None:
    with pytest.raises(ValidationError):
        _settings(gemini_reescrita_proporcao_minima=valor)


def test_o_orcamento_do_job_inclui_as_chamadas_extras() -> None:
    # Padrões + imagens ligadas somam 390 s com 1 complementação (30 + 2×45 + 60 + 150 + 60) e
    # cabem em 420. Subir o orçamento do Gemini sem subir o prazo do job é recusado.
    base: dict[str, Any] = {
        "imagens_geradas_habilitadas": True,
        "cloudflare_account_id": "0123456789abcdef0123456789abcdef",
        "cloudflare_api_token": "token-de-teste",
        "cloudflare_image_model": "@cf/black-forest-labs/flux-1-schnell",
    }
    _settings(**base)  # padrões: válido
    with pytest.raises(ValidationError, match="WORKER_PRAZO_MAXIMO_JOB_SEGUNDOS"):
        _settings(**base, gemini_timeout_total_segundos=75)  # 30 + 2×75 + 270 = 450 > 420
    _settings(**base, gemini_timeout_total_segundos=75, worker_prazo_maximo_job_segundos=460)
    _settings(**base, gemini_timeout_total_segundos=75, gemini_reescrita_complemento_tentativas=0)
