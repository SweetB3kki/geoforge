import math
from dataclasses import asdict

import numpy as np
import pytest

from app.gis.road_profiles import (
    RoadGenerationStrategy,
    RoadProfileSettings,
    resolve_profiles,
)
from app.models.scene import Road


def road(identifier="r", points=None, nodes=None, **kwargs):
    return Road(
        id=identifier,
        path=points or [(0, 0, 0), (100, 0, 0)],
        node_ids=nodes or ["start", "end"],
        width=6,
        road_type="residential",
        **kwargs,
    )


def test_linear_incline_is_preserved_including_endpoints():
    source = road()
    before = source.model_dump()
    profiles, audit = resolve_profiles([source], lambda x, y: 10 + 0.1 * x)
    p = profiles[0]
    assert p.heights == pytest.approx(p.raw_heights, abs=1e-10)
    assert p.heights[-1] - p.heights[0] == pytest.approx(10)
    assert audit["constraint_converged"]
    assert source.model_dump() == before


def test_single_dsm_spike_is_rejected_without_flattening_regional_slope():
    profiles, audit = resolve_profiles(
        [road()], lambda x, y: 0.05 * x + (15 if abs(x - 50) < 0.1 else 0)
    )
    p = profiles[0]
    assert p.metrics["rejected_spikes"] == 1
    assert (
        max(abs(h - 0.05 * d) for h, d in zip(p.heights, p.distances, strict=True))
        < 0.3
    )
    assert p.metrics["conditioned"]["max_abs_grade"] < 0.1
    assert audit["constraint_converged"]


def test_joint_network_constraints_keep_exact_shared_junction_height():
    roads = [
        road("a", [(0, 0, 0), (50, 0, 0)], ["a0", "junction"]),
        road("b", [(50, 0, 0), (100, 0, 0)], ["junction", "b1"]),
        road("c", [(50, 0, 0), (50, 50, 0)], ["junction", "c1"]),
    ]
    profiles, audit = resolve_profiles(
        roads, lambda x, y: 0.1 * x + 0.15 * math.sin(x / 8) + 0.05 * y
    )
    a, b, c = profiles
    assert a.heights[-1] == b.heights[0] == c.heights[0]
    assert audit["shared_automotive_nodes"] == 1
    assert audit["constraint_converged"]


def test_interior_topology_node_is_sampled_and_shared():
    a = road("a", [(0, 0, 0), (37, 0, 0), (100, 0, 0)], ["a0", "j", "a1"])
    b = road("b", [(37, 0, 0), (37, 40, 0)], ["j", "b1"])
    profiles, audit = resolve_profiles([a, b], lambda x, y: 0.1 * x + 0.07 * y)
    p = profiles[0]
    index = next(i for i, node in p.sample_node_ids.items() if node == "j")
    assert p.distances[index] == 37
    assert p.heights[index] == profiles[1].heights[0]
    assert audit["shared_automotive_nodes"] == 1


def test_layer_separation_and_unknown_layer_do_not_share_nodes():
    roads = [road("a", layer=0), road("b", layer=1), road("c", layer=None)]
    _, audit = resolve_profiles(roads, lambda x, y: 0)
    assert audit["shared_automotive_nodes"] == 0


def test_steep_terrain_is_grade_and_curvature_conditioned():
    settings = RoadProfileSettings(maximumConstraintIterations=2000)
    profiles, audit = resolve_profiles(
        [road(points=[(0, 0, 0), (20, 0, 0)])], lambda x, y: 0.8 * x, settings
    )
    p = profiles[0]
    assert audit["constraint_converged"]
    assert p.metrics["conditioned"]["max_abs_grade"] <= settings.maxRoadGrade + 0.0001
    assert (
        p.metrics["conditioned"]["max_abs_curvature"]
        <= settings.maxVerticalCurvature + 0.0001
    )
    assert p.heights[-1] > p.heights[0]
    assert p.metrics["max_abs_terrain_deviation"] > 1


def test_bridge_is_linear_above_sampled_terrain_and_explicitly_approximate():
    bridge = road(bridge=True, layer=2)
    profiles, _ = resolve_profiles(
        [bridge], lambda x, y: 8 * math.exp(-(((x - 50) / 10) ** 2))
    )
    p = profiles[0]
    assert p.strategy == RoadGenerationStrategy.AUTOMOTIVE_BRIDGE
    assert p.bridge_height_method == "linear_sampled_clearance_envelope"
    assert min(np.array(p.heights) - p.raw_heights) >= 6 - 1e-9
    assert p.metrics["conditioned"]["max_abs_curvature"] < 1e-10
    assert "bridge_approaches_and_cross_section_unverified" in p.warnings


def test_tunnel_surface_hidden_in_profile_policy_only():
    source = road(tunnel=True)
    profiles, _ = resolve_profiles([source], lambda x, y: 10)
    p = profiles[0]
    assert not p.surface_visible and p.heights == pytest.approx([7] * len(p.heights))
    assert source.tunnel  # No scene geometry or semantics mutated.


@pytest.mark.parametrize("category", ["pedestrian", "cycle", "steps", "track", "other"])
def test_distinct_nonautomotive_policies(category):
    profiles, _ = resolve_profiles([road(road_category=category)], lambda x, y: 0.3 * x)
    p = profiles[0]
    assert p.strategy.value == category.upper()
    assert p.max_grade > RoadProfileSettings().maxRoadGrade
    assert p.max_curvature > RoadProfileSettings().maxVerticalCurvature


def test_road_order_does_not_change_result():
    a, b = road("a"), road("b", [(100, 0, 0), (120, 0, 0)], ["end", "b1"])
    first, report1 = resolve_profiles([a, b], lambda x, y: 0.1 * x)
    second, report2 = resolve_profiles([b, a], lambda x, y: 0.1 * x)
    assert [asdict(p) for p in first] == [asdict(p) for p in second]
    assert report1 == report2


def test_iteration_exhaustion_is_not_reported_as_success():
    profiles, report = resolve_profiles(
        [road()], lambda x, y: x, RoadProfileSettings(maximumConstraintIterations=1)
    )
    assert not report["constraint_converged"]
    assert "network_constraint_iteration_limit" in profiles[0].warnings


def test_invalid_input_and_budget_fail_explicitly():
    with pytest.raises(ValueError, match="finite"):
        RoadProfileSettings(maxRoadGrade=float("nan"))
    with pytest.raises(ValueError, match="integer"):
        RoadProfileSettings(maximumConstraintIterations=1.5)
    with pytest.raises(ValueError, match="Nonfinite"):
        resolve_profiles([road()], lambda x, y: float("nan"))
    with pytest.raises(ValueError, match="budget"):
        resolve_profiles(
            [road()], lambda x, y: 0, RoadProfileSettings(maximumSamplesPerRoad=3)
        )
    with pytest.raises(ValueError, match="Zero-length"):
        resolve_profiles([road(points=[(0, 0, 0), (0, 0, 1)])], lambda x, y: 0)
    with pytest.raises(ValueError, match="Duplicate"):
        resolve_profiles([road(), road()], lambda x, y: 0)


def test_sampling_does_not_add_tiny_edges_near_original_vertices():
    # A whole-road 5 m grid would place a station only 1 cm from the middle node.
    source = road(points=[(0, 0, 0), (49.99, 0, 0), (100, 0, 0)], nodes=["a", "b", "c"])
    profiles, _ = resolve_profiles([source], lambda x, y: 0.05 * x)
    assert min(np.diff(profiles[0].distances)) > 4
    assert 49.99 in profiles[0].distances


def test_nonautomotive_structures_retain_category_and_structure_policy():
    profiles, audit = resolve_profiles(
        [
            road("bridge", road_category="pedestrian", bridge=True),
            road("tunnel", road_category="cycle", tunnel=True),
        ],
        lambda x, y: 10,
    )
    bridge, tunnel = profiles
    assert bridge.strategy == RoadGenerationStrategy.PEDESTRIAN
    assert bridge.bridge_height_method and min(bridge.heights) == 13
    assert (
        tunnel.strategy == RoadGenerationStrategy.CYCLE and not tunnel.surface_visible
    )
    assert audit["bridge_profiles"] == audit["hidden_tunnel_profiles"] == 1


def test_empty_network_is_supported():
    profiles, audit = resolve_profiles([], lambda x, y: 0)
    assert profiles == [] and audit["constraint_converged"]


def test_profile_export_contract_rejects_mismatched_or_zero_length_samples():
    from app.models.scene import RoadVerticalProfile

    with pytest.raises(ValueError, match="sample lengths"):
        RoadVerticalProfile(
            points=[(0, 0, 0), (1, 0, 0)], raw_heights=[0], strategy="OTHER"
        )
    with pytest.raises(ValueError, match="Zero-length"):
        RoadVerticalProfile(
            points=[(0, 0, 0), (0, 0, 1)], raw_heights=[0, 1], strategy="OTHER"
        )


def test_explicit_profile_export_preserves_raw_scene_and_legacy_road_fields(frame):
    import geopandas as gpd

    from app.fusion.road_profiles import apply_road_profiles
    from app.gis.processing import build_scene
    from app.models.scene import TerrainData, WorldScene

    scene = build_scene(gpd.GeoDataFrame(geometry=[], crs=4326), frame)
    scene.roads = [road()]
    assert apply_road_profiles(scene)["reason"] == "no_dem"
    assert scene.roads[0].vertical_profile is None
    scene.terrain = TerrainData(
        resolution_x=3,
        resolution_y=3,
        origin=(scene.bounds.min_x, scene.bounds.min_y, 0),
        cell_size=(
            (scene.bounds.max_x - scene.bounds.min_x) / 2,
            (scene.bounds.max_y - scene.bounds.min_y) / 2,
        ),
        heights=[0] * 9,
        valid_mask=[True] * 9,
        min_height=0,
        max_height=0,
        height_offset_m=0,
        source="fixture",
        attribution="fixture",
    )
    before = scene.model_dump()
    report = apply_road_profiles(scene)
    assert report["applied"] and scene.roads[0].vertical_profile is not None
    assert scene.terrain.model_dump() == before["terrain"]
    for key in ("path", "node_ids", "width", "road_category", "source_tags"):
        assert scene.roads[0].model_dump()[key] == before["roads"][0][key]
    assert WorldScene.model_validate_json(scene.model_dump_json()) == scene
