from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def shift_body(guard: dict[str, Any], post: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body = {
        "guard_id": guard["id"],
        "post_id": post["id"],
        "starts_at": "2026-11-17T08:00:00+00:00",
        "ends_at": "2026-11-17T16:00:00+00:00",
    }
    return body | overrides


def test_shift_times_are_stored_in_utc(
    client: TestClient, guard: dict[str, Any], post: dict[str, Any]
) -> None:
    body = shift_body(
        guard, post, starts_at="2026-11-17T03:00:00-05:00", ends_at="2026-11-17T11:00:00-05:00"
    )
    response = client.post("/shifts", json=body)
    assert response.status_code == 201
    shift = client.get(f"/shifts/{response.json()['id']}").json()
    assert shift["starts_at"].startswith("2026-11-17T08:00:00")
    assert shift["ends_at"].startswith("2026-11-17T16:00:00")


def test_shift_must_end_after_it_starts(
    client: TestClient, guard: dict[str, Any], post: dict[str, Any]
) -> None:
    for ends_at in ("2026-11-17T08:00:00+00:00", "2026-11-17T08:00:00.500+00:00"):
        response = client.post("/shifts", json=shift_body(guard, post, ends_at=ends_at))
        assert response.status_code == 422, ends_at
        assert "ends_at must be after starts_at" in response.text


def test_shift_for_unknown_guard_is_404(client: TestClient, post: dict[str, Any]) -> None:
    response = client.post("/shifts", json=shift_body({"id": 777}, post))
    assert response.status_code == 404
    assert response.json()["detail"] == "guard 777 not found"


def test_shifts_filter_by_guard(
    client: TestClient, guard: dict[str, Any], post: dict[str, Any]
) -> None:
    other = client.post(
        "/guards",
        json={"name": "Ben Ode", "badge_number": "B-101", "license_expires_on": "2027-06-30"},
    ).json()
    mine = client.post("/shifts", json=shift_body(guard, post)).json()
    client.post("/shifts", json=shift_body(other, post))
    assert client.get("/shifts", params={"guard_id": guard["id"]}).json() == [mine]
    assert len(client.get("/shifts").json()) == 2
