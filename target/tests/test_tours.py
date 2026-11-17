from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

T0 = "2026-11-17T08:00:00+00:00"


def start_tour(client: TestClient, site: dict[str, Any], guard: dict[str, Any]) -> dict[str, Any]:
    body = {"site_id": site["id"], "guard_id": guard["id"], "started_at": T0}
    response = client.post("/tours", json=body)
    assert response.status_code == 201, response.text
    tour: dict[str, Any] = response.json()
    return tour


def test_scans_are_recorded_in_time_order(
    client: TestClient,
    site: dict[str, Any],
    guard: dict[str, Any],
    checkpoint: dict[str, Any],
) -> None:
    second = client.post(
        f"/sites/{site['id']}/checkpoints", json={"name": "Roof door", "tag_code": "NFC-002"}
    ).json()
    tour = start_tour(client, site, guard)
    assert tour["scans"] == []
    late = {"tag_code": "NFC-002", "scanned_at": "2026-11-17T08:20:00+00:00"}
    early = {"tag_code": "NFC-001", "scanned_at": "2026-11-17T08:05:00+00:00"}
    assert client.post(f"/tours/{tour['id']}/scans", json=late).status_code == 201
    assert client.post(f"/tours/{tour['id']}/scans", json=early).status_code == 201
    scans = client.get(f"/tours/{tour['id']}").json()["scans"]
    assert [scan["checkpoint_id"] for scan in scans] == [checkpoint["id"], second["id"]]


def test_unknown_tag_is_rejected(
    client: TestClient, site: dict[str, Any], guard: dict[str, Any]
) -> None:
    tour = start_tour(client, site, guard)
    scan = {"tag_code": "NFC-404", "scanned_at": "2026-11-17T08:05:00+00:00"}
    response = client.post(f"/tours/{tour['id']}/scans", json=scan)
    assert response.status_code == 422
    assert "NFC-404" in response.json()["detail"]


def test_tag_from_another_site_is_rejected(
    client: TestClient, site: dict[str, Any], guard: dict[str, Any]
) -> None:
    other = client.post("/sites", json={"name": "Depot", "address": "9 Rail St"}).json()
    setup = client.post(
        f"/sites/{other['id']}/checkpoints", json={"name": "Gate", "tag_code": "NFC-900"}
    )
    assert setup.status_code == 201, setup.text  # else this repeats the unknown-tag test
    tour = start_tour(client, site, guard)
    scan = {"tag_code": "NFC-900", "scanned_at": "2026-11-17T08:05:00+00:00"}
    response = client.post(f"/tours/{tour['id']}/scans", json=scan)
    assert response.status_code == 422
    assert f"site {site['id']}" in response.json()["detail"]


def test_scan_before_tour_start_is_rejected(
    client: TestClient, site: dict[str, Any], guard: dict[str, Any], checkpoint: dict[str, Any]
) -> None:
    tour = start_tour(client, site, guard)
    scan = {"tag_code": checkpoint["tag_code"], "scanned_at": "2026-11-17T07:59:00+00:00"}
    response = client.post(f"/tours/{tour['id']}/scans", json=scan)
    assert response.status_code == 422
    assert "before the tour started" in response.json()["detail"]
