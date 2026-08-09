import os

# Settings.database_url é obrigatório (sem default, de propósito — ver Fase 2). Os
# testes declaram aqui o próprio valor, em vez de depender de um .env local que não
# existe em CI, e sem enfraquecer o fail-fast do Settings em produção.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/mpi_test"
)
