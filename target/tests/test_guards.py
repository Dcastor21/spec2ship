from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_create_and_get_guard(client: TestClient, guard: dict[str, Any]) -> None:
    assert guard["active"] is True
    assert guard["badge_number"] == "B-100"
    assert client.get(f"/guards/{guard['id']}").json() == guard
    assert client.get("/guards").json() == [guard]


def test_duplicate_badge_is_a_conflict(client: TestClient, guard: dict[str, Any]) -> None:
    body = {"name": "Other", "badge_number": "B-100", "license_expires_on": "2027-01-01"}
    response = client.post("/guards", json=body)
    assert response.status_code == 409
    assert "B-100" in response.json()["detail"]


def test_unknown_guard_is_404(client: TestClient) -> None:
    response = client.get("/guards/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "guard 999 not found"


def test_blank_name_is_rejected(client: TestClient) -> None:
    body = {"name": "   ", "badge_number": "B-200", "license_expires_on": "2027-01-01"}
    assert client.post("/guards", json=body).status_code == 422
