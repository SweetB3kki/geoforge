"""Ocean datum and conservative fallback must not modify source DSM."""

import pytest
from shapely.geometry import LineString, box

from app.fusion.scene_adapter import ocean_level
from app.gis.elevation import build_terrain
from app.gis.processing import build_scene
from app.models.candidates import CandidateBatch, WaterAttributes, WaterCandidate
from tests.test_elevation import write_dem


def test_ocean_datum_and_shoreline_fallback(features, frame, tmp_path):
    scene = build_scene(features, frame)
    scene.terrain = build_terrain(scene, [write_dem(tmp_path, scene)], 33)
    batch = CandidateBatch(
        crs=scene.metadata.crs,
        origin_easting=scene.origin.easting,
        origin_northing=scene.origin.northing,
    )
    geometry = box(-50, -50, 50, 50)
    scene.terrain.vertical_datum = "EGM2008"
    original = scene.terrain.model_dump_json()
    assert ocean_level(scene, batch, geometry) == (-180, "sea_level_datum")
    assert scene.terrain.model_dump_json() == original
    scene.terrain.vertical_datum = "unspecified"
    batch.candidates.append(
        WaterCandidate(
            candidate_id="osm:coast",
            provider="osm",
            provider_feature_id="way/1",
            geometry=LineString([(-50, -50), (50, -50)]),
            attributes=WaterAttributes(is_coastline=True),
        )
    )
    level, method = ocean_level(scene, batch, geometry)
    assert method == "shoreline_median" and level == pytest.approx(-4.8, abs=0.001)
    batch.candidates.clear()
    assert ocean_level(scene, batch, geometry) == (0, "fallback")
    scene.terrain = None
    assert ocean_level(scene, batch, geometry) == (0, "fallback")
