from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from domain.aluno.grupo_experimental import GrupoExperimental


@dataclass
class Aluno:
    id: UUID
    nome: str
    email: str
    matricula: str
    grupo_experimental: GrupoExperimental
    data_cadastro: datetime

    def atualizar_cadastro(self, nome: str, email: str) -> None:
        # Único método de mutação: matricula e grupo_experimental são imutáveis
        # após o cadastro (Documento 3, §4.1) e por isso não têm setter — a
        # ausência do método, não uma validação em tempo de execução, é a
        # proteção.
        self.nome = nome
        self.email = email
