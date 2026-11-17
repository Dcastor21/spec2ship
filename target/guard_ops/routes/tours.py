"""Guard tours: a guard walks a site and scans the checkpoint tags they pass."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from target.guard_ops.db import Db, insert, require, row_dict, utc_text
from target.guard_ops.models import ScanCreate, ScanEvent, Tour, TourCreate

router = APIRouter(prefix="/tours", tags=["tours"])


def _load_tour(db: sqlite3.Connection, tour_id: int) -> Tour:
    tour = row_dict(require(db, "tour", tour_id))
    scans = db.execute(
        "SELECT * FROM scan_events WHERE tour_id = ? ORDER BY scanned_at, id", (tour_id,)
    ).fetchall()
    tour["scans"] = [row_dict(scan) for scan in scans]
    return Tour.model_validate(tour)


@router.post("", status_code=status.HTTP_201_CREATED)
def start_tour(body: TourCreate, db: Db) -> Tour:
    require(db, "site", body.site_id)
    require(db, "guard", body.guard_id)
    tour_id = insert(
        db,
        "INSERT INTO tours (site_id, guard_id, started_at) VALUES (?, ?, ?)",
        (body.site_id, body.guard_id, utc_text(body.started_at)),
    )
    return _load_tour(db, tour_id)


@router.get("/{tour_id}")
def get_tour(tour_id: int, db: Db) -> Tour:
    return _load_tour(db, tour_id)


@router.post("/{tour_id}/scans", status_code=status.HTTP_201_CREATED)
def record_scan(tour_id: int, body: ScanCreate, db: Db) -> ScanEvent:
    tour = require(db, "tour", tour_id)
    checkpoint = db.execute(
        "SELECT id FROM checkpoints WHERE tag_code = ? AND site_id = ?",
        (body.tag_code, tour["site_id"]),
    ).fetchone()
    if checkpoint is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"tag {body.tag_code!r} is not a checkpoint at site {tour['site_id']}",
        )
    if body.scanned_at < datetime.fromisoformat(tour["started_at"]):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"scan at {body.scanned_at.isoformat()} is before the tour started",
        )
    scan_id = insert(
        db,
        "INSERT INTO scan_events (tour_id, checkpoint_id, scanned_at) VALUES (?, ?, ?)",
        (tour_id, checkpoint["id"], utc_text(body.scanned_at)),
    )
    row = db.execute("SELECT * FROM scan_events WHERE id = ?", (scan_id,)).fetchone()
    return ScanEvent.model_validate(row_dict(row))
