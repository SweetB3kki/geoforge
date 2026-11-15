"""Validate a scene before Unity, with geometry and provenance diagnostics."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from pydantic import ValidationError
from pyproj import CRS
from shapely.geometry import LineString, Polygon, box, shape
from shapely.validation import explain_validity

from app.models.scene import WorldScene


def validate_scene(data: dict) -> dict:
    report = {"version": "0.4.1", "valid": True, "warnings": [], "objects": []}

    def issue(code, stage, detail, identifier=None, severity="warning"):
        report["warnings"].append(
            dict(
                code=code,
                stage_of_origin=stage,
                detail=detail,
                object_id=identifier,
                severity=severity,
            )
        )
        if severity == "error":
            report["valid"] = False

    try:
        json.dumps(data, allow_nan=False)
        # Required core fields must be explicit even when a Pydantic default exists.
        for key in (
            "metadata",
            "origin",
            "bounds",
            "buildings",
            "roads",
            "water_areas",
            "green_areas",
        ):
            if key not in data:
                raise ValueError("Missing required field: " + key)
        for key in ("schema_version", "crs", "axes", "units"):
            if key not in data["metadata"]:
                raise ValueError("Missing metadata field: " + key)
        scene = WorldScene.model_validate(data)
        if scene.metadata.fusion_mode == "auto":
            report["version"] = "0.5"
        crs = CRS.from_user_input(scene.metadata.crs)
        if not crs.is_projected or any(a.unit_name != "metre" for a in crs.axis_info):
            raise ValueError("CRS must be projected in meters")
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        issue("invalid_contract", "SCENE_MODEL", str(exc), severity="error")
        return report
    b = scene.bounds
    selection = Polygon(
        scene.metadata.selection_boundary.exterior,
        scene.metadata.selection_boundary.holes,
    )
    bounds = box(b.min_x, b.min_y, b.max_x, b.max_y)
    if not selection.is_valid or not bounds.buffer(0.02).covers(selection):
        issue(
            "selection_boundary",
            "SCENE_MODEL",
            "Invalid selection or bounds mismatch",
            severity="error",
        )
    ids, geometries = set(), {}
    for category, objects in (
        ("buildings", [obj for b in scene.buildings for obj in [b, *b.parts]]),
        ("roads", scene.roads),
        ("water", scene.water_areas),
        ("green", scene.green_areas),
    ):
        for obj in objects:
            identifier = obj.id
            if not identifier or identifier in ids:
                issue(
                    "duplicate_or_empty_id",
                    "SCENE_MODEL",
                    identifier,
                    identifier,
                    "error",
                )
            ids.add(identifier)
            polygon = getattr(obj, "footprint", getattr(obj, "polygon", None))
            geom = (
                Polygon(polygon.exterior, polygon.holes)
                if polygon
                else LineString(obj.path)
            )
            if not geom.is_valid or geom.is_empty:
                issue(
                    "invalid_geometry",
                    "SCENE_MODEL",
                    explain_validity(geom),
                    identifier,
                    "error",
                )
            if not geom.is_simple:
                issue(
                    "self_intersection",
                    "SCENE_MODEL",
                    "Non-simple geometry",
                    identifier,
                )
            fingerprint = (category, geom.normalize().wkb)
            if fingerprint in geometries:
                issue(
                    "duplicate_geometry",
                    "PROCESSING",
                    geometries[fingerprint],
                    identifier,
                )
            geometries[fingerprint] = identifier
            if not selection.buffer(0.05).covers(geom):
                issue(
                    "outside_selection",
                    "PROCESSING",
                    "Geometry exceeds selection by >5cm",
                    identifier,
                )
            rings = [polygon.exterior, *polygon.holes] if polygon else [obj.path]
            lengths = [
                math.dist(a[:2], c[:2])
                for ring in rings
                for a, c in zip(ring, ring[1:], strict=False)
            ]
            if any(v == 0 for v in lengths):
                issue(
                    "duplicate_consecutive_vertex",
                    "PROCESSING",
                    "Zero length edge",
                    identifier,
                )
            if any(0 < v < 0.05 for v in lengths):
                issue("tiny_segment", "PROCESSING", "Edge shorter than 5cm", identifier)
            if polygon:
                if geom.area <= 0:
                    issue(
                        "zero_area",
                        "SCENE_MODEL",
                        "Nonpositive polygon area",
                        identifier,
                        "error",
                    )
                elif geom.area < 1:
                    issue(
                        "tiny_polygon", "SOURCE", f"Area {geom.area:.3f} m2", identifier
                    )
                if geom.area > selection.area * 0.8:
                    issue(
                        "huge_polygon",
                        "SOURCE",
                        "More than 80% of selection",
                        identifier,
                    )
                if geom.area > 0 and geom.length**2 / geom.area > 1000:
                    issue(
                        "extreme_aspect_or_spikes",
                        "SOURCE",
                        "Perimeter squared / area >1000",
                        identifier,
                    )
                for ring in rings:
                    for a, c, d in zip(ring, ring[1:], ring[2:], strict=False):
                        u, v = np.array(c[:2]) - a[:2], np.array(d[:2]) - c[:2]
                        norm = np.linalg.norm(u) * np.linalg.norm(v)
                        if norm and np.dot(u, v) / norm < -0.98:
                            issue(
                                "spike",
                                "SOURCE",
                                "Near reversal in polygon ring",
                                identifier,
                            )
                            break
                        if (
                            norm
                            and np.dot(u, v) / norm > 0.9999
                            and min(np.linalg.norm(u), np.linalg.norm(v)) < 0.1
                        ):
                            issue(
                                "collinear_micro_segment",
                                "PROCESSING",
                                "Near-collinear edge below 10cm; "
                                "not automatically simplified",
                                identifier,
                            )
            elif geom.length < 0.5:
                issue(
                    "very_short_road",
                    "PROCESSING",
                    f"Length {geom.length:.3f} m",
                    identifier,
                )
            entry = {
                "id": identifier,
                "category": category,
                "source_osm_ids": obj.source_osm_ids,
                "processing": obj.processing,
            }
            if category == "buildings":
                tags = obj.source_tags
                flags = dict(
                    height_known=obj.height_source in {"osm_height", "overture_height"},
                    height_estimated=obj.height_source in {"levels", "fallback"},
                    roof_known=bool(
                        obj.resolved_tags.get("roof:shape") or tags.get("roof:shape")
                    ),
                    type_known=obj.building_type not in {"", "yes"},
                    colour_known=bool(
                        obj.resolved_tags.get("building:colour")
                        or tags.get("building:colour")
                    ),
                    geometry_repaired="repaired" in obj.processing,
                )
                entry.update(
                    flags=flags,
                    completeness_score=sum(
                        flags[k]
                        for k in (
                            "height_known",
                            "roof_known",
                            "type_known",
                            "colour_known",
                        )
                    )
                    / 4,
                )
                if obj.height_source in {"fallback", "legacy"}:
                    issue(
                        "height_" + obj.height_source,
                        "SOURCE",
                        "Height not measured in source",
                        identifier,
                    )
            if category == "roads":
                if not obj.source_ids:
                    issue(
                        "missing_road_provenance",
                        "SCENE_MODEL",
                        "No source segment IDs (legacy allowed)",
                        identifier,
                    )
                if obj.node_ids and len(obj.node_ids) != len(obj.path):
                    issue(
                        "malformed_merged_road",
                        "SCENE_MODEL",
                        "node_ids/path length mismatch",
                        identifier,
                        "error",
                    )
                for key in obj.source_tags_by_id:
                    if key not in obj.source_ids:
                        issue(
                            "orphan_road_tags", "SCENE_MODEL", key, identifier, "error"
                        )
                entry["semantics"] = {
                    k: getattr(obj, k)
                    for k in (
                        "road_type",
                        "road_category",
                        "width",
                        "width_source",
                        "oneway",
                        "lanes",
                        "bridge",
                        "tunnel",
                        "layer",
                    )
                }
            report["objects"].append(entry)
    # Width discontinuities are diagnostics, not permission to change road semantics.
    ends = {}
    for road in scene.roads:
        for node in (road.start_node, road.end_node):
            if node:
                ends.setdefault(node, []).append(road)
    for node, roads in ends.items():
        if len(roads) > 1 and max(r.width for r in roads) > 3 * min(
            r.width for r in roads
        ):
            issue(
                "width_jump",
                "SOURCE",
                "Connected width ratio >3; may be intentional",
                node,
            )
    records = (scene.processing_audit or {}).get("records", [])
    if scene.processing_audit is None:
        issue(
            "source_audit_unavailable",
            "PROCESSING",
            "Legacy scene: raw counts/loss cannot be reconstructed from output alone",
        )
    for record in records:
        if record["status"] == "filtered" and not record.get("skip_reason"):
            issue(
                "unexplained_filter",
                "PROCESSING",
                "Missing skip_reason",
                record["source_osm_id"],
                "error",
            )
        missing = [i for i in record["output_ids"] if i not in ids]
        if record.get("lost_segment_ids") or missing:
            issue(
                "lost_object",
                "PROCESSING",
                str(record.get("lost_segment_ids", []) + missing),
                record["source_osm_id"],
                "error",
            )
    raw_buildings = [
        r for r in records if r["source_tags"].get("building", "no") not in {"", "no"}
    ]
    raw_water = [
        r
        for r in records
        if r["source_tags"].get("natural") in {"water", "coastline"}
        or r["source_tags"].get("water")
        or r["source_tags"].get("waterway")
        or r["source_tags"].get("landuse") in {"reservoir", "basin"}
    ]
    coast = [r for r in raw_water if r["source_tags"].get("natural") == "coastline"]

    def in_selection(r):
        return bool(r.get("raw_geometry_local")) and shape(
            r["raw_geometry_local"]
        ).intersects(selection)

    coast_inside = sum(in_selection(r) for r in coast)
    if not scene.water_areas and coast_inside:
        issue(
            "coastline_without_surface",
            "PROCESSING",
            "Coastline data exists, but coastal water surface reconstruction "
            "is not implemented in the current pipeline.",
        )
    report["scene"] = {
        "schema_version": scene.metadata.schema_version,
        "crs": scene.metadata.crs,
        "object_count": len(ids),
    }
    report["source"] = {
        "available": scene.processing_audit is not None,
        "raw_features": len(records) if scene.processing_audit is not None else None,
    }
    report["source"]["buildingPartFeatures"] = sum(
        bool(r["source_tags"].get("building:part")) for r in records
    )
    report["source"]["skipReasons"] = dict(
        Counter(r["skip_reason"] for r in records if r.get("skip_reason"))
    )
    counts = Counter(x.height_source for x in scene.buildings)
    report["buildings"] = {
        "raw": len(raw_buildings) if scene.processing_audit is not None else None,
        "processed": len(scene.buildings),
        "height_source": dict(counts),
        "raw_tag_counts": {
            tag: sum(bool(r["source_tags"].get(tag)) for r in raw_buildings)
            for tag in (
                "height",
                "building:levels",
                "building",
                "building:colour",
                "building:material",
                "roof:shape",
                "roof:colour",
                "roof:material",
                "building:part",
            )
        },
        "holes": sum(bool(b.footprint.holes) for b in scene.buildings),
        "repaired": sum("repaired" in r["operations"] for r in raw_buildings),
        "split": sum("split" in r["operations"] for r in raw_buildings),
        "filtered": sum(r["status"] == "filtered" for r in raw_buildings),
        "lost": sum(
            bool(r.get("lost_segment_ids"))
            or any(i not in ids for i in r["output_ids"])
            for r in raw_buildings
        ),
    }
    report["roads"] = (
        (scene.processing_audit or {})
        .get("road_metrics", {"raw": None, "processedLogicalRoads": len(scene.roads)})
        .copy()
    )
    report["roads"]["missingSceneRoads"] = sum(
        any(i not in ids for i in r["output_ids"])
        for r in records
        if r["source_tags"].get("highway")
    )
    report["water"] = {
        "rawWaterFeatureCount": (
            len(raw_water) if scene.processing_audit is not None else None
        ),
        "waterPolygonCount": len(scene.water_areas),
        "processedWaterFeatureCount": len(scene.water_areas),
        "waterRelations": sum(
            r["source_osm_id"].startswith("relation/") for r in raw_water
        ),
        "coastlineWayCount": coast_inside,
        "coastlineInQueryBBox": len(coast),
        "waterwayCount": sum(
            bool(r["source_tags"].get("waterway")) and in_selection(r)
            for r in raw_water
        ),
        "waterCoverageArea": sum(
            Polygon(a.polygon.exterior, a.polygon.holes).area for a in scene.water_areas
        ),
    }
    report["terrain"] = {"available": scene.terrain is not None}
    if scene.terrain:
        t = scene.terrain
        h = np.array(t.heights).reshape(t.resolution_y, t.resolution_x)
        dz, dx = np.gradient(h, t.cell_size[1], t.cell_size[0])
        slopes = np.degrees(np.arctan(np.hypot(dx, dz)))
        mask = np.array(t.valid_mask).reshape(h.shape)
        spikes = (
            np.abs(
                h[1:-1, 1:-1]
                - (h[:-2, 1:-1] + h[2:, 1:-1] + h[1:-1, :-2] + h[1:-1, 2:]) / 4
            )
            > 5
        )
        report["terrain"].update(
            height_range=t.max_height - t.min_height,
            max_local_slope=float(slopes[mask].max()),
            mean_slope=float(slopes[mask].mean()),
            suspicious_local_spike_count=int(spikes.sum()),
            source=t.source,
        )
        if spikes.any():
            issue(
                "dem_spikes", "SOURCE", "Neighbor deviation >5m; DSM is not bare earth"
            )
    report["warning_count"] = len(report["warnings"])
    return report


def write_report(scene, path):
    report = validate_scene(scene.model_dump(mode="json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate_scene(json.loads(args.scene.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        report = {
            "valid": False,
            "warnings": [
                {
                    "stage_of_origin": "SCENE_MODEL",
                    "code": "unreadable_json",
                    "detail": str(exc),
                }
            ],
        }
    output = args.output or args.scene.with_name("scene-quality.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(f"valid={report['valid']} warnings={len(report['warnings'])} report={output}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
