# Fase 11, Task 2 (Documento 5 §185; Documento 4 §19) — imagem do Worker.
# Mesmo padrão validado em docker/api.Dockerfile (build multi-stage, venv criado e copiado
# no mesmo caminho /app/.venv para não quebrar os shebangs dos executáveis, uv.lock como
# fonte reproduzível, sem grupo "dev", usuário não-root, nenhum segredo na imagem).
#
# worker/worker.py importa GeminiAdapter, que importa infrastructure/pipeline (extrator.py:
# pymupdf4llm; gerador_pdf.py: weasyprint) — as mesmas dependências nativas da API, pelo
# mesmo motivo: o Worker é quem de fato executa o pipeline de personalização (reescrita via
# Gemini, extração e geração de PDF), então essa cadeia é ainda mais central aqui do que na API.

FROM python:3.13-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.13-slim AS runtime

# Pango/Cairo — exigidos pelo WeasyPrint; mesmos pacotes de docker/api.Dockerfile.
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

# PYTHONPATH em vez do --app-dir do uvicorn (que só existe para esse comando): é o
# equivalente exato de `PYTHONPATH=src python -m worker.worker`, já documentado no README
# para rodar o Worker localmente — mesma convenção, sem introduzir nada novo.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1

# Sem EXPOSE: o Worker não escuta porta nenhuma, não é um servidor HTTP.
# Migrations não rodam aqui — mesma decisão já tomada para a API (Task 1): etapa explícita e
# separada do deploy, fora do escopo desta imagem.
CMD ["python", "-m", "worker.worker"]
