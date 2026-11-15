from shapely.geometry import box, mapping

from app.validation.elevation_followup_audit import classify_candidates


def test_every_candidate_has_evidence_based_reason_without_cross_city_denominator():
    def c(name, provider, geometry, kind="building"):
        return dict(
            candidate_id=name, provider=provider, geometry=mapping(geometry), kind=kind
        )

    candidates = [
        c("osm-match", "osm", box(0, 0, 10, 10)),
        c("ov-match", "overture", box(0, 0, 10, 10)),
        c("ov-missing", "overture", box(100, 100, 110, 110)),
        c("ov-part", "overture", box(1, 1, 2, 2), "building_part"),
        c("ov-small", "overture", box(1, 1, 2, 2)),
    ]
    rows = classify_candidates(candidates, {"osm-match", "ov-match"}, [])
    reasons = {r["id"]: r["classification"] for r in rows}
    assert len(rows) == len(candidates)
    assert reasons == dict(
        zip(
            ["osm-match", "ov-match", "ov-missing", "ov-part", "ov-small"],
            [
                "aligned",
                "aligned",
                "missing_osm_counterpart",
                "building_part_vs_building",
                "different_geometry_representation",
            ],
            strict=True,
        )
    )
