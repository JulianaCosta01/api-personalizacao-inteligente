from uuid import UUID

from application.ports.llm import ConteudoPersonalizado, ILLMPort
from application.ports.perfil_repository import IPerfilRepository
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil


class PerfilRepositorioFake(IPerfilRepository):
    def __init__(self) -> None:
        self._perfis: dict[UUID, Perfil] = {}

    def semear(self, perfil: Perfil) -> None:
        self._perfis[perfil.id] = perfil

    async def adicionar(self, perfil: Perfil) -> None:
        self._perfis[perfil.id] = perfil

    async def atualizar(self, perfil: Perfil) -> None:
        self._perfis[perfil.id] = perfil

    async def obter_por_id(self, id: UUID) -> Perfil | None:
        return self._perfis.get(id)

    async def obter_mais_recente_por_aluno_id(self, aluno_id: UUID) -> Perfil | None:
        perfis_do_aluno = [p for p in self._perfis.values() if p.aluno_id == aluno_id]
        if not perfis_do_aluno:
            return None
        return max(perfis_do_aluno, key=lambda p: p.data_atualizacao)

    async def listar_por_aluno_id(
        self, aluno_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Perfil], int]:
        perfis_do_aluno = sorted(
            (p for p in self._perfis.values() if p.aluno_id == aluno_id),
            key=lambda p: p.data_atualizacao,
            reverse=True,
        )
        inicio = (pagina - 1) * tamanho_pagina
        return perfis_do_aluno[inicio : inicio + tamanho_pagina], len(perfis_do_aluno)


class LLMFake(ILLMPort):
    def __init__(
        self,
        descricao: str | None = "Descrição gerada.",
        levantar: bool = False,
        conteudo_reescrito: ConteudoPersonalizado | None = None,
        levantar_reescrita: bool = False,
        retornar_none_na_reescrita: bool = False,
    ) -> None:
        self.descricao = descricao
        self.levantar = levantar
        self.chamadas = 0
        self.conteudo_reescrito = conteudo_reescrito or ConteudoPersonalizado(
            conteudo_pdf=b"%PDF-conteudo adaptado", resumo="Resumo do material adaptado."
        )
        self.levantar_reescrita = levantar_reescrita
        self.retornar_none_na_reescrita = retornar_none_na_reescrita
        self.chamadas_reescrita = 0

    async def gerar_descricao_perfil(
        self,
        estilo_processamento: EstiloProcessamento,
        percepcao: Percepcao,
        entrada: Entrada,
        compreensao: Compreensao,
    ) -> str | None:
        self.chamadas += 1
        if self.levantar:
            raise RuntimeError("falha simulada do Gemini")
        return self.descricao

    async def reescrever_conteudo(
        self,
        conteudo_original: bytes,
        estilo_processamento: EstiloProcessamento,
        percepcao: Percepcao,
        entrada: Entrada,
        compreensao: Compreensao,
    ) -> ConteudoPersonalizado | None:
        self.chamadas_reescrita += 1
        if self.levantar_reescrita:
            raise RuntimeError("falha simulada do Gemini")
        if self.retornar_none_na_reescrita:
            return None
        return self.conteudo_reescrito
