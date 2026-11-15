"""Resolution priorities, ambiguity, supplemental dedup and ocean coverage."""

import pytest
from shapely.geometry import Polygon, box

from app.fusion.resolvers import FusionResult, FusionSettings, resolve
from app.models.candidates import (
    BuildingAttributes,
    BuildingCandidate,
    BuildingPartCandidate,
    CandidateBatch,
    SourceRecord,
    WaterAttributes,
    WaterCandidate,
)


def building(identifier, provider="osm", geometry=None, osm_id=None, **attrs):
    return BuildingCandidate(
        candidate_id=f"{provider}:building:{identifier}",
        provider=provider,
        provider_feature_id=identifier,
        geometry=geometry if geometry is not None else box(0, 0, 10, 10),
        attributes=BuildingAttributes(**attrs),
        source_records=(
            [SourceRecord(dataset="OpenStreetMap", osm_id=osm_id)] if osm_id else []
        ),
    )


def water(identifier, provider, geometry, water_type):
    return WaterCandidate(
        candidate_id=f"{provider}:water:{identifier}",
        provider=provider,
        provider_feature_id=identifier,
        geometry=geometry,
        attributes=WaterAttributes(water_type=water_type, is_surface=True),
    )


def run(candidates, **settings):
    batch = CandidateBatch(
        crs="EPSG:32636", origin_easting=0, origin_northing=0, candidates=candidates
    )
    return resolve(batch, box(-100, -100, 100, 100), FusionSettings(**settings))


def test_explicit_osm_values_win_and_conflicts_preserve_both():
    result = run(
        [
            building("a", osm_id="way/1", height=12, floors=4, roof_shape="flat"),
            building(
                "b",
                "overture",
                osm_id="way/1",
                height=20,
                floors=6,
                facade_color="#abc",
            ),
        ]
    )
    b = result.buildings[0]
    assert len(result.buildings) == 1 and b.attributes.height == 12
    assert b.attributes.facade_color == "#abc"
    assert b.field_provenance["facade_color"].source == "overture"
    assert (
        result.conflicts[0].kept.value == 12
        and result.conflicts[0].alternative.value == 20
    )
    assert b.geometry.equals(box(0, 0, 10, 10))


def test_missing_osm_height_uses_overture_height_before_floor_estimate():
    result = run([building("a", floors=3), building("b", "overture", height=11)])
    b = result.buildings[0]
    assert b.attributes.height == 11 and b.attributes.floors == 3
    assert not b.field_provenance["height"].estimated
    assert result.metrics["overtureEnrichedHeights"] == 1


def test_floors_then_generic_fallback_are_marked_estimated():
    result = run([building("a", floors=5), building("b", geometry=box(20, 0, 30, 10))])
    assert [b.attributes.height for b in result.buildings] == [15, 9]
    assert all(b.field_provenance["height"].estimated for b in result.buildings)
    assert result.metrics["fallbackHeights"] == 1


def test_ambiguous_spatial_match_never_silently_merges():
    result = run(
        [
            building("a"),
            building("b", "overture", height=11),
            building("c", "overture", height=19),
        ]
    )
    assert result.metrics["matchedBuildings"] == 0
    assert result.buildings[0].attributes.height == 9
    assert len(result.buildings) == 1
    assert any(w["reason"] == "ambiguous_spatial_match" for w in result.warnings)


def test_many_to_one_match_is_ambiguous():
    result = run(
        [
            building("a", osm_id="way/1"),
            building("b", osm_id="way/1"),
            building("c", "overture", osm_id="way/1", height=18),
        ]
    )
    assert result.metrics["matchedBuildings"] == 0
    assert any(w["reason"] == "ambiguous_many_to_one" for w in result.warnings)


def test_valid_osm_footprint_not_replaced_by_overture():
    original = box(0, 0, 10, 10)
    result = run(
        [
            building("a", geometry=original, osm_id="way/1"),
            building("b", "overture", geometry=box(-1, -1, 11, 11), osm_id="way/1"),
        ]
    )
    assert result.buildings[0].geometry.equals(original)
    assert result.buildings[0].field_provenance["geometry"].source == "osm"


def test_supplemental_dedup_rejects_covering_and_near_duplicate_footprints():
    result = run(
        [
            building("a"),
            building("b", "overture", geometry=box(-20, -20, 30, 30)),
            building("c", "overture", geometry=box(40, 0, 50, 10), height=8),
            building("d", "overture", geometry=box(40, 0, 50, 10), height=8),
        ]
    )
    assert result.metrics["overtureSupplementalBuildings"] == 1
    assert len(result.buildings) == 2


def test_parts_attach_via_matched_parent_without_becoming_parent_buildings():
    part = BuildingPartCandidate(
        candidate_id="overture:building_part:p",
        provider="overture",
        provider_feature_id="p",
        geometry=box(0, 0, 5, 5),
        attributes=BuildingAttributes(parent_building_id="b", height=10, min_height=2),
    )
    result = run([building("a"), building("b", "overture"), part])
    assert len(result.buildings) == 1 and result.buildings[0].parts == [part]
    assert result.metrics["attachedBuildingParts"] == 1


def test_ocean_surface_is_clipped_and_not_duplicated():
    result = run(
        [
            water("sea", "overture", box(90, 0, 120, 20), "ocean"),
            water("same", "overture", box(90, 0, 120, 20), "ocean"),
        ]
    )
    assert len(result.water) == 1
    assert result.water[0].geometry.area == 200
    assert result.water[0].fusion_method == "overture_ocean"


def test_osm_inland_preserved_and_overture_only_fills_uncovered_area():
    original = box(0, 0, 10, 10)
    result = run(
        [
            water("osm", "osm", original, "lake"),
            water("ov", "overture", box(0, 0, 20, 10), "lake"),
        ]
    )
    assert result.water[0].geometry.equals(original)
    assert result.water[0].geometry.intersection(result.water[1].geometry).area == 0
    assert result.metrics["waterAreaM2"] == 200
    assert result.water[1].fusion_method == "overture_fallback"


def test_fusion_roundtrip_keeps_field_provenance():
    result = run([building("a", height=10)])
    restored = FusionResult.model_validate_json(result.model_dump_json())
    assert restored.buildings[0].field_provenance["height"].source == "osm"
    assert restored.buildings[0].geometry.equals(result.buildings[0].geometry)


def test_invalid_osm_footprint_uses_matched_valid_overture_and_records_choice():
    invalid = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
    result = run(
        [
            building("a", geometry=invalid, osm_id="way/1", height=12),
            building("b", "overture", osm_id="way/1", height=19),
        ]
    )
    b = result.buildings[0]
    assert b.geometry.is_valid and b.field_provenance["geometry"].source == "overture"
    assert b.attributes.height == 12
    assert "invalid_osm_geometry_replaced_by_matched_overture" in b.warnings


def test_water_holes_are_not_filled_by_duplicate_outer_ring():
    island = box(3, 3, 7, 7)
    lake = box(0, 0, 10, 10).difference(island)
    result = run(
        [water("lake", "osm", lake, "lake"), water("copy", "overture", lake, "lake")]
    )
    assert len(result.water) == 1
    assert result.water[0].geometry.intersection(island).area == 0


def test_thresholds_validated():
    with pytest.raises(ValueError):
        FusionSettings(building_iou=1.5)


def test_same_water_source_preserves_osm_island_despite_coarser_overture_geometry():
    lake = water("lake", "osm", box(0, 0, 10, 10).difference(box(3, 3, 7, 7)), "lake")
    other = water("copy", "overture", box(0, 0, 10, 10), "water")
    for candidate in (lake, other):
        candidate.source_records = [
            SourceRecord(dataset="OpenStreetMap", osm_id="way/8")
        ]
    result = run([lake, other])
    assert len(result.water) == 1 and result.water[0].geometry.area == 84
    assert result.warnings[0]["reason"] == "duplicate_water_source_preserve_osm"


def test_small_valid_osm_building_is_preserved_but_small_supplement_is_filtered():
    result = run(
        [
            building("a", geometry=box(0, 0, 0.5, 0.5)),
            building("b", "overture", geometry=box(20, 0, 20.5, 0.5)),
        ]
    )
    assert len(result.buildings) == 1 and result.buildings[0].provider == "osm"


def test_fusion_deterministic_when_candidates_are_reordered():
    candidates = [
        building("a"),
        building("b", "overture", height=10),
        building("c", "overture", geometry=box(20, 0, 30, 10)),
    ]
    assert (
        run(candidates).model_dump_json()
        == run(list(reversed(candidates))).model_dump_json()
    )


def test_uncorroborated_waterborne_ml_is_reviewed_without_editing_water():
    from app.models.candidates import SourceRecord

    lake = water("w", "osm", box(-5, -5, 15, 15), "water")
    candidate = building("ml", "overture")
    candidate.source_records = [SourceRecord(dataset="Microsoft ML Buildings")]
    result = run([candidate, lake])
    assert not result.buildings
    assert result.water[0].geometry.equals(lake.geometry)
    assert any(
        w["reason"] == "unconfirmed_ml_building_in_water" for w in result.warnings
    )
    candidate.attributes.building_type = "boathouse"
    assert len(run([candidate, lake]).buildings) == 1
    candidate.attributes.building_type = None
    assert (
        len(
            run(
                [candidate, water("shore", "osm", box(-1, -1, 1, 1), "water")]
            ).buildings
        )
        == 1
    )
    candidate.source_records.append(SourceRecord(dataset="independent survey"))
    assert len(run([candidate, lake]).buildings) == 1
