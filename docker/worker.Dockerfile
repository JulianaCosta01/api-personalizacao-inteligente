# Mesmo padrão de docker/api.Dockerfile. O Worker é quem de fato executa o
# pipeline (Gemini, extração, geração de PDF), por isso o WeasyPrint é central aqui.

FROM python:3.13-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.13-slim AS runtime

# Pango/Cairo — exigidos pelo WeasyPrint.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Usuário não-root: o Worker não escreve em disco além de cache temporário do processo (o
# PDF gerado vai direto para o Object Storage, nunca é persistido localmente).
RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/

RUN chown -R app:app /app

USER app

# PYTHONPATH em vez do --app-dir do uvicorn (exclusivo da API): equivalente a
# `PYTHONPATH=src python -m worker.worker`, mesma convenção usada localmente.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1

# Sem EXPOSE: o Worker não é um servidor HTTP. Migrations não rodam aqui.
CMD ["python", "-m", "worker.worker"]
