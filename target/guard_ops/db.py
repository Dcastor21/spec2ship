"""SQLite access: schema, per-request connections and small lookup helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Request, status

SCHEMA = """
CREATE TABLE IF NOT EXISTS guards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    badge_number TEXT NOT NULL UNIQUE,
    license_expires_on TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites (id),
    name TEXT NOT NULL,
    UNIQUE (site_id, name)
);
CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY,
    guard_id INTEGER NOT NULL REFERENCES guards (id),
    post_id INTEGER NOT NULL REFERENCES posts (id),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites (id),
    name TEXT NOT NULL,
    tag_code TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS tours (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites (id),
    guard_id INTEGER NOT NULL REFERENCES guards (id),
    started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_events (
    id INTEGER PRIMARY KEY,
    tour_id INTEGER NOT NULL REFERENCES tours (id),
    checkpoint_id INTEGER NOT NULL REFERENCES checkpoints (id),
    scanned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites (id),
    guard_id INTEGER NOT NULL REFERENCES guards (id),
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    summary TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
"""

SqlParam = str | int | float | None
Entity = Literal["guard", "site", "post", "tour", "incident", "shift"]

# Fixed queries keyed by entity, so no SQL is ever built from strings.
_LOOKUPS: dict[Entity, str] = {
    "guard": "SELECT * FROM guards WHERE id = ?",
    "site": "SELECT * FROM sites WHERE id = ?",
    "post": "SELECT * FROM posts WHERE id = ?",
    "tour": "SELECT * FROM tours WHERE id = ?",
    "incident": "SELECT * FROM incidents WHERE id = ?",
    "shift": "SELECT * FROM shifts WHERE id = ?",
}


def connect(db_path: str | Path) -> sqlite3.Connection:
    # FastAPI may run a sync dependency and its endpoint on different threadpool
    # threads; each connection still serves exactly one request at a time.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(db_path: str | Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(zip(row.keys(), row, strict=True))


def require(db: sqlite3.Connection, entity: Entity, entity_id: int) -> sqlite3.Row:
    """Return the row, or raise 404 naming what was missing."""
    row: sqlite3.Row | None = db.execute(_LOOKUPS[entity], (entity_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{entity} {entity_id} not found")
    return row


def insert(db: sqlite3.Connection, sql: str, params: tuple[SqlParam, ...]) -> int:
    """Run one INSERT in its own transaction and return the new row id."""
    with db:
        cursor = db.execute(sql, params)
    if cursor.lastrowid is None:  # pragma: no cover - sqlite sets it for every INSERT
        raise RuntimeError("INSERT did not return a row id")
    return cursor.lastrowid


def utc_text(value: datetime) -> str:
    """Store timestamps as fixed-width UTC ISO 8601, so text order is time order."""
    return value.astimezone(UTC).isoformat(timespec="seconds")
