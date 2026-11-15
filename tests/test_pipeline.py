import json

import geopandas as gpd
import pytest
from pydantic import ValidationError

from app.exporters.json_exporter import export_json
from app.gis.processing import build_scene
from app.models.scene import PolygonModel, Road, WorldScene
from app.services.generation import generate
from tests.conftest import StaticProvider


def test_processing_and_roundtrip(features, frame, tmp_path):
    scene = build_scene(features, frame)
    assert len(scene.buildings) == len(scene.roads) == 1
    assert scene.buildings[0].height == 12
    assert len(scene.buildings[0].footprint.holes) == 1
    assert max(abs(p[0]) for p in scene.roads[0].path) < 500
    path = export_json(scene, tmp_path / "scene.json")
    assert WorldScene.model_validate_json(path.read_text(encoding="utf-8")) == scene
    assert json.loads(path.read_text(encoding="utf-8"))["metadata"]["units"] == "meters"


def test_full_generation(selection, features, tmp_path):
    result = generate(selection, tmp_path, StaticProvider(features))
    assert result.scene_path.is_file()
    assert result.preview_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_empty(selection, tmp_path):
    result = generate(
        selection, tmp_path, StaticProvider(gpd.GeoDataFrame(geometry=[], crs=4326))
    )
    assert result.scene.buildings == result.scene.roads == []
    assert result.preview_path.is_file()


def test_bad_feature_isolated(features, frame):
    features.loc[2, "geometry"] = None
    scene = build_scene(features, frame)
    assert len(scene.buildings) == 1
    assert scene.metadata.skipped_features == 1


def test_models_reject_bad_geometry_and_nonfinite():
    with pytest.raises(ValidationError):
        PolygonModel(exterior=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    with pytest.raises(ValidationError):
        Road(
            id="r", path=[(0, 0, 0), (float("nan"), 1, 0)], road_type="service", width=4
        )
    with pytest.raises(ValidationError):
        Road(id="r", path=[(0, 0, 0), (1, 1, 0)], road_type="service", width=0)
