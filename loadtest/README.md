# Teste de carga

Mede latência, taxa de erro e comportamento da fila sob concorrência, com [Locust](https://locust.io/). Fica isolado de `src/` e fora da suíte do pytest. O Worker de carga usa fakes de LLM e Storage, então nenhum teste chama o Gemini ou o Supabase reais.

Nunca rode contra o banco de produção nem com o `SERVICE_TOKEN` de um ambiente real.

## Execução

**1. Banco isolado**

```bash
docker compose up -d postgres
uv run alembic upgrade head
```

**2. Token descartável.** Gere um valor só para o teste e use-o como `SERVICE_TOKEN` no `.env` e em `LOADTEST_SERVICE_TOKEN`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

`GEMINI_API_KEY`, `STORAGE_URL` e `STORAGE_SERVICE_KEY` precisam estar preenchidas para o processo subir, mas qualquer valor serve: nenhuma delas é usada durante o teste.

**3. API e Worker de carga**, em terminais separados:

```bash
uv run uvicorn presentation.api.main:app --app-dir src
PYTHONPATH=src uv run python -m loadtest.worker_carga --latencia-llm-segundos 2.0
```

`--latencia-llm-segundos` define quanto o fake de LLM espera a cada chamada. É um valor ajustável, não uma medida do Gemini real.

**4. Dados sintéticos**

```bash
PYTHONPATH=src uv run python -m loadtest.seed --quantidade 20
```

**5. Carga**

```bash
mkdir -p loadtest/resultados
LOADTEST_SERVICE_TOKEN=<token> LOADTEST_CSV_PREFIXO=loadtest/resultados/carga \
    uv run locust -f loadtest/locustfile.py --host http://localhost:8000 \
    --headless --users 5 --spawn-rate 1 --run-time 60s --csv=loadtest/resultados/carga
```

**6. Métricas do banco**

```bash
PYTHONPATH=src uv run python -m loadtest.relatorio --csv-prefixo loadtest/resultados/carga
```

## Resultados gerados

| Arquivo | Conteúdo |
|---|---|
| `carga_stats.csv` | Throughput e latência (média, p50, p95, p99) |
| `carga_stats_history.csv` | Série temporal da execução |
| `carga_failures.csv` | Respostas não-2xx, incluindo os `429` do rate limit |
| `carga_status_codes.json` | Contagem exata por código HTTP |
| `carga_mpi.json` | Status dos processamentos, drenagem da fila e checagem de duplicação |

Os resultados ficam em `loadtest/resultados/`, ignorada pelo Git.

## Cenários

| Cenário | Objetivo | Parâmetros |
|---|---|---|
| Base | Latência abaixo do rate limit (10 req/min) | `--users 5 --spawn-rate 1 --run-time 60s` |
| Rate limit | Excedente recebendo `429` de forma consistente | `--users 20 --spawn-rate 5 --run-time 60s` |
| Rajada | Recuperação depois de um pico, sem jobs presos | `--users 50 --spawn-rate 50 --run-time 10s` |

Os parâmetros são pontos de partida, não metas de desempenho.

## Concorrência entre Workers

Para testar vários Workers disputando a mesma fila, rode mais de um `loadtest.worker_carga` apontando para o mesmo banco. A garantia de que cada job é reivindicado uma única vez também é coberta de forma determinística em `tests/integration/queue` e `tests/integration/worker`.

Os logs da API e do Worker usam o `processamento_id` como id de correlação, o que permite seguir a jornada de cada requisição.
