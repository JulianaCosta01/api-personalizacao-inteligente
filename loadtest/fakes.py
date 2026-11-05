"""Fakes de LLM e Object Storage usados só pelo Worker de carga, nunca em produção.

O teste de carga mede o próprio sistema (API, fila, Worker), não a latência ou o custo
de provedores externos.
"""

import asyncio

from application.ports.llm import ConteudoPersonalizado, ILLMPort
from application.ports.object_storage import IObjectStoragePort
from domain.material.tipo_arquivo import TipoArquivo
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao

_CONTEUDO_ORIGINAL_FAKE = b"%PDF-1.4 conteudo de material didatico fake (loadtest, sem I/O real)"
_PDF_PERSONALIZADO_FAKE = b"%PDF-1.4 conteudo de material personalizado fake (loadtest)"
_RESUMO_FAKE = "Resumo gerado pelo fake de carga (loadtest) — não é conteúdo real do Gemini."
_DESCRICAO_PERFIL_FAKE = "Descrição de perfil gerada pelo fake de carga (loadtest)."


class LLMFakeComLatencia(ILLMPort):
    """Simula o tempo de resposta do Gemini sem chamar a rede.

    `latencia_segundos` é um valor ajustável, não medido do Gemini real (ver loadtest/README.md).
    """

    def __init__(self, latencia_segundos: float) -> None:
        self.latencia_segundos = latencia_segundos

    async def gerar_descricao_perfil(
        self,
        estilo_processamento: EstiloProcessamento,
        percepcao: Percepcao,
        entrada: Entrada,
        compreensao: Compreensao,
    ) -> str | None:
        await asyncio.sleep(self.latencia_segundos)
        return _DESCRICAO_PERFIL_FAKE

    async def reescrever_conteudo(
        self,
        conteudo_original: bytes,
        estilo_processamento: EstiloProcessamento,
        percepcao: Percepcao,
        entrada: Entrada,
        compreensao: Compreensao,
    ) -> ConteudoPersonalizado | None:
        await asyncio.sleep(self.latencia_segundos)
        return ConteudoPersonalizado(conteudo_pdf=_PDF_PERSONALIZADO_FAKE, resumo=_RESUMO_FAKE)


class ObjectStorageFake(IObjectStoragePort):
    """Guarda os objetos em memória do próprio processo do Worker de carga.

    Uma instância por execução do caso de uso (ver worker_carga.py), não precisa persistir
    entre Processamentos nem entre execuções; o teste de carga não avalia o Storage em si, só
    precisa que o Worker consiga completar o fluxo sem depender de rede externa.
    """

    def __init__(self) -> None:
        self._objetos: dict[str, bytes] = {}

    async def salvar(self, chave: str, conteudo: bytes, tipo_arquivo: TipoArquivo) -> None:
        self._objetos[chave] = conteudo

    async def remover(self, chave: str) -> None:
        self._objetos.pop(chave, None)

    async def obter(self, chave: str) -> bytes:
        return self._objetos.get(chave, _CONTEUDO_ORIGINAL_FAKE)

    async def criar_url_leitura(self, chave: str, expiracao_segundos: int) -> str:
        return f"http://loadtest-storage.invalid/{chave}?expira_em={expiracao_segundos}"
