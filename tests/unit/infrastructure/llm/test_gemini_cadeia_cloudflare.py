"""Cadeia real do pipeline, sem rede: Gemini simulado -> marcadores -> orquestrador ->
CloudflareImageAdapter (transporte simulado) -> figuras no PDF.

Prova que cada ilustração sai de uma chamada ao provedor de imagens configurado (o corpo e a URL
são conferidos) e que entra junto ao seu tópico, sem a seção de imagens originais.
"""

import base64
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pymupdf

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from infrastructure.config.settings import Settings
from infrastructure.imagens.cloudflare_adapter import CloudflareImageAdapter
from infrastructure.llm.gemini_adapter import GeminiAdapter
from tests.unit.application.ports.imagens_fixture import jpeg_valido
from tests.unit.infrastructure.llm.limites_locais import LIMITES_LOCAIS_DE_PRODUCAO
from tests.unit.infrastructure.llm.test_gemini_adapter import _cliente_fake, _InteractionsFake
from tests.unit.infrastructure.pipeline.pdf_fixture import pdf_valido

_CONTA = "0123456789abcdef0123456789abcdef"
_MODELO = "@cf/black-forest-labs/flux-1-schnell"
_DESCRICAO_1 = "Balança de dois pratos equilibrada com pesos iguais"
_DESCRICAO_2 = "Duas pontes ligadas por uma estrada entre ilhas"

_ADAPTADO = (
    "# Estudo\n\n## Equilíbrio\n\n" + ("Explicação do equilíbrio entre as partes. " * 8) + "\n\n"
    f"[[IMAGEM:equilibrio|{_DESCRICAO_1}]]\n\n"
    "## Conexões\n\n" + ("Explicação das conexões entre os elementos. " * 8) + "\n\n"
    f"[[IMAGEM:conexoes|{_DESCRICAO_2}]]\n\n"
    "## Fechamento\n\nTexto final do material adaptado.\n"
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        imagens_geradas_habilitadas=True,
        imagens_provedor="cloudflare",
        cloudflare_account_id=_CONTA,
        cloudflare_api_token="token-de-teste",
        cloudflare_image_model=_MODELO,
    )


async def _rodar(handler: Any, **opcoes: Any) -> Any:
    cliente = httpx.AsyncClient(
        base_url="https://api.cloudflare.com/client/v4",
        headers={"Authorization": "Bearer token-de-teste"},
        transport=httpx.MockTransport(handler),
    )
    gerador = CloudflareImageAdapter.a_partir_de_settings(_settings(), cliente)
    interactions = _InteractionsFake(resposta=SimpleNamespace(output_text=_ADAPTADO))
    adaptador = GeminiAdapter(
        _cliente_fake(interactions),
        "gemini-3.1-flash-lite",
        5.0,
        imagens_geradas_habilitadas=True,
        imagens_max_por_material=2,
        gerador_de_imagens=gerador,
        **{**LIMITES_LOCAIS_DE_PRODUCAO, **opcoes},
    )
    return await adaptador.reescrever_conteudo(
        pdf_valido("Conteúdo original."),
        EstiloProcessamento.ATIVO,
        Percepcao.SENSORIAL,
        Entrada.VISUAL,
        Compreensao.SEQUENCIAL,
    )


def _resposta_ok(request: httpx.Request) -> httpx.Response:
    imagem = base64.b64encode(jpeg_valido()).decode("ascii")
    return httpx.Response(200, json={"success": True, "result": {"image": imagem}})


async def test_cada_ilustracao_vem_de_uma_chamada_ao_provedor_e_entra_junto_ao_topico() -> None:
    chamadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request)
        return _resposta_ok(request)

    resultado = await _rodar(handler)

    assert resultado is not None
    assert len(chamadas) == 2
    for requisicao in chamadas:
        assert requisicao.url.host == "api.cloudflare.com"
        assert requisicao.url.path.endswith(f"/accounts/{_CONTA}/ai/run/{_MODELO}")
    prompts = [json.loads(r.content)["prompt"] for r in chamadas]
    assert _DESCRICAO_1 in prompts[0] and _DESCRICAO_2 in prompts[1]

    pdf = pymupdf.open(stream=resultado.conteudo_pdf, filetype="pdf")
    texto = "".join(p.get_text() for p in pdf)
    assert "Imagens do material original" not in texto
    assert (
        texto.index("Explicação do equilíbrio") < texto.index("Figura 1.") < texto.index("Conexões")
    )
    assert (
        texto.index("Explicação das conexões")
        < texto.index("Figura 2.")
        < texto.index("Fechamento")
    )
    jpegs = {
        ref[0]
        for p in pdf
        for ref in p.get_images(full=True)
        if pdf.extract_image(ref[0])["ext"] in ("jpeg", "jpg")
    }
    assert len(jpegs) >= 1  # a imagem devolvida pelo provedor está embutida no PDF


async def test_falha_do_provedor_nao_simula_imagem_e_o_pdf_sai_so_com_texto(
    caplog: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"success": False})

    with caplog.at_level("INFO"):
        resultado = await _rodar(handler)

    assert resultado is not None
    pdf = pymupdf.open(stream=resultado.conteudo_pdf, filetype="pdf")
    texto = "".join(p.get_text() for p in pdf)
    assert "Figura " not in texto  # nenhuma imagem inventada
    assert "Explicação do equilíbrio" in texto  # o texto adaptado foi preservado
    assert "falha(s)" in caplog.text  # a falha foi registrada
    assert "limite_excedido" in caplog.text
    assert "token-de-teste" not in caplog.text
