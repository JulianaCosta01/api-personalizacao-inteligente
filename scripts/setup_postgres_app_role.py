"""Cria ou atualiza a role `mpi_app`, de privilégio mínimo, usada pela API e pelo Worker.

Idempotente. Lê as credenciais do .env e nunca imprime nem grava senhas.

Uso:
    python scripts/setup_postgres_app_role.py
"""

import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _ler_env(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not caminho.exists():
        return valores
    for linha_bruta in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha_bruta.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip()
    return valores


def _exigir(env: dict[str, str], chave: str) -> str:
    valor = env.get(chave) or os.environ.get(chave)
    if not valor:
        sys.exit(f"Erro: {chave} não definido no .env. Veja .env.example para o que adicionar.")
    return valor


def _escapar_literal_sql(valor: str) -> str:
    # Forma padrão de literal de string em SQL: aspas simples embutidas se
    # escapam dobrando-as, nunca com barra invertida.
    return valor.replace("'", "''")


def main() -> None:
    env = _ler_env(RAIZ / ".env")

    admin_user = _exigir(env, "POSTGRES_USER")
    admin_password = _exigir(env, "POSTGRES_PASSWORD")
    banco = env.get("POSTGRES_DB") or os.environ.get("POSTGRES_DB") or "mpi"
    app_user = env.get("POSTGRES_APP_USER") or os.environ.get("POSTGRES_APP_USER") or "mpi_app"
    app_password = _exigir(env, "POSTGRES_APP_PASSWORD")

    # Viram identificador SQL entre aspas duplas abaixo: aspas embutidas
    # quebrariam a sintaxe, então são rejeitadas em vez de escapadas.
    identificadores = (
        ("POSTGRES_USER", admin_user),
        ("POSTGRES_APP_USER", app_user),
        ("POSTGRES_DB", banco),
    )
    for nome, valor in identificadores:
        if '"' in valor:
            sys.exit(f"Erro: {nome} não pode conter aspas duplas (valor atual é inválido).")

    senha_role_sql = _escapar_literal_sql(app_password)
    app_user_literal_sql = _escapar_literal_sql(app_user)

    sql = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{app_user_literal_sql}') THEN
        CREATE ROLE "{app_user}" LOGIN PASSWORD '{senha_role_sql}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE;
    ELSE
        ALTER ROLE "{app_user}" WITH LOGIN PASSWORD '{senha_role_sql}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE "{banco}" TO "{app_user}";
GRANT USAGE ON SCHEMA public TO "{app_user}";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{app_user}";

-- Tabelas futuras criadas pelo admin (Alembic) já nascem acessíveis para a
-- role de runtime, sem precisar lembrar de reconceder a cada migration nova.
ALTER DEFAULT PRIVILEGES FOR ROLE "{admin_user}" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_user}";
"""

    ambiente = os.environ.copy()
    ambiente["PGPASSWORD"] = admin_password

    comando = [
        "docker",
        "compose",
        "exec",
        "-T",
        "-e",
        "PGPASSWORD",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        admin_user,
        "-d",
        banco,
    ]

    print(f"Aplicando role '{app_user}' (privilégio mínimo) no banco '{banco}'...")
    resultado = subprocess.run(comando, input=sql, text=True, env=ambiente, cwd=RAIZ)
    if resultado.returncode != 0:
        sys.exit(f"Falha ao aplicar a role (código {resultado.returncode}). Veja a saída acima.")
    print("Role aplicada com sucesso.")


if __name__ == "__main__":
    main()
