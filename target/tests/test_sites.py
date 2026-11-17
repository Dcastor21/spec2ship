from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_site_posts_are_listed(
    client: TestClient, site: dict[str, Any], post: dict[str, Any]
) -> None:
    assert post["site_id"] == site["id"]
    assert client.get(f"/sites/{site['id']}").json() == site
    assert client.get(f"/sites/{site['id']}/posts").json() == [post]


def test_post_on_unknown_site_is_404(client: TestClient) -> None:
    response = client.post("/sites/42/posts", json={"name": "Gate"})
    assert response.status_code == 404
    assert response.json()["detail"] == "site 42 not found"


def test_checkpoint_tag_codes_are_unique(
    client: TestClient, site: dict[str, Any], checkpoint: dict[str, Any]
) -> None:
    assert client.get(f"/sites/{site['id']}/checkpoints").json() == [checkpoint]
    body = {"name": "Roof door", "tag_code": checkpoint["tag_code"]}
    response = client.post(f"/sites/{site['id']}/checkpoints", json=body)
    assert response.status_code == 409
    assert checkpoint["tag_code"] in response.json()["detail"]
