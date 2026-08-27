"""Locust do teste de carga da Fase 10, Task 2 — dispara POST /api/v1/processamentos.

Não importa nada de src/: lê os pares aluno_id/material_didatico_id gerados por
`loadtest/seed.py` (loadtest/seed_data.json) e o SERVICE_TOKEN de teste via variável de
ambiente LOADTEST_SERVICE_TOKEN. Nunca usar o SERVICE_TOKEN real de nenhum ambiente aqui —
gere um valor descartável só para esta execução, igual ao configurado no .env do Worker/API de
carga (ver loadtest/README.md).

Uso:
    LOADTEST_SERVICE_TOKEN=<token-de-teste-descartavel> \\
        uv run locust -f loadtest/locustfile.py --host http://localhost:8000
"""

import json
import os
import random
from collections import Counter
from pathlib import Path

from locust import HttpUser, between, events, task

_ARQUIVO_SEED = Path(__file__).resolve().parent / "seed_data.json"
_PREFIXO_RESULTADOS = os.environ.get("LOADTEST_CSV_PREFIXO", "loadtest/resultados/carga")

# Distribuição exata de status HTTP (Fase 10, Task 2 exige isso explicitamente). O _stats.csv
# nativo do Locust agrupa por nome de requisição, não por status code — este contador separado
# é o jeito direto de responder "quantos 202 vs. 429 vs. outro código", sem depender de parsear
# o texto de _failures.csv.
_CONTADOR_STATUS: Counter[int] = Counter()

_TOKEN = os.environ.get("LOADTEST_SERVICE_TOKEN", "")
if not _TOKEN:
    raise RuntimeError(
        "LOADTEST_SERVICE_TOKEN não definido. Nunca use o SERVICE_TOKEN real de nenhum "
        "ambiente — configure um valor de teste descartável (ver loadtest/README.md)."
    )

try:
    _PARES: list[dict[str, str]] = json.loads(_ARQUIVO_SEED.read_text(encoding="utf-8"))
except FileNotFoundError as exc:
    raise RuntimeError(
        f"{_ARQUIVO_SEED} não encontrado. Rode antes: PYTHONPATH=src uv run python -m loadtest.seed"
    ) from exc

if not _PARES:
    raise RuntimeError(f"{_ARQUIVO_SEED} está vazio — rode loadtest/seed.py com --quantidade > 0.")


class UsuarioDeProcessamento(HttpUser):
    """Simula uma solicitação de personalização por vez, por usuário virtual.

    PROPOSTA: `wait_time` entre 1 e 2 segundos por usuário não é requisito de nenhum documento —
    só controla a intensidade agregada junto com --users/--spawn-rate na linha de comando.
    """

    wait_time = between(1, 2)

    @task
    def criar_processamento(self) -> None:
        par = random.choice(_PARES)
        resposta = self.client.post(
            "/api/v1/processamentos",
            json={"aluno_id": par["aluno_id"], "material_didatico_id": par["material_didatico_id"]},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        _CONTADOR_STATUS[resposta.status_code] += 1
        # Sem override de success/failure: 429 (rate limiter, Fase 9 Task 1) e qualquer 5xx
        # seguem a semântica padrão do Locust (status >= 400 conta como falha em
        # _stats.csv/_failures.csv) — a distinção entre "limite esperado sob carga" e "erro
        # real" fica em _status_codes.json (contador exato por código), não decidida aqui.


@events.quitting.add_listener
def _salvar_distribuicao_de_status(environment: object, **kwargs: object) -> None:
    caminho = Path(f"{_PREFIXO_RESULTADOS}_status_codes.json")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps({str(codigo): total for codigo, total in _CONTADOR_STATUS.items()}, indent=2),
        encoding="utf-8",
    )
