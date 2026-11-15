import pytest

from app.fusion.crossings import deduplicate_crossings
from app.models.scene import Road


def crossing(identifier, **kwargs):
    return Road(
        id=identifier,
        path=[(0, 0, 0), (10, 0, 0)],
        node_ids=["a", "b"],
        road_type="footway",
        road_category="pedestrian",
        road_subtype="crossing",
        width=2,
        sources=[identifier],
        source_osm_ids=[identifier],
        **kwargs,
    )


def test_duplicate_crossing_keeps_provenance_and_does_not_mutate_input():
    a, b = crossing("a"), crossing("b")
    original = a.model_dump()
    merged = deduplicate_crossings([b, a])
    assert len(merged) == 1 and merged[0].id == "a"
    assert merged[0].sources == ["a", "b"]
    assert merged[0].source_osm_ids == ["a", "b"]
    assert merged[0].field_provenance["crossing_duplicate_resolution"][0]["id"] == "b"
    assert a.model_dump() == original


@pytest.mark.parametrize(
    "change",
    [dict(layer=1), dict(bridge=True), dict(tunnel=True), dict(name="different")],
)
def test_separated_or_semantically_different_crossing_is_not_deduplicated(change):
    assert len(deduplicate_crossings([crossing("a"), crossing("b", **change)])) == 2


def test_same_xy_with_different_nodes_is_not_a_proven_duplicate():
    a, b = crossing("a"), crossing("b")
    b.node_ids = ["other-a", "other-b"]
    assert len(deduplicate_crossings([a, b])) == 2


def test_duplicate_identifier_cannot_silently_remove_both_records():
    with pytest.raises(ValueError, match="Duplicate crossing ID"):
        deduplicate_crossings([crossing("a"), crossing("a")])
