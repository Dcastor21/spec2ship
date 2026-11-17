from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def incident_body(site: dict[str, Any], guard: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body = {
        "site_id": site["id"],
        "guard_id": guard["id"],
        "severity": "medium",
        "summary": "Propped fire door on level 2, closed and logged.",
        "occurred_at": "2026-11-17T09:30:00+00:00",
    }
    return body | overrides


def test_report_and_get_incident(
    client: TestClient, site: dict[str, Any], guard: dict[str, Any]
) -> None:
    response = client.post("/incidents", json=incident_body(site, guard))
    assert response.status_code == 201
    incident = response.json()
    assert incident["severity"] == "medium"
    assert client.get(f"/incidents/{incident['id']}").json() == incident


def test_unknown_severity_is_rejected(
    client: TestClient, site: dict[str, Any], guard: dict[str, Any]
) -> None:
    response = client.post("/incidents", json=incident_body(site, guard, severity="urgent"))
    assert response.status_code == 422


def test_incidents_are_listed_newest_first(
    client: TestClient, site: dict[str, Any], guard: dict[str, Any]
) -> None:
    older = incident_body(site, guard, occurred_at="2026-11-17T09:00:00+00:00")
    newer = incident_body(site, guard, occurred_at="2026-11-17T11:00:00+00:00")
    for body in (older, newer):
        client.post("/incidents", json=body)
    listed = client.get("/incidents").json()
    assert [item["occurred_at"][:19] for item in listed] == [
        "2026-11-17T11:00:00",
        "2026-11-17T09:00:00",
    ]
