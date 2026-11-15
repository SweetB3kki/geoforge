import pytest

from app.gis.road_profiles import RoadProfileSettings, resolve_profiles
from app.models.scene import Road


def road(name, path, **extra):
    return Road(
        id=name,
        path=path,
        node_ids=[name + "0", name + "1"],
        width=6,
        road_type="residential",
        layer=extra.pop("layer", 0),
        **extra,
    )


def test_bridge_abutment_ramp_has_no_step_and_matches_deck_grade():
    roads = [
        road("a", [(-100, 0, 0), (0, 0, 0)]),
        road("b", [(0, 0, 0), (50, 0, 0)], bridge=True, layer=1),
        road("c", [(50, 0, 0), (150, 0, 0)]),
    ]
    before = [r.model_dump() for r in roads]
    profiles, audit = resolve_profiles(
        roads,
        lambda x, y: 0,
        RoadProfileSettings(
            bridgeApproachContinuity=True, maximumConstraintIterations=16000
        ),
    )
    a, b, c = profiles
    assert audit["constraint_converged"]
    assert len(audit["bridge_approach_connections"]) == 2
    assert a.heights[-1] == pytest.approx(b.heights[0], abs=1e-8)
    assert c.heights[0] == pytest.approx(b.heights[-1], abs=1e-8)
    assert a.heights[-2] == a.heights[-1]
    assert c.heights[0] == c.heights[1]
    assert min(b.heights) >= 3
    assert abs(a.heights[0]) < 1
    assert [r.model_dump() for r in roads] == before


def test_underpassing_ground_and_tunnel_not_pulled_to_deck():
    roads = [
        road("bridge", [(0, 0, 0), (50, 0, 0)], bridge=True, layer=1),
        road("under", [(25, -30, 0), (25, 30, 0)]),
        road("tunnel", [(-100, 0, 0), (0, 0, 0)], tunnel=True),
    ]
    profiles, audit = resolve_profiles(
        roads, lambda x, y: 0, RoadProfileSettings(bridgeApproachContinuity=True)
    )
    assert audit["bridge_approach_connections"] == []
    under = next(p for p in profiles if p.road_id == "under")
    assert under.heights == pytest.approx([0] * len(under.heights))
