"""Semeia Aluno + Material Didático + Perfil direto via repositórios (Fase 10, Task 2).

POST /api/v1/processamentos exige um Aluno, um Material Didático e um Perfil já cadastrados
(ver application/processamento/criar_processamento.py). Este script cria esses três recursos
SEM passar pela API — motivo: `POST /alunos/{id}/perfil` chama o Gemini de forma síncrona (ver
presentation/api/routers/perfil.py) e `POST /materiais` chama o Object Storage real; nenhum dos
dois deve ser tocado só para preparar dados de teste. O padrão de composição direta via
repositórios já existe em tests/integration/queue/test_fila_postgres.py::_criar_processamento —
este script reaproveita o mesmo padrão (repositórios SQLAlchemy existentes), só parando antes de
criar o Processamento em si, que é o próprio POST que o Locust vai disparar.

NUNCA rodar contra um banco de produção — grava dados sintéticos, sem vínculo com alunos reais.

Uso:
    PYTHONPATH=src uv run python -m loadtest.seed --quantidade 20
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.session import sessao_transacional

ARQUIVO_SAIDA = Path(__file__).resolve().parent / "seed_data.json"


async def semear(quantidade: int) -> list[dict[str, str]]:
    pares: list[dict[str, str]] = []
    async with sessao_transacional() as session:
        repositorio_aluno = AlunoRepositorySQLAlchemy(session)
        repositorio_material = MaterialRepositorySQLAlchemy(session)
        repositorio_perfil = PerfilRepositorySQLAlchemy(session)

        for indice in range(quantidade):
            aluno = Aluno(
                id=uuid4(),
                nome=f"Aluno de Carga {indice}",
                email=f"carga-{uuid4()}@discente.ufma.br",
                matricula=f"CARGA{indice:06d}-{str(uuid4())[:8]}",
                grupo_experimental=GrupoExperimental.EXPERIMENTAL,
                data_cadastro=datetime.now(UTC),
            )
            await repositorio_aluno.adicionar(aluno)

            material = MaterialDidatico(
                id=uuid4(),
                titulo=f"Material de Carga {indice}",
                nome_arquivo=f"{uuid4()}.pdf",
                tipo_arquivo=TipoArquivo.PDF,
                # Nunca lido de verdade: o Worker de carga usa ObjectStorageFake
                # (loadtest/fakes.py), que ignora esta chave.
                caminho_storage=f"materiais/loadtest/{uuid4()}.pdf",
                versao=1,
                data_upload=datetime.now(UTC),
            )
            await repositorio_material.adicionar(material)

            perfil = Perfil(
                id=uuid4(),
                aluno_id=aluno.id,
                estilo_processamento=EstiloProcessamento.ATIVO,
                percepcao=Percepcao.SENSORIAL,
                entrada=Entrada.VISUAL,
                compreensao=Compreensao.SEQUENCIAL,
                descricao_llm=None,
                data_atualizacao=datetime.now(UTC),
            )
            await repositorio_perfil.adicionar(perfil)

            pares.append({"aluno_id": str(aluno.id), "material_didatico_id": str(material.id)})

    return pares


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semeia Alunos/Materiais/Perfis para o teste de carga da Fase 10, Task 2."
    )
    parser.add_argument(
        "--quantidade",
        type=int,
        default=20,
        help="PROPOSTA: número de pares aluno/material a semear (default arbitrário, sem "
        "relação com nenhuma meta do projeto).",
    )
    args = parser.parse_args()

    pares = asyncio.run(semear(args.quantidade))
    ARQUIVO_SAIDA.write_text(json.dumps(pares, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(pares)} pares aluno/material semeados em {ARQUIVO_SAIDA}")


if __name__ == "__main__":
    main()
