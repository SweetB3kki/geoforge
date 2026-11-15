from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, get_provider
from app.gis.input import DownloadError
from tests.conftest import StaticProvider


@pytest.fixture
def client(features, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.main.OUTPUT_DIR", tmp_path)
    app.dependency_overrides[get_provider] = lambda: StaticProvider(features)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_health_and_generate(client):
    assert client.get("/health").json() == {"status": "ok"}
    body = {"latitude": 44.6, "longitude": 33.5, "radius_m": 500}
    first = client.post("/generate", json=body)
    second = client.post("/generate", json=body)
    assert first.status_code == second.status_code == 200
    result = first.json()
    assert result["buildings"] == result["roads"] == 1
    assert result["water_areas"] == result["green_areas"] == 0
    assert Path(result["scene_path"]).is_file()
    assert Path(result["preview_path"]).is_file()
    assert result["scene_path"] != second.json()["scene_path"]


@pytest.mark.parametrize(
    "body",
    [
        {"latitude": 44.6, "longitude": 33.5, "radius_m": -1},
        {"latitude": 90, "longitude": 33.5, "radius_m": 500},
        {"latitude": 44.6, "longitude": 181, "radius_m": 500},
        {"latitude": 0, "longitude": 179.999, "radius_m": 500},
        {"latitude": 44.6},
    ],
)
def test_bad_request(client, body):
    assert client.post("/generate", json=body).status_code == 422


def test_download_failure(client):
    class FailingProvider:
        def fetch(self, bbox):
            raise DownloadError("offline")

    app.dependency_overrides[get_provider] = FailingProvider
    response = client.post(
        "/generate", json={"latitude": 44.6, "longitude": 33.5, "radius_m": 500}
    )
    assert response.status_code == 502
