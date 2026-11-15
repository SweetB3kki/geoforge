"""End-to-end fusion contract, including provider failure and OSM preservation."""

import json

import geopandas as gpd
from shapely.geometry import Polygon

from app.fusion.normalization import normalize
from app.fusion.resolvers import resolve
from app.fusion.scene_adapter import apply_fusion
from app.gis.coordinates import LocalFrame
from app.gis.processing import build_scene
from app.models.scene import WorldScene
from app.providers.base import ProviderResult, ProviderStatus
from app.services.generation import generate
from app.validation.scene_validator import validate_scene
from tests.conftest import StaticProvider


class ExtraProvider:
    def __init__(self, features, fail=False):
        self.features, self.fail = features, fail

    def fetch(self, bbox, kind):
        if self.fail:
            raise RuntimeError("offline test failure")
        rows = (
            self.features
            if kind == "building"
            else gpd.GeoDataFrame(geometry=[], crs=4326)
        )
        return ProviderResult(
            "overture",
            "test-release",
            kind,
            ProviderStatus.SUCCESS if len(rows) else ProviderStatus.EMPTY,
            features=rows,
        )


def no_dem(*args, **kwargs):
    raise RuntimeError("DEM offline test")


def test_auto_generation_enriches_export_without_overwriting_raw(
    features, selection, tmp_path, monkeypatch
):
    monkeypatch.setattr("app.gis.elevation.add_elevation", no_dem)
    extra = gpd.GeoDataFrame(
        [
            {
                "id": "ov-b",
                "height": 23,
                "roof_shape": "flat",
                "geometry": features.geometry.iloc[0],
            }
        ],
        crs=4326,
    )
    result = generate(
        selection,
        tmp_path,
        StaticProvider(features),
        data_mode="auto",
        overture_provider=ExtraProvider(extra),
    )
    scene = WorldScene.model_validate_json(
        result.scene_path.read_text(encoding="utf-8")
    )
    assert scene == result.scene
    assert len(scene.buildings) == 1
    building = scene.buildings[0]
    assert building.height == 23 and building.height_source == "overture_height"
    assert "height" not in building.source_tags
    assert building.resolved_tags["height"] == "23.0"
    assert building.field_provenance["height"]["source"] == "overture"
    assert scene.metadata.schema_version == "1.1"
    assert set(scene.fusion_audit["applied_domains"]) == {
        "buildings",
        "water",
        "building_parts",
        "building_ground",
        "transportation",
    }
    assert any(
        p["provider"] == "copernicus" and p["status"] == "unavailable"
        for p in scene.metadata.providers
    )
    assert json.loads((tmp_path / "scene-quality.json").read_text())["valid"]


def test_auto_unavailable_preserves_osm(features, selection, tmp_path, monkeypatch):
    monkeypatch.setattr("app.gis.elevation.add_elevation", no_dem)
    result = generate(
        selection,
        tmp_path,
        StaticProvider(features),
        data_mode="auto",
        overture_provider=ExtraProvider(None, fail=True),
    )
    baseline = build_scene(features, LocalFrame(selection))
    assert [r.path for r in result.scene.roads] == [r.path for r in baseline.roads]
    assert [r.width for r in result.scene.roads] == [r.width for r in baseline.roads]
    assert len(result.scene.buildings) == len(baseline.buildings)
    for actual, old in zip(result.scene.buildings, baseline.buildings, strict=True):
        assert (actual.id, actual.footprint, actual.height, actual.source_tags) == (
            old.id,
            old.footprint,
            old.height,
            old.source_tags,
        )
    providers = result.scene.metadata.providers
    assert (
        sum(
            p["provider"] == "overture" and p["status"] == "unavailable"
            for p in providers
        )
        == 5
    )


def test_water_dedup_replaces_scene_and_updates_audit(features, frame):
    ring = features.geometry.iloc[0]
    water = gpd.GeoDataFrame(
        [
            {"natural": "water", "geometry": ring},
            {"natural": "water", "geometry": Polygon(ring.exterior)},
        ],
        crs=4326,
    )
    original = build_scene(water, frame)
    batch = normalize(
        [
            ProviderResult(
                "osm", None, "features", ProviderStatus.SUCCESS, features=water
            )
        ],
        frame,
    )
    fused = resolve(batch, frame.boundary)
    scene = apply_fusion(original, batch, fused)
    polygons = [
        Polygon(
            [(p[0], p[1]) for p in a.polygon.exterior],
            [[(p[0], p[1]) for p in h] for h in a.polygon.holes],
        )
        for a in scene.water_areas
    ]
    assert (
        sum(
            a.intersection(b).area
            for i, a in enumerate(polygons)
            for b in polygons[i + 1 :]
        )
        < 1e-8
    )
    assert validate_scene(scene.model_dump(mode="json"))["valid"]
    assert all(r["status"] != "lost" for r in scene.processing_audit["records"])


def test_legacy_osm_building_part_is_not_lost(features, frame):
    features.loc[0, "building:part"] = "yes"
    scene = build_scene(features, frame)
    batch = normalize(
        [
            ProviderResult(
                "osm", None, "features", ProviderStatus.SUCCESS, features=features
            )
        ],
        frame,
    )
    old = scene.buildings[0].model_copy(deep=True)
    apply_fusion(scene, batch, resolve(batch, frame.boundary))
    assert len(scene.buildings) == 1 and scene.buildings[0].footprint == old.footprint
    assert scene.buildings[0].fusion_method == "osm_legacy_preserved"
    assert validate_scene(scene.model_dump(mode="json"))["valid"]
