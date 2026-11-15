import math

import pytest

from app.gis.road_profiles import RoadProfileSettings, resolve_profiles
from app.models.scene import Road


def road(name, path, nodes, **extra):
    return Road(
        id=name,
        path=path,
        node_ids=nodes,
        width=8,
        road_type="residential",
        layer=extra.pop("layer", 0),
        **extra,
    )


def test_plateau_and_approach_constraints_solved_together_without_dem_mutation():
    roads = [
        road("a", [(-60, 0, 0), (0, 0, 0)], ["a", "j"]),
        road("b", [(0, 0, 0), (60, 0, 0)], ["j", "b"]),
        road("c", [(0, 0, 0), (0, 60, 0)], ["j", "c"]),
    ]
    original = [r.model_dump() for r in roads]
    settings = RoadProfileSettings(junctionCrossSectionRadiusFactor=0.8)
    profiles, report = resolve_profiles(
        roads, lambda x, y: 0.08 * x + 0.06 * y, settings
    )
    assert report["constraint_converged"]
    assert len(report["junction_sections"]) == 1
    junction_heights = []
    for p in profiles:
        junction_heights.extend(
            h for xy, h in zip(p.xy, p.heights, strict=True) if math.hypot(*xy) < 6.4
        )
        assert p.metrics["conditioned"]["max_abs_grade"] < 0.1801
        assert p.metrics["conditioned"]["max_abs_curvature"] < 0.0151
        assert abs(p.heights[-1] - p.heights[0]) > 1
    assert max(junction_heights) - min(junction_heights) < 1e-8
    assert [r.model_dump() for r in roads] == original


@pytest.mark.parametrize("extra", [{"bridge": True}, {"tunnel": True}, {"layer": 1}])
def test_grade_separated_profile_not_in_ground_junction_plateau(extra):
    roads = [
        road("a", [(-60, 0, 0), (0, 0, 0)], ["a", "j"]),
        road("b", [(0, 0, 0), (0, 60, 0)], ["j", "b"], **extra),
    ]
    _, report = resolve_profiles(
        roads,
        lambda x, y: 0.05 * x,
        RoadProfileSettings(junctionCrossSectionRadiusFactor=0.8),
    )
    assert report["junction_sections"] == []
