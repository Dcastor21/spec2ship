"""Shifts: a guard assigned to a post for a time window."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from target.guard_ops.db import Db, insert, require, row_dict, utc_text
from target.guard_ops.models import Shift, ShiftCreate

router = APIRouter(prefix="/shifts", tags=["shifts"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_shift(body: ShiftCreate, db: Db) -> Shift:
    require(db, "guard", body.guard_id)
    require(db, "post", body.post_id)
    shift_id = insert(
        db,
        "INSERT INTO shifts (guard_id, post_id, starts_at, ends_at) VALUES (?, ?, ?, ?)",
        (body.guard_id, body.post_id, utc_text(body.starts_at), utc_text(body.ends_at)),
    )
    return Shift.model_validate(row_dict(require(db, "shift", shift_id)))


@router.get("")
def list_shifts(
    db: Db,
    guard_id: Annotated[int | None, Query()] = None,
    post_id: Annotated[int | None, Query()] = None,
) -> list[Shift]:
    rows = db.execute(
        "SELECT * FROM shifts"
        " WHERE (? IS NULL OR guard_id = ?) AND (? IS NULL OR post_id = ?)"
        " ORDER BY starts_at, id",
        (guard_id, guard_id, post_id, post_id),
    ).fetchall()
    return [Shift.model_validate(row_dict(row)) for row in rows]


@router.get("/{shift_id}")
def get_shift(shift_id: int, db: Db) -> Shift:
    return Shift.model_validate(row_dict(require(db, "shift", shift_id)))
