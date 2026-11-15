import copy

import geopandas as gpd
import pytest

from app.gis.processing import build_scene
from app.validation.scene_validator import validate_scene


@pytest.fixture
def data(features, frame):
    return build_scene(features, frame).model_dump(mode="json")


def codes(data):
    return {w["code"] for w in validate_scene(data)["warnings"]}


def test_valid_source_stats(data):
    q = validate_scene(data)
    assert q["valid"]
    assert q["buildings"]["height_source"] == {"levels": 1}
    assert q["buildings"]["holes"] == 1
    assert q["roads"]["lostSegments"] == 0


@pytest.mark.parametrize("key", ["bounds", "origin", "metadata", "roads"])
def test_missing_field(data, key):
    del data[key]
    assert not validate_scene(data)["valid"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite(data, value):
    data["buildings"][0]["height"] = value
    assert not validate_scene(data)["valid"]


def test_duplicates(data):
    data["buildings"].append(copy.deepcopy(data["buildings"][0]))
    assert {"duplicate_or_empty_id", "duplicate_geometry"} <= codes(data)


def test_invalid_polygon(data):
    data["buildings"][0]["footprint"] = {
        "exterior": [[0, 0, 0], [10, 10, 0], [10, 0, 0], [0, 10, 0], [0, 0, 0]],
        "holes": [],
    }
    assert "invalid_geometry" in codes(data)


def test_lost_road(data):
    data["roads"] = []
    assert "lost_object" in codes(data)


def test_unexplained_filter(data):
    r = data["processing_audit"]["records"][0]
    r["status"], r["skip_reason"] = "filtered", None
    assert "unexplained_filter" in codes(data)


def test_legacy(data):
    del data["processing_audit"]
    assert validate_scene(data)["valid"]
    assert "source_audit_unavailable" in codes(data)


def test_coastline_is_diagnostic(features, frame):
    features.loc[1, "highway"] = None
    features.loc[1, "natural"] = "coastline"
    scene = build_scene(features, frame)
    q = validate_scene(scene.model_dump(mode="json"))
    assert q["water"]["coastlineWayCount"] == 1
    assert "coastline_without_surface" in codes(scene.model_dump(mode="json"))
    assert scene.water_areas == []
    assert (
        scene.processing_audit["records"][1]["skip_reason"]
        == "coastal_reconstruction_not_implemented"
    )


def test_empty_has_known_zero_source(frame):
    scene = build_scene(gpd.GeoDataFrame(geometry=[], crs=4326), frame)
    q = validate_scene(scene.model_dump(mode="json"))
    assert q["source"]["raw_features"] == 0


def test_water_and_green_inventory(features, frame):
    features.loc[0, "building"] = None
    features.loc[0, "natural"] = "water"
    q = validate_scene(build_scene(features, frame).model_dump(mode="json"))
    assert q["water"]["waterPolygonCount"] == 1
    assert q["water"]["waterCoverageArea"] == pytest.approx(9600)


def test_link_tags_survive_trace(features, frame):
    features.loc[1, "highway"] = "primary_link"
    tags = {
        "lanes:forward": "2",
        "lanes:backward": "1",
        "oneway": "yes",
        "bridge": "yes",
        "layer": "1",
        "width": "8",
        "ref": "A1",
    }
    for k, v in tags.items():
        features.loc[1, k] = v
    s = build_scene(features, frame)
    r = s.roads[0]
    assert r.road_subtype == "link"
    assert r.width == 8
    assert r.bridge and r.oneway == 1
    assert all(r.source_tags[k] == v for k, v in tags.items())
    assert s.processing_audit["records"][1]["output_ids"] == [r.id]


def test_combined_report_requires_real_unity_evidence(data, tmp_path):
    import json

    from app.validation.quality_report import combine

    (tmp_path / "scene-quality.json").write_text(
        json.dumps(validate_scene(data)), encoding="utf-8"
    )
    q = json.loads(combine(tmp_path).read_text(encoding="utf-8"))
    assert q["unity"] is None
    assert any(w["code"] == "unity_audit_unavailable" for w in q["warnings"])


def test_combined_report_rejects_stale_unity(data, tmp_path):
    import json

    from app.validation.quality_report import combine

    (tmp_path / "scene-quality.json").write_text(
        json.dumps(validate_scene(data)), encoding="utf-8"
    )
    (tmp_path / "scene.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "unity-quality.json").write_text(
        '{"scene_sha256":"wrong"}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="SHA256"):
        combine(tmp_path)
