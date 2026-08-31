"""Persistência da revisão humana (R6): processos e trilha de auditoria.

A R6 exige audit log com usuário, timestamp, anterior e posterior, e a R10
exige reprocessar sem apagá-lo. Estado em memória perde os dois no primeiro
restart, então a persistência é parte do requisito, não infraestrutura
opcional.

Duas implementações com o mesmo contrato: ``InMemoryStorage``, para teste e
para uso local sem banco, e ``PostgresStorage``, que é o modo em que a fase
fecha.
"""

from __future__ import annotations

import json
from typing import Protocol

import psycopg

from licita_core.schema import ProcurementProcess
from licita_review.models import ReviewAuditEntry

# A imutabilidade do audit log é garantida no banco, não só na aplicação: um
# UPDATE ou DELETE em review_audit levanta exceção.
DDL = """
CREATE TABLE IF NOT EXISTS {schema}.review_process (
    id          text PRIMARY KEY,
    payload     jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {schema}.review_audit (
    id            uuid PRIMARY KEY,
    process_id    text NOT NULL REFERENCES {schema}.review_process (id),
    registered_at timestamptz NOT NULL DEFAULT now(),
    entry         jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS review_audit_process_idx
    ON {schema}.review_audit (process_id, registered_at);

CREATE OR REPLACE FUNCTION {schema}.review_audit_imutavel() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit log é imutável: % não é permitido em review_audit', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER review_audit_sem_alteracao
    BEFORE UPDATE OR DELETE ON {schema}.review_audit
    FOR EACH ROW EXECUTE FUNCTION {schema}.review_audit_imutavel();
"""


class ReviewStorage(Protocol):
    """Contrato de persistência da revisão humana."""

    def save_process(self, process: ProcurementProcess) -> None: ...

    def load_process(self, process_id: str) -> ProcurementProcess | None: ...

    def process_ids(self) -> list[str]: ...

    def append_audit(self, entry: ReviewAuditEntry) -> None: ...

    def audit_trail(self, process_id: str) -> list[ReviewAuditEntry]: ...


class InMemoryStorage:
    """Estado em memória: some no restart, serve a teste e a uso sem banco."""

    def __init__(self) -> None:
        self._processes: dict[str, ProcurementProcess] = {}
        self._audit: dict[str, list[ReviewAuditEntry]] = {}

    def save_process(self, process: ProcurementProcess) -> None:
        self._processes[process.id] = process
        self._audit.setdefault(process.id, [])

    def load_process(self, process_id: str) -> ProcurementProcess | None:
        return self._processes.get(process_id)

    def process_ids(self) -> list[str]:
        return list(self._processes)

    def append_audit(self, entry: ReviewAuditEntry) -> None:
        self._audit.setdefault(entry.process_id, []).append(entry)

    def audit_trail(self, process_id: str) -> list[ReviewAuditEntry]:
        return list(self._audit.get(process_id, []))


class PostgresStorage:
    """Persistência em PostgreSQL, uma conexão por operação.

    A conexão por chamada custa um round-trip a mais e dispensa ciclo de vida
    de pool numa UI onde as ações vêm de cliques humanos. A senha nunca é
    lida pela aplicação: o ``conninfo`` não a carrega e o libpq resolve por
    ``~/.pgpass``, variável de ambiente ou o que o operador tiver configurado.
    """

    def __init__(self, conninfo: str, *, schema: str = "public") -> None:
        if not schema.isidentifier():
            raise ValueError(f"Schema inválido: {schema!r}")
        self._conninfo = conninfo
        self._schema = schema

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._conninfo, autocommit=True)

    def migrate(self) -> None:
        """Cria schema e tabelas se ainda não existirem."""
        with self._connect() as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            conn.execute(DDL.format(schema=self._schema))

    def drop(self) -> None:
        """Remove tudo. Existe para o teste de integração se limpar."""
        with self._connect() as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {self._schema} CASCADE")

    def save_process(self, process: ProcurementProcess) -> None:
        payload = json.dumps(process.model_dump(mode="json"))
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.review_process (id, payload, updated_at)
                VALUES (%s, %s::jsonb, now())
                ON CONFLICT (id) DO UPDATE
                    SET payload = EXCLUDED.payload, updated_at = now()
                """,
                (process.id, payload),
            )

    def load_process(self, process_id: str) -> ProcurementProcess | None:
        with self._connect() as conn:
            linha = conn.execute(
                f"SELECT payload FROM {self._schema}.review_process WHERE id = %s",
                (process_id,),
            ).fetchone()
        if linha is None:
            return None
        return ProcurementProcess.model_validate(linha[0])

    def process_ids(self) -> list[str]:
        with self._connect() as conn:
            linhas = conn.execute(
                f"SELECT id FROM {self._schema}.review_process ORDER BY id"
            ).fetchall()
        return [linha[0] for linha in linhas]

    def append_audit(self, entry: ReviewAuditEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.review_audit (id, process_id, registered_at, entry)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (
                    entry.id,
                    entry.process_id,
                    entry.timestamp,
                    json.dumps(entry.model_dump(mode="json")),
                ),
            )

    def audit_trail(self, process_id: str) -> list[ReviewAuditEntry]:
        with self._connect() as conn:
            linhas = conn.execute(
                f"""
                SELECT entry FROM {self._schema}.review_audit
                WHERE process_id = %s
                ORDER BY registered_at, id
                """,
                (process_id,),
            ).fetchall()
        return [ReviewAuditEntry.model_validate(linha[0]) for linha in linhas]
