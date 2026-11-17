"""Sites, the posts staffed at each site, and the tour checkpoints placed there."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, status

from target.guard_ops.db import Db, insert, require, row_dict
from target.guard_ops.models import (
    Checkpoint,
    CheckpointCreate,
    Post,
    PostCreate,
    Site,
    SiteCreate,
)

router = APIRouter(prefix="/sites", tags=["sites"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_site(body: SiteCreate, db: Db) -> Site:
    site_id = insert(
        db, "INSERT INTO sites (name, address) VALUES (?, ?)", (body.name, body.address)
    )
    return Site.model_validate(row_dict(require(db, "site", site_id)))


@router.get("")
def list_sites(db: Db) -> list[Site]:
    rows = db.execute("SELECT * FROM sites ORDER BY id").fetchall()
    return [Site.model_validate(row_dict(row)) for row in rows]


@router.get("/{site_id}")
def get_site(site_id: int, db: Db) -> Site:
    return Site.model_validate(row_dict(require(db, "site", site_id)))


@router.post("/{site_id}/posts", status_code=status.HTTP_201_CREATED)
def create_post(site_id: int, body: PostCreate, db: Db) -> Post:
    require(db, "site", site_id)
    try:
        post_id = insert(
            db, "INSERT INTO posts (site_id, name) VALUES (?, ?)", (site_id, body.name)
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"site {site_id} already has a post named {body.name!r}",
        ) from exc
    return Post.model_validate(row_dict(require(db, "post", post_id)))


@router.get("/{site_id}/posts")
def list_posts(site_id: int, db: Db) -> list[Post]:
    require(db, "site", site_id)
    rows = db.execute("SELECT * FROM posts WHERE site_id = ? ORDER BY id", (site_id,)).fetchall()
    return [Post.model_validate(row_dict(row)) for row in rows]


@router.post("/{site_id}/checkpoints", status_code=status.HTTP_201_CREATED)
def create_checkpoint(site_id: int, body: CheckpointCreate, db: Db) -> Checkpoint:
    require(db, "site", site_id)
    try:
        checkpoint_id = insert(
            db,
            "INSERT INTO checkpoints (site_id, name, tag_code) VALUES (?, ?, ?)",
            (site_id, body.name, body.tag_code),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"tag code {body.tag_code!r} is already used by another checkpoint",
        ) from exc
    row = db.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
    return Checkpoint.model_validate(row_dict(row))


@router.get("/{site_id}/checkpoints")
def list_checkpoints(site_id: int, db: Db) -> list[Checkpoint]:
    require(db, "site", site_id)
    rows = db.execute(
        "SELECT * FROM checkpoints WHERE site_id = ? ORDER BY id", (site_id,)
    ).fetchall()
    return [Checkpoint.model_validate(row_dict(row)) for row in rows]
