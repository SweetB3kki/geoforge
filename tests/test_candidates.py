"""Normalization preserves evidence, missing values and geometric identity."""

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import transform

from app.fusion.normalization import clean, normalize, number, osm_reference
from app.models.candidates import CandidateBatch, ResolvedValue, WidthRule
from app.providers.base import ProviderResult, ProviderStatus


def result(frame, kind, rows, provider="overture", indices=None):
    rows = [dict(r) for r in rows]
    for row in rows:
        geometry = row.pop("geometry", box(-10, -10, 10, 10))
        row["geometry"] = transform(
            frame.inverse.transform,
            affinity.translate(geometry, frame.easting, frame.northing),
        )
    features = gpd.GeoDataFrame(rows, crs=4326)
    if indices is not None:
        features.index = pd.MultiIndex.from_tuples(indices)
    return ProviderResult(
        provider,
        "test-release",
        kind,
        ProviderStatus.SUCCESS,
        features=features,
        metadata={
            "license": "ODbL-1.0",
            "attribution_url": "https://example.test/credits",
        },
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("w123@4", "way/123"),
        ("r12", "relation/12"),
        ("n3@0", "node/3"),
        ("way/123", "way/123"),
        ("https://www.openstreetmap.org/relation/12", "relation/12"),
        ("w12suffix", None),
        ("other/12", None),
        (None, None),
    ],
)
def test_osm_id_matching_preserves_element_type(raw, expected):
    assert osm_reference(raw) == expected


@pytest.mark.parametrize(
    "raw,expected", [("10 ft", 3.048), ("2,5 m", 2.5), ("3 metres", 3), (12.2, 12.2)]
)
def test_measurement_units(raw, expected):
    assert number(raw, meters=True) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [True, "12;14", "3 yards", -2, float("inf")])
def test_invalid_measurement_is_not_estimated(raw):
    with pytest.raises((ValueError, TypeError)):
        number(raw, meters=True)


def test_nested_arrow_values_clean_to_finite_json():
    raw = {
        "a": np.array(
            [{"value": np.float64(2), "between": np.array([0, 1])}], dtype=object
        ),
        "missing": pd.NA,
        "nan": np.nan,
    }
    value = clean(raw)
    assert value == {
        "a": [{"value": 2, "between": [0, 1]}],
        "missing": None,
        "nan": None,
    }
    json.dumps(value, allow_nan=False)


def test_building_mapping_keeps_missing_height_and_record_scope(frame):
    source = {
        "dataset": "OpenStreetMap",
        "record_id": "w123@9",
        "property": "/height",
        "confidence": 0.9,
        "update_time": "2026-09-01T00:00:00Z",
        "license": "ODbL-1.0",
    }
    candidates = normalize(
        [
            result(
                frame,
                "building",
                [{"id": "b", "num_floors": 4, "sources": np.array([source])}],
            )
        ],
        frame,
    ).candidates
    c = candidates[0]
    assert c.attributes.height is None and c.attributes.floors == 4
    assert c.source_records[0].osm_id == "way/123"
    assert c.source_records[0].raw["record_id"] == "w123@9"
    assert c.source_records[0].property == "/height"
    assert c.confidence is None  # A property-specific score is not a geometry score.
    assert c.geometry.area == pytest.approx(400, abs=0.001)
    assert c.license == "ODbL-1.0"


def test_osm_units_parts_and_no_defaults(frame):
    features = result(
        frame,
        "features",
        [
            {"building": "yes", "height": "10 ft", "roof:shape": "hipped"},
            {
                "building": "yes",
                "building:part": "yes",
                "min_height": "0 m",
                "building:levels": "2",
            },
            {"highway": "residential", "geometry": LineString([(-10, 0), (10, 0)])},
        ],
        provider="osm",
        indices=[("way", 1), ("way", 2), ("way", 3)],
    )
    candidates = normalize([features], frame).candidates
    by_kind = {c.kind: c for c in candidates}
    assert by_kind["building"].attributes.height == pytest.approx(3.048)
    assert by_kind["building_part"].attributes.min_height == 0
    assert by_kind["building_part"].attributes.height is None
    road = by_kind["road"]
    assert road.attributes.explicit_width is None
    assert road.attributes.oneway is None and road.attributes.layer is None
    assert road.source_records[0].osm_id == "way/3"


def test_parts_retain_parent_and_offsets(frame):
    c = normalize(
        [
            result(
                frame,
                "building_part",
                [
                    {
                        "id": "part",
                        "building_id": "parent",
                        "height": 8,
                        "min_height": 5,
                        "min_floor": 2,
                        "roof_height": 1,
                    }
                ],
            )
        ],
        frame,
    ).candidates[0]
    assert c.kind == "building_part" and c.attributes.parent_building_id == "parent"
    assert c.attributes.height == 8 and c.attributes.min_height == 5


def test_bad_fields_warn_without_discarding_valid_footprint(frame):
    c = normalize(
        [
            result(
                frame,
                "building",
                [
                    {
                        "id": "b",
                        "height": -4,
                        "num_floors": True,
                        "roof_direction": 370,
                        "roof_shape": ["flat"],
                    }
                ],
            )
        ],
        frame,
    ).candidates[0]
    assert c.attributes.height is None and c.attributes.floors is None
    assert len(c.warnings) == 4
    assert c.raw_attributes["height"] == -4


def test_piecewise_rules_connectors_and_invalid_rules_retained_raw(frame):
    raw = {
        "id": "r",
        "geometry": LineString([(-10, 0), (10, 0)]),
        "subtype": "road",
        "width_rules": np.array(
            [
                {"value": 6, "between": np.array([0, 0.5])},
                {"value": 4, "between": np.array([0.5, 1])},
                {"value": 1, "between": np.array([0.8, 0.2])},
            ]
        ),
        "connectors": [{"connector_id": "a", "at": 0}, {"connector_id": "b", "at": 1}],
        "road_flags": [{"values": ["is_bridge"], "between": [0.2, 0.8]}],
    }
    c = normalize([result(frame, "segment", [raw])], frame).candidates[0]
    assert len(c.attributes.width_rules) == 2
    assert c.attributes.width_rules[1].between == (0.5, 1)
    assert c.attributes.connectors[1].connector_id == "b"
    assert len(c.raw_attributes["width_rules"]) == 3
    assert c.warnings == ["invalid_attribute:width_rules/2"]


def test_water_ocean_is_surface_but_physical_point_and_coastline_are_not(frame):
    overture = result(
        frame,
        "water",
        [
            {"id": "ocean", "subtype": "ocean"},
            {"id": "label", "subtype": "physical", "geometry": Point(0, 0)},
        ],
    )
    osm = result(
        frame,
        "features",
        [{"natural": "coastline", "geometry": LineString([(-100, 0), (100, 0)])}],
        "osm",
        [("way", 9)],
    )
    items = normalize([overture, osm], frame).candidates
    assert sum(c.attributes.is_surface for c in items) == 1
    assert sum(c.attributes.is_coastline for c in items) == 1


def test_geometry_outside_selection_and_highway_node_have_diagnostics(frame):
    data = result(
        frame,
        "features",
        [
            {"highway": "crossing", "geometry": Point(0, 0)},
            {"building": "yes", "geometry": box(600, 600, 620, 620)},
        ],
        "osm",
        [("node", 1), ("way", 2)],
    )
    batch = normalize([data], frame)
    assert not batch.candidates
    assert {d["reason"] for d in batch.diagnostics} == {
        "unsupported_geometry",
        "outside_selection",
    }


def test_invalid_polygon_is_preserved_for_resolver_not_silently_repaired(frame):
    polygon = Polygon([(0, 0), (20, 20), (0, 20), (20, 0), (0, 0)])
    c = normalize(
        [result(frame, "building", [{"id": "b", "geometry": polygon}])], frame
    ).candidates[0]
    assert (
        not c.geometry.is_valid and "invalid_geometry_requires_resolution" in c.warnings
    )


def test_roundtrip_and_input_order_determinism(frame):
    data = result(
        frame, "building", [{"id": "b", "height": 4}, {"id": "a", "height": 7}]
    )
    first = normalize([data], frame)
    data.features = data.features.iloc[::-1]
    second = normalize([data], frame)
    assert first.model_dump_json() == second.model_dump_json()
    restored = CandidateBatch.model_validate_json(first.model_dump_json())
    assert restored.candidates[0].geometry.equals(first.candidates[0].geometry)


def test_missing_provider_id_does_not_invent_identity(frame):
    batch = normalize([result(frame, "building", [{"id": None}])], frame)
    assert (
        not batch.candidates and batch.diagnostics[0]["reason"] == "invalid_candidate"
    )


def test_duplicate_ids_reject_both_candidates_instead_of_order_dependent_choice(frame):
    data = result(
        frame, "building", [{"id": "same", "height": 4}, {"id": "same", "height": 9}]
    )
    a = normalize([data], frame)
    data.features = data.features.iloc[::-1]
    b = normalize([data], frame)
    assert not a.candidates and a.model_dump_json() == b.model_dump_json()
    assert "Duplicate" in a.diagnostics[0]["detail"]


def test_nullable_water_column_does_not_turn_parks_into_water(frame):
    data = result(
        frame,
        "features",
        [
            {"water": None, "leisure": "park"},
            {"water": "pond", "natural": "water"},
            {
                "water": None,
                "highway": "footway",
                "tunnel": "building_passage",
                "geometry": LineString([(-10, 0), (10, 0)]),
            },
        ],
        "osm",
        [("way", 1), ("way", 2), ("way", 3)],
    )
    batch = normalize([data], frame)
    assert sum(c.kind == "water" for c in batch.candidates) == 1
    assert next(c for c in batch.candidates if c.kind == "road").attributes.tunnel
    assert any(
        d["id"] == "way/1" and d["reason"] == "unsupported_domain"
        for d in batch.diagnostics
    )


def test_wrong_crs_rejected(frame):
    data = result(frame, "building", [{"id": "a"}])
    data.features = data.features.to_crs(3857)
    with pytest.raises(ValueError, match="WGS84"):
        normalize([data], frame)


def test_resolved_value_is_explicit_about_estimation():
    value = ResolvedValue(
        value=9, source="fallback", method="generic_height", estimated=True
    )
    assert value.model_dump()["estimated"]
    with pytest.raises(ValidationError):
        ResolvedValue(value=9, source="osm", method="explicit", confidence=1.2)
    with pytest.raises(ValidationError):
        WidthRule(value=4, between=(1, 0))
