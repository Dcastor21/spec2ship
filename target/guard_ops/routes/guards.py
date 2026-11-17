"""Guards: the people who staff posts and walk tours."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, status

from target.guard_ops.db import Db, insert, require, row_dict
from target.guard_ops.models import Guard, GuardCreate

router = APIRouter(prefix="/guards", tags=["guards"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_guard(body: GuardCreate, db: Db) -> Guard:
    try:
        guard_id = insert(
            db,
            "INSERT INTO guards (name, badge_number, license_expires_on) VALUES (?, ?, ?)",
            (body.name, body.badge_number, body.license_expires_on.isoformat()),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"badge number {body.badge_number!r} is already in use",
        ) from exc
    return Guard.model_validate(row_dict(require(db, "guard", guard_id)))


@router.get("")
def list_guards(db: Db) -> list[Guard]:
    rows = db.execute("SELECT * FROM guards ORDER BY id").fetchall()
    return [Guard.model_validate(row_dict(row)) for row in rows]


@router.get("/{guard_id}")
def get_guard(guard_id: int, db: Db) -> Guard:
    return Guard.model_validate(row_dict(require(db, "guard", guard_id)))
