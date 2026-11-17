"""Shared fixtures: a client on a fresh SQLite file per test, and a few seeded records."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from target.guard_ops.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(tmp_path / "guard_ops.db")) as test_client:
        yield test_client


def created(client: TestClient, url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(url, json=body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


@pytest.fixture
def guard(client: TestClient) -> dict[str, Any]:
    body = {"name": "Ana Reyes", "badge_number": "B-100", "license_expires_on": "2027-06-30"}
    return created(client, "/guards", body)


@pytest.fixture
def site(client: TestClient) -> dict[str, Any]:
    return created(client, "/sites", {"name": "Harbor Tower", "address": "1 Pier Rd"})


@pytest.fixture
def post(client: TestClient, site: dict[str, Any]) -> dict[str, Any]:
    return created(client, f"/sites/{site['id']}/posts", {"name": "Lobby desk"})


@pytest.fixture
def checkpoint(client: TestClient, site: dict[str, Any]) -> dict[str, Any]:
    body = {"name": "Loading dock", "tag_code": "NFC-001"}
    return created(client, f"/sites/{site['id']}/checkpoints", body)
