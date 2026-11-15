import geopandas as gpd
import pytest
from shapely.geometry import box
from shapely.strtree import STRtree

from app.fusion.buildings import ground_estimate, polygon, strategy
from app.fusion.resolvers import resolve
from app.fusion.scene_adapter import apply_fusion
from app.gis.processing import build_scene
from app.models.candidates import (
    BuildingAttributes,
    BuildingPartCandidate,
    CandidateBatch,
)
from app.models.scene import BuildingAvailability, TerrainData, WorldScene
from app.validation.scene_validator import validate_scene
from tests.test_fusion import building


def part(identifier, geometry, provider="overture", **attributes):
    return BuildingPartCandidate(
        candidate_id=f"{provider}:building_part:{identifier}",
        provider=provider,
        provider_feature_id=identifier,
        geometry=geometry,
        attributes=BuildingAttributes(**attributes),
    )


def generate(frame, candidates):
    scene = build_scene(gpd.GeoDataFrame(geometry=[], crs=4326), frame)
    batch = CandidateBatch(
        crs=frame.crs.to_string(),
        origin_easting=frame.easting,
        origin_northing=frame.northing,
        candidates=candidates,
    )
    apply_fusion(scene, batch, resolve(batch, frame.boundary))
    assert validate_scene(scene.model_dump(mode="json"))["valid"]
    assert WorldScene.model_validate_json(scene.model_dump_json()) == scene
    return scene


def test_parts_replace_monolith_keep_open_passage_and_explicit_roof(frame):
    scene = generate(
        frame,
        [
            building("parent", "overture", box(0, 0, 20, 10), height=20),
            part("low", box(0, 0, 10, 10), parent_building_id="parent", height=10),
            part(
                "raised",
                box(10, 0, 20, 10),
                parent_building_id="parent",
                height=20,
                min_height=5,
                roof_height=2,
                roof_shape="gabled",
            ),
        ],
    )
    parent = scene.buildings[0]
    assert parent.strategy_used == "PARTS_EXPLICIT" and parent.render_footprints == []
    assert len(parent.parts) == 2
    raised = next(p for p in parent.parts if p.min_height > 0)
    assert raised.height == 20 and raised.min_height == 5
    assert raised.resolved_tags["roof:height"] == "2.0"
    assert all(p.parent_id == parent.id for p in parent.parts)


def test_partial_parts_only_extrude_uncovered_parent_and_allow_overhang(frame):
    scene = generate(
        frame,
        [
            building("parent", "overture", box(0, 0, 20, 10), height=20),
            part("wing", box(-5, 0, 10, 10), parent_building_id="parent", height=12),
        ],
    )
    parent = scene.buildings[0]
    assert polygon(parent.parts[0].footprint).bounds[0] == -5
    assert sum(polygon(p).area for p in parent.render_footprints) == pytest.approx(100)
    assert all(
        polygon(p).intersection(polygon(parent.parts[0].footprint)).area == 0
        for p in parent.render_footprints
    )


def test_osm_part_priority_and_min_floor(frame):
    scene = generate(
        frame,
        [
            building("parent", "overture", box(0, 0, 20, 10), height=20),
            part("ov", box(0, 0, 10, 10), parent_building_id="parent", height=15),
            part(
                "way/1",
                box(0, 0, 10, 10),
                provider="osm",
                floors=3,
                min_floor=1,
                height=11,
            ),
        ],
    )
    parent = scene.buildings[0]
    assert len(parent.parts) == 1
    assert parent.parts[0].height == 11 and parent.parts[0].min_height == 3
    assert scene.fusion_audit["conflicts"]


def test_invalid_part_interval_reverts_to_parent(frame):
    scene = generate(
        frame,
        [
            building("parent", "overture", box(0, 0, 20, 10), height=20),
            part(
                "bad",
                box(0, 0, 20, 10),
                parent_building_id="parent",
                height=5,
                min_height=8,
            ),
        ],
    )
    assert (
        scene.buildings[0].parts == [] and scene.buildings[0].render_footprints is None
    )
    assert any(
        w["reason"] == "invalid_part_vertical_interval"
        for w in scene.fusion_audit["warnings"]
    )


def test_osm_orphan_part_becomes_standalone_volume(frame):
    scene = generate(
        frame, [part("way/1", box(0, 0, 10, 10), provider="osm", height=14)]
    )
    assert len(scene.buildings) == 1 and len(scene.buildings[0].parts) == 1
    assert scene.buildings[0].parts[0].height == 14


@pytest.mark.parametrize(
    "profile,kind,expected",
    [
        (
            BuildingAvailability(parts=2, explicit_height=True),
            "house",
            "PARTS_EXPLICIT",
        ),
        (BuildingAvailability(explicit_height=True), "house", "EXPLICIT_HEIGHT"),
        (BuildingAvailability(floors=True), "house", "FLOORS_ESTIMATED"),
        (BuildingAvailability(), "garage", "TYPE_BASED_FALLBACK"),
        (BuildingAvailability(), "yes", "GENERIC_FALLBACK"),
    ],
)
def test_strategy_uses_availability(profile, kind, expected):
    assert strategy(profile, kind) == expected


def test_ground_ignores_building_dsm_spike_and_preserves_raw():
    footprint = box(-20, -20, 20, 20)
    heights = [
        40.0 if -20 <= x <= 20 and -20 <= y <= 20 else 3.0
        for y in range(-100, 101, 10)
        for x in range(-100, 101, 10)
    ]
    terrain = TerrainData(
        resolution_x=21,
        resolution_y=21,
        origin=(-100, -100, 0),
        cell_size=(10, 10),
        heights=heights,
        valid_mask=[True] * 441,
        min_height=3,
        max_height=40,
        height_offset_m=0,
        source="fixture",
        attribution="fixture",
    )
    raw = terrain.model_dump_json()
    value, method, audit = ground_estimate(
        terrain, footprint, STRtree([footprint]), box(-100, -100, 100, 100)
    )
    assert value == 3 and method == "surrounding_p35"
    assert audit["old_footprint_median"] == 40
    from shapely.geometry import Point

    assert all(not footprint.covers(Point(x, y)) for x, y in audit["sample_points"])
    assert terrain.model_dump_json() == raw


def test_multipart_orphan_does_not_duplicate_second_volume(frame):
    from shapely.geometry import MultiPolygon

    geometry = MultiPolygon([box(0, 0, 10, 10), box(20, 0, 30, 10)])
    scene = generate(frame, [part("way/multi", geometry, provider="osm", height=14)])
    assert len(scene.buildings) == 2
    volumes = [p for b in scene.buildings for p in b.parts]
    assert len(volumes) == 2 and len({p.id for p in volumes}) == 2
    assert sum(polygon(p.footprint).area for p in volumes) == 200
    assert all(b.render_footprints == [] for b in scene.buildings)
