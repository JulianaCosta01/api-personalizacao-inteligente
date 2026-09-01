import os

# Campos obrigatórios de Settings, sem default de propósito: os testes declaram os
# próprios valores aqui em vez de depender de um .env que não existe em CI.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/mpi_test"
)
os.environ.setdefault("SERVICE_TOKEN", "token-de-teste-nao-usar-em-producao")
os.environ.setdefault("STORAGE_URL", "https://storage.teste.invalid")
os.environ.setdefault("STORAGE_SERVICE_KEY", "chave-de-teste-nao-usar-em-producao")
os.environ.setdefault("GEMINI_API_KEY", "chave-de-teste-nao-usar-em-producao")
