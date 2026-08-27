# Teste de carga e concorrência — Fase 10, Task 2

Ferramental para o critério de conclusão da Fase 10 (Documento 5, §17): *"teste de carga
executado com resultado documentado (latência, taxa de erro sob concorrência)"*.

Este diretório é isolado de `src/`: nada aqui é importado pela API ou pelo Worker reais — só o
inverso. Nada aqui deve rodar contra produção, dados reais, `SERVICE_TOKEN` real, Gemini real ou
Moodle real.

## O que é requisito do projeto e o que é proposta desta implementação

| | Fonte |
|---|---|
| Teste de carga deve existir e produzir resultado documentado (latência, taxa de erro sob concorrência) | Documento 5, §17 — requisito |
| Locust como ferramenta | Documento 4, §18 cita Locust ou k6 como exemplo; **Locust foi formalmente aprovado por Xulis para esta Task** |
| Gemini real fora do teste de carga, substituído por fake com latência configurável | Aprovado por Xulis para esta Task |
| Quantidade de usuários virtuais, RPS, duração dos cenários, valor de latência do fake LLM | **Não especificado em nenhum documento — todo número abaixo é PROPOSTA**, ajustável sem aprovação prévia |
| Critério numérico de aprovação (ex.: "p95 deve ser < Xms") | **Não existe no projeto** — os resultados são registrados objetivamente; a interpretação/aceitação é decisão posterior de Xulis, não automatizada aqui |

## Pré-requisitos

- Ambiente já configurado conforme o `README.md` da raiz (Python 3.13+, `uv sync --all-groups`
  — isso já instala o Locust, adicionado ao grupo `dev` nesta Task).
- Um Postgres isolado, nunca o de produção.

## 1. Subir o PostgreSQL (isolado)

```bash
docker compose up -d postgres
uv run alembic upgrade head
```

Use a mesma `DATABASE_URL` do seu `.env` de desenvolvimento local, ou um banco totalmente à
parte — nunca aponte para produção.

## 2. Configurar um `.env` de carga

Copie `.env.example` para `.env` (ou reaproveite o seu `.env` de desenvolvimento local) e gere um
`SERVICE_TOKEN` descartável só para este teste:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

`GEMINI_API_KEY`, `STORAGE_URL` e `STORAGE_SERVICE_KEY` continuam **obrigatórios** para o
processo subir (`Settings` não tem default para eles), mas nenhum deles é chamado de verdade
durante o cenário principal (`POST /api/v1/processamentos` nunca toca Gemini nem Storage
diretamente — só o Worker toca, e o Worker de carga usa fakes). Qualquer valor sintático válido
serve; não é necessário um projeto Gemini/Supabase real para rodar o teste de carga.

## 3. Iniciar a API (sem alterações — a mesma de produção)

```bash
uv run uvicorn presentation.api.main:app --app-dir src --reload
```

## 4. Iniciar o Worker de carga (não é o Worker de produção)

```bash
PYTHONPATH=src uv run python -m loadtest.worker_carga --latencia-llm-segundos 2.0
```

`--latencia-llm-segundos` (PROPOSTA, default `2.0`) controla quanto tempo o fake de LLM
(`loadtest/fakes.py`) espera antes de "responder" em cada chamada — simula um Worker ocupado por
um tempo não-instantâneo, sem depender da rede real. Ajuste para explorar cenários diferentes de
tempo de processamento; não é um valor medido do Gemini real.

## 5. Semear dados

```bash
PYTHONPATH=src uv run python -m loadtest.seed --quantidade 20
```

Cria N pares Aluno + Material Didático + Perfil direto no banco (sem tocar a API, o Gemini ou o
Storage) e grava `loadtest/seed_data.json`, lido pelo `locustfile.py`.

## 6. Executar a carga

```bash
mkdir -p loadtest/resultados
LOADTEST_SERVICE_TOKEN=<o-token-gerado-no-passo-2> \
LOADTEST_CSV_PREFIXO=loadtest/resultados/carga \
    uv run locust -f loadtest/locustfile.py --host http://localhost:8000 \
    --headless --users 5 --spawn-rate 1 --run-time 60s \
    --csv=loadtest/resultados/carga
```

`LOADTEST_CSV_PREFIXO` deve ser sempre igual ao valor passado em `--csv=`. Locust já grava
`carga_stats.csv` (throughput, latência média, p50/p95/p99, contagem por endpoint),
`carga_stats_history.csv` (série temporal) e `carga_failures.csv` (não-2xx, inclusive 429 do
rate limiter). O `locustfile.py` grava, além disso, `carga_status_codes.json` — contagem exata
por código HTTP (202 vs. 429 vs. qualquer outro), já que o `_stats.csv` nativo agrupa por
endpoint, não por status.

### Cenários sugeridos (PROPOSTA — ajuste os números livremente)

| Cenário | Objetivo | Exemplo de comando |
|---|---|---|
| 1. Baseline | Latência/throughput normal, abaixo do rate limiter (10 req/min) | `--users 5 --spawn-rate 1 --run-time 60s` |
| 2. No limite do rate limiter | Confirmar que o excedente de 10 req/min recebe 429 de forma consistente (comportamento esperado, não falha) | `--users 20 --spawn-rate 5 --run-time 60s` |
| 3. Rajada | Pico curto seguido de repouso; observar recuperação e ausência de estado preso | `--users 50 --spawn-rate 50 --run-time 10s` |

Nenhum desses números é meta de desempenho do projeto — são pontos de partida para gerar carga
suficiente e observar o comportamento real.

## 7. Coletar as métricas específicas do MPI

```bash
PYTHONPATH=src uv run python -m loadtest.relatorio --csv-prefixo loadtest/resultados/carga
```

Consulta o banco diretamente e grava `loadtest/resultados/carga_mpi.json` com:

- quantidade de Processamentos criados, e quantos ficaram em cada status (`pendente`,
  `em_processamento`, `concluido`, `erro`);
- mensagens restantes em `fila_processamento` (drenagem — deve chegar a zero depois que o Worker
  de carga processar tudo);
- qualquer `processamento_id` com mais de um `MaterialPersonalizado` (evidência de duplicação de
  claim/processamento — deve ser sempre uma lista vazia).

## Concorrência entre Workers e idempotência

O padrão de concorrência real (`asyncio.gather` com sessões independentes, exercitando o `SELECT
... FOR UPDATE SKIP LOCKED`) já existe e está coberto por
`tests/integration/queue/test_fila_postgres.py::test_dois_workers_disputando_a_mesma_mensagem_apenas_um_reivindica`
e pela suíte de idempotência do Worker em `tests/integration/worker/test_worker.py` — este teste
de carga **não substitui** esses testes de integração; ele avalia o comportamento sob volume real
via HTTP + banco, não é um teste determinístico de unidade/integração e não deve ser adicionado à
suíte pytest. Para avaliar múltiplos Workers de carga concorrentes, basta rodar mais de um
processo de `loadtest.worker_carga` ao mesmo tempo, apontando para o mesmo banco — o `SKIP LOCKED`
já garante que cada mensagem da fila é reivindicada por um único Worker.

## Correlação API → Worker

Todo log do Worker (produção ou de carga) carrega `request_id` = `processamento_id` (Fase 10,
Task 1). Para investigar a jornada de uma requisição específica, filtre os logs JSON estruturados
(saída padrão da API e do Worker de carga) pelo mesmo `processamento_id` retornado no corpo da
resposta de `POST /api/v1/processamentos`.

## Segurança

- Nunca usar o `SERVICE_TOKEN` real de nenhum ambiente — sempre um valor gerado só para o teste.
- `loadtest/seed_data.json` e `loadtest/resultados/*.csv`/`*.json` contêm apenas UUIDs sintéticos
  e métricas agregadas — nenhum dado real de aluno, e-mail real ou segredo. Ainda assim, não
  versionar (`loadtest/seed_data.json` e `loadtest/resultados/` devem ficar fora do controle de
  versão, junto com `.env`).
- Não altera CORS, autenticação, rate limiting nem nenhuma outra regra de segurança existente —
  o teste roda contra a API exatamente como ela existe em produção.
