import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from app.fusion.transportation import TransportSettings, enrich_transport
from app.gis.processing import build_scene
from app.gis.roads import build_network
from app.models.candidates import (
    CandidateBatch,
    ConnectorCandidate,
    ConnectorReference,
    RoadAttributes,
    RoadCandidate,
    SourceRecord,
    WidthRule,
)
from app.models.scene import Road, WorldScene
from app.validation.scene_validator import validate_scene


def road(width=None, lanes=None):
    tags = {"highway": "residential"}
    if width:
        tags["width"] = str(width)
    if lanes:
        tags["lanes"] = str(lanes)
    return Road(
        id="way/1/road/0",
        path=[(0, 0, 0), (100, 0, 0)],
        road_type="residential",
        width=6,
        source_tags=tags,
    )


def segment(identifier="s", coords=None, osm_id="way/1", rules=None, **attrs):
    return RoadCandidate(
        candidate_id="overture:segment:" + identifier,
        provider="overture",
        provider_feature_id=identifier,
        geometry=LineString(coords or [(0, 0), (100, 0)]),
        source_records=(
            [SourceRecord(dataset="OpenStreetMap", osm_id=osm_id)] if osm_id else []
        ),
        attributes=RoadAttributes(
            subtype="road", road_class="residential", width_rules=rules or [], **attrs
        ),
    )


def run(frame, roads, candidates, settings=None):
    scene = build_scene(gpd.GeoDataFrame(geometry=[], crs=4326), frame)
    scene.roads, scene.metadata.road_statistics = build_network(roads)
    scene.fusion_audit = {"applied_domains": [], "pending_domains": []}
    batch = CandidateBatch(
        crs=frame.crs.to_string(),
        origin_easting=frame.easting,
        origin_northing=frame.northing,
        candidates=candidates,
    )
    result = enrich_transport(scene, batch, frame.boundary, settings)
    assert WorldScene.model_validate_json(scene.model_dump_json()) == scene
    assert validate_scene(scene.model_dump(mode="json"))["valid"]
    return scene, result


@pytest.mark.parametrize(
    "osm_width,lanes,expected,source",
    [
        (5, 2, 5, "osm_width"),
        (None, 2, 8, "overture_width_rule"),
        (None, None, 8, "overture_width_rule"),
    ],
)
def test_width_priority_and_topology(frame, osm_width, lanes, expected, source):
    original = road(osm_width, lanes)
    scene, result = run(frame, [original], [segment(rules=[WidthRule(value=8)])])
    r = scene.roads[0]
    baseline = build_network([original])[0][0]
    assert r.width == expected and r.width_source == source
    assert (r.path, r.node_ids, r.source_tags, r.road_category) == (
        baseline.path,
        baseline.node_ids,
        baseline.source_tags,
        baseline.road_category,
    )
    assert (
        result["matched_roads"] == 1
        and r.transportation_matches[0]["method"] == "provenance"
    )


def test_piecewise_rules_preserved_and_warning(frame):
    scene, result = run(
        frame,
        [road()],
        [
            segment(
                rules=[
                    WidthRule(value=4, between=(0, 0.7)),
                    WidthRule(value=10, between=(0.7, 1)),
                ]
            )
        ],
    )
    assert scene.roads[0].width == 4
    assert len(scene.roads[0].width_rules) == 2
    assert any(
        w["reason"] == "piecewise_width_representative" for w in result["warnings"]
    )


def test_partial_rule_not_spread_over_whole_road(frame):
    scene, result = run(
        frame, [road()], [segment(rules=[WidthRule(value=1, between=(0, 0.1))])]
    )
    assert scene.roads[0].width == 6 and scene.roads[0].width_source == "fallback"
    assert any(
        w["reason"] == "partial_width_coverage_not_applied" for w in result["warnings"]
    )


def test_reverse_direction_matches_and_ambiguous_parallel_does_not(frame):
    scene, result = run(
        frame,
        [road()],
        [segment(coords=[(100, 0), (0, 0)], osm_id=None, rules=[WidthRule(value=8)])],
    )
    assert scene.roads[0].width == 8 and result["matched_roads"] == 1
    scene, result = run(
        frame,
        [road()],
        [
            segment("a", [(0, 1), (100, 1)], None),
            segment("b", [(0, -1), (100, -1)], None),
        ],
    )
    assert result["matched_roads"] == 0
    assert any(w["reason"] == "ambiguous_transport_match" for w in result["warnings"])


def test_perpendicular_line_not_a_match_and_no_duplicate(frame):
    scene, result = run(
        frame, [road()], [segment(coords=[(50, -50), (50, 50)], osm_id=None)]
    )
    assert result["matched_roads"] == 0 and len(scene.roads) == 1


def test_supplement_auto_and_off(frame):
    extra = segment("new", [(0, 30), (100, 30)], None, rules=[WidthRule(value=7)])
    scene, result = run(frame, [road()], [extra])
    assert result["supplemental_roads"] == 1
    added = scene.roads[-1]
    assert added.source == "Overture" and added.width == 7 and added.source_tags == {}
    assert added.node_ids and added.field_provenance["geometry"]["source"] == "overture"
    scene, result = run(
        frame,
        [road()],
        [extra],
        TransportSettings(enableSupplementalOvertureRoads="off"),
    )
    assert len(scene.roads) == 1


def test_stale_provenance_not_duplicated_as_supplement(frame):
    scene, result = run(frame, [road()], [segment(coords=[(0, 40), (100, 40)])])
    assert len(scene.roads) == 1 and result["matched_roads"] == 0


def test_connector_missing_and_position_mismatch_are_reported(frame):
    refs = [
        ConnectorReference(connector_id="missing", at=0),
        ConnectorReference(connector_id="bad", at=1),
    ]
    connector = ConnectorCandidate(
        candidate_id="overture:connector:bad",
        provider="overture",
        provider_feature_id="bad",
        geometry=Point(0, 20),
    )
    _, result = run(frame, [road()], [segment(connectors=refs), connector])
    assert result["connectors"] == {"missing": 1, "position_mismatch": 1}


def test_invalid_settings():
    with pytest.raises(ValueError):
        TransportSettings(proximity_m=float("nan"))
    with pytest.raises(ValueError):
        TransportSettings(overlap_ratio=1.1)
    with pytest.raises(ValueError):
        TransportSettings(enableSupplementalOvertureRoads="yes")


def test_spatial_matching_respects_road_category(frame):
    candidate = segment(osm_id=None, rules=[WidthRule(value=2)])
    candidate.attributes.road_class = "footway"
    scene, result = run(frame, [road()], [candidate])
    assert result["matched_roads"] == 0 and scene.roads[0].width == 6


def test_disjoint_source_segments_enrich_one_logical_road(frame):
    a = segment("a", [(0, 0), (50, 0)], rules=[WidthRule(value=8)])
    b = segment("b", [(50, 0), (100, 0)], rules=[WidthRule(value=8)])
    scene, result = run(frame, [road()], [b, a])
    assert result["matched_segments"] == 2 and scene.roads[0].width == 8
    assert len(scene.roads[0].transportation_matches) == 2


def test_shuffled_segments_have_deterministic_enrichment(frame):
    a = segment("a", [(0, 0), (50, 0)], rules=[WidthRule(value=8)])
    b = segment("b", [(50, 0), (100, 0)], rules=[WidthRule(value=8)])
    first, report1 = run(frame, [road()], [a, b])
    second, report2 = run(frame, [road()], [b, a])
    assert first.roads == second.roads and report1 == report2


def test_rail_and_structured_supplement_not_blindly_added(frame):
    rail = segment("rail", [(0, 30), (100, 30)], None)
    rail.attributes.subtype = "rail"
    bridge = segment(
        "bridge", [(0, 60), (100, 60)], None, road_flags=[{"values": ["is_bridge"]}]
    )
    scene, report = run(frame, [road()], [rail, bridge])
    assert len(scene.roads) == 1 and report["supplemental_roads"] == 0
