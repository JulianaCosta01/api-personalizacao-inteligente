# Build multi-stage: builder resolve as dependências via uv.lock; o estágio
# final recebe só o ambiente Python pronto e o código-fonte, sem ferramenta de build.

FROM python:3.13-slim AS builder

RUN pip install --no-cache-dir uv

# Mesmo caminho do estágio final: `uv sync` grava o shebang do venv como caminho
# absoluto do WORKDIR — construir em /build e copiar para /app quebraria os executáveis.
WORKDIR /app

# Só os arquivos que definem as dependências: cache de camada do Docker não invalida a
# instalação a cada mudança em src/, que é copiado depois.
COPY pyproject.toml uv.lock ./

# --no-dev exclui pytest/ruff/mypy/locust; --no-install-project porque o projeto
# não é um pacote instalável ([tool.uv] package = false), só dependências de terceiros.
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.13-slim AS runtime

# Pango/Cairo — exigidos pelo WeasyPrint.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Usuário não-root: a API não escreve em disco além de cache temporário do processo.
RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/

RUN chown -R app:app /app

USER app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Sem --reload. Migrations não rodam aqui. Interpretador do venv chamado direto
# (-m uvicorn), para não depender do shebang gravado pelo uv sync no script .venv/bin/uvicorn.
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "presentation.api.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
