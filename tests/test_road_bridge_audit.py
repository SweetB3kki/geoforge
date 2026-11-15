from types import SimpleNamespace

import pytest

from app.models.scene import Road, RoadVerticalProfile
from app.validation.road_bridge_audit import audit, endpoint_candidates


def road(identifier, points, height, **kwargs):
    bridge = kwargs.get("bridge", False)
    return Road(
        id=identifier,
        path=[(*p, 0) for p in points],
        width=4,
        road_type="residential",
        **kwargs,
        vertical_profile=RoadVerticalProfile(
            points=[(*p, height) for p in points],
            raw_heights=[0] * len(points),
            strategy="AUTOMOTIVE_BRIDGE" if bridge else "AUTOMOTIVE_GROUND",
        ),
    )


def scene(roads, terrain=None, water=None):
    return SimpleNamespace(roads=roads, terrain=terrain, water_areas=water or [])


def test_bridge_candidates_cross_layer_without_mutating_topology():
    b = road(
        "bridge",
        [(0, 0), (10, 0)],
        6,
        bridge=True,
        layer=2,
        node_ids=["bridge-start", "bridge-end"],
    )
    g = road("ground", [(-10, 0), (0, 0)], 1, node_ids=["ground-start", "ground-end"])
    before = [r.model_dump() for r in [b, g]]
    result = audit(scene([b, g]))
    assert result["summary"]["candidate_pairs"] == 1
    assert result["summary"]["max_abs_candidate_gap_m"] == 5
    assert result["summary"]["endpoints_without_candidate"] == 1
    assert [r.model_dump() for r in [b, g]] == before


def test_no_snap_to_nearby_carriageway_or_interior_bridge_crossing():
    b = road("bridge", [(0, 0), (10, 0)], 3, bridge=True)
    near = road("near", [(-10, 0.001), (0, 0.001)], 0)
    crossing = road("crossing", [(5, -5), (5, 0), (5, 5)], 0)
    tunnel = road("tunnel", [(-10, 0), (0, 0)], 0, tunnel=True)
    cycle = road("cycle", [(-10, 0), (0, 0)], 0, road_category="cycle")
    assert all(
        not e["candidates"]
        for e in endpoint_candidates([b, near, crossing, tunnel, cycle])
    )


def test_missing_profile_sample_is_not_filled_from_nearest_neighbor():
    b = road("bridge", [(0, 0), (10, 0)], 3, bridge=True)
    g = road("ground", [(-10, 0), (0, 0)], 0)
    g.vertical_profile.points[-1] = (-0.1, 0, 0)
    result = audit(scene([b, g]))
    assert result["summary"]["candidate_pairs"] == 1
    assert result["summary"]["measured_candidate_pairs"] == 0
    assert result["summary"]["max_abs_candidate_gap_m"] is None


def test_cross_section_detects_side_penetration_and_water_height():
    # Centreline y=0 is clear; the lateral y=2 edge intersects terrain at height 4.
    terrain = SimpleNamespace(
        resolution_x=3,
        resolution_y=3,
        origin=(-10, -10, 0),
        cell_size=(10, 10),
        heights=[-20] * 3 + [0] * 3 + [20] * 3,
        valid_mask=[True] * 9,
    )
    water = SimpleNamespace(
        polygon=SimpleNamespace(
            exterior=[(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)], holes=[]
        ),
        water_level_m=5,
    )
    result = audit(
        scene([road("b", [(0, 0), (5, 0)], 3, bridge=True)], terrain, [water])
    )
    cross = result["cross_sections"][0]
    assert cross["min_profile_above_terrain_m"] == pytest.approx(-1)
    assert cross["min_profile_above_water_m"] == -2
    assert result["summary"]["bridges_with_terrain_penetration"] == 1
    assert result["summary"]["bridges_with_water_penetration"] == 1


def test_unknown_terrain_and_water_are_not_zero_clearance():
    water = SimpleNamespace(
        polygon=SimpleNamespace(
            exterior=[(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)], holes=[]
        ),
        water_level_m=None,
    )
    cross = audit(scene([road("b", [(0, 0), (5, 0)], 3, bridge=True)], water=[water]))[
        "cross_sections"
    ][0]
    assert cross["missing_terrain_samples"] == cross["samples"]
    assert cross["water_samples_without_level"] == cross["samples"]
    assert cross["min_profile_above_terrain_m"] is None
    assert cross["min_profile_above_water_m"] is None
