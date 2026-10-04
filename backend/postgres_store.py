from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.types.json import Jsonb


class PostgresStateStore:
    """Transactional restart-safe store for serverless API invocations.

    Every request locks the single state row before loading the engine snapshot.
    The snapshot is written and committed before the HTTP response is emitted,
    so concurrent receipt consumption still has exactly one winner.
    """

    _table_sql = """
        CREATE TABLE IF NOT EXISTS aegis_state (
            state_id SMALLINT PRIMARY KEY CHECK (state_id = 1),
            snapshot JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """

    def __init__(self, database_url: str):
        if not database_url:
            raise RuntimeError("DATABASE_URL is required")
        self.database_url = database_url

    @contextmanager
    def transaction(self) -> Iterator["PostgresStateTransaction"]:
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._table_sql)
                cursor.execute(
                    """
                    INSERT INTO aegis_state (state_id, snapshot)
                    VALUES (1, %s)
                    ON CONFLICT (state_id) DO NOTHING
                    """,
                    (Jsonb({"policies": {}, "intents": {}, "receipts": {}}),),
                )
                cursor.execute("SELECT snapshot FROM aegis_state WHERE state_id = 1 FOR UPDATE")
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("STATE_ROW_MISSING")
                snapshot = row[0]
                if isinstance(snapshot, str):
                    snapshot = json.loads(snapshot)
                if not isinstance(snapshot, dict):
                    raise ValueError("persisted state root must be an object")
                transaction = PostgresStateTransaction(cursor, snapshot)
                try:
                    yield transaction
                    cursor.execute(
                        "UPDATE aegis_state SET snapshot = %s, updated_at = NOW() WHERE state_id = 1",
                        (Jsonb(transaction.snapshot),),
                    )
                except BaseException:
                    connection.rollback()
                    raise
            connection.commit()

    def load(self) -> dict[str, Any] | None:
        with self.transaction() as transaction:
            return transaction.snapshot

    def save(self, value: dict[str, Any]) -> None:
        with self.transaction() as transaction:
            transaction.replace(value)


class PostgresStateTransaction:
    def __init__(self, cursor: psycopg.Cursor[Any], snapshot: dict[str, Any]):
        self.cursor = cursor
        self.snapshot = snapshot

    def replace(self, value: dict[str, Any]) -> None:
        if not isinstance(value, dict):
            raise ValueError("state snapshot must be an object")
        self.snapshot = value
