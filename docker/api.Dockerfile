# Fase 11, Task 1 (Documento 5 §185; Documento 4 §19) — imagem da API.
# Build multi-stage: o estágio "builder" resolve as dependências de runtime a partir do
# uv.lock (build reprodutível, grupo "dev" excluído — pytest/ruff/mypy/locust não pertencem
# a esta imagem); o estágio final só recebe o ambiente Python já pronto, as bibliotecas
# nativas do WeasyPrint e o código-fonte, sem nenhuma ferramenta de build.
#
# A API importa infrastructure/pipeline (pymupdf4llm, weasyprint) transitivamente no startup
# via infrastructure/llm/gemini_adapter.py, mesmo nunca gerando PDF diretamente — por isso
# libpango/libcairo são instaladas aqui também, não só na futura imagem do Worker.

FROM python:3.13-slim AS builder

RUN pip install --no-cache-dir uv

# Mesmo caminho do estágio final (/app), de propósito: `uv sync` grava o shebang de cada
# executável do venv (ex. .venv/bin/uvicorn) como caminho absoluto do WORKDIR atual. Se o
# venv fosse criado em /build e depois copiado para /app, os shebangs continuariam
# apontando para /build/.venv/bin/python — inexistente no estágio final ("no such file or
# directory" ao rodar o container). Construir e copiar no mesmo /app elimina essa divergência.
WORKDIR /app

# Só os arquivos que definem as dependências: cache de camada do Docker não invalida a
# instalação a cada mudança em src/, que é copiado depois.
COPY pyproject.toml uv.lock ./

# --no-dev: exclui o grupo "dev" (pytest, ruff, mypy, locust) da imagem final.
# --no-install-project: pyproject.toml não declara nenhum artefato instalável (é uma
# aplicação, não uma biblioteca — [tool.uv] package = false); só as dependências de
# terceiros precisam ser resolvidas aqui.
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.13-slim AS runtime

# Pango/Cairo — exigidos pelo WeasyPrint (README, Documento 4 §19); pacotes idênticos aos
# já documentados para o ambiente de desenvolvimento em Debian/Ubuntu.
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

# Sem --reload (é um recurso de desenvolvimento). Migrations não rodam aqui — etapa
# explícita e separada do deploy, por decisão desta Task.
#
# Python do venv invocado diretamente (-m uvicorn), não o script .venv/bin/uvicorn: esse
# script tem o caminho do interpretador gravado no próprio shebang no momento do `uv sync`
# (estágio builder) — qualquer divergência de path entre os estágios do build quebra o
# shebang e o container falha com "no such file or directory". Chamar o interpretador
# diretamente elimina essa dependência do shebang por completo.
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "presentation.api.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
