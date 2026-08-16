import os

# Settings.database_url e Settings.service_token são obrigatórios (sem default,
# de propósito — ver Fase 2 e Etapa 4). Os testes declaram os próprios valores
# aqui, em vez de depender de um .env local que não existe em CI, e sem
# enfraquecer o fail-fast do Settings em produção.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/mpi_test"
)
os.environ.setdefault("SERVICE_TOKEN", "token-de-teste-nao-usar-em-producao")
