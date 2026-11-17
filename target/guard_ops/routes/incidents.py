"""Incident reports filed by guards at a site."""

from __future__ import annotations

from fastapi import APIRouter, status

from target.guard_ops.db import Db, insert, require, row_dict, utc_text
from target.guard_ops.models import Incident, IncidentCreate

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", status_code=status.HTTP_201_CREATED)
def report_incident(body: IncidentCreate, db: Db) -> Incident:
    require(db, "site", body.site_id)
    require(db, "guard", body.guard_id)
    incident_id = insert(
        db,
        "INSERT INTO incidents (site_id, guard_id, severity, summary, occurred_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            body.site_id,
            body.guard_id,
            body.severity.value,
            body.summary,
            utc_text(body.occurred_at),
        ),
    )
    return Incident.model_validate(row_dict(require(db, "incident", incident_id)))


@router.get("")
def list_incidents(db: Db) -> list[Incident]:
    """All incidents, newest first."""
    rows = db.execute("SELECT * FROM incidents ORDER BY occurred_at DESC, id DESC").fetchall()
    return [Incident.model_validate(row_dict(row)) for row in rows]


@router.get("/{incident_id}")
def get_incident(incident_id: int, db: Db) -> Incident:
    return Incident.model_validate(row_dict(require(db, "incident", incident_id)))
