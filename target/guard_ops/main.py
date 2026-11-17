"""guard_ops FastAPI app. Run with: uv run uvicorn target.guard_ops.main:app"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from target.guard_ops.db import init_schema
from target.guard_ops.routes import guards, incidents, shifts, sites, tours

DEFAULT_DB_PATH = "guard_ops.db"


def create_app(db_path: str | Path | None = None) -> FastAPI:
    """Build the app. The database path comes from the argument, then GUARD_OPS_DB."""
    path = db_path if db_path is not None else os.environ.get("GUARD_OPS_DB", DEFAULT_DB_PATH)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_schema(path)  # on startup, so importing this module never touches disk
        yield

    app = FastAPI(
        title="guard_ops",
        version="0.1.0",
        description=(
            "Physical-security workforce operations: guards, sites and posts, shifts, "
            "guard tours and incidents. A demo target for spec2ship."
        ),
        lifespan=lifespan,
    )
    app.state.db_path = path
    for module in (guards, sites, shifts, tours, incidents):
        app.include_router(module.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
