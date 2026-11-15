"""Explicit opt-in integration test against the public OSM service."""

import pytest

from app.gis.coordinates import CenterSelection
from app.models.scene import WorldScene
from app.services.generation import generate


@pytest.mark.integration
def test_live_osm(tmp_path):
    result = generate(
        CenterSelection(latitude=44.6, longitude=33.5, radius_m=500), tmp_path
    )
    restored = WorldScene.model_validate_json(
        result.scene_path.read_text(encoding="utf-8")
    )
    assert restored.buildings
    assert restored.roads
    assert result.preview_path.is_file()
