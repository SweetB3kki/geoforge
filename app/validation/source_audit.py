"""Observe processing without changing classification, clipping or road topology."""

import json
from collections import Counter

from shapely.geometry import mapping


def begin_record(identifier, tags, geometry, frame):
    record = {
        "source": "OpenStreetMap",
        "source_osm_id": identifier,
        "source_tags": tags,
        "operations": [],
        "output_ids": [],
        "input_segment_ids": [],
        "skip_reason": None,
    }
    if geometry is not None and not geometry.is_empty:
        record["geometry_type"] = geometry.geom_type
        try:
            record["raw_geometry_wgs84"] = json.loads(
                json.dumps(mapping(geometry), allow_nan=False)
            )
            record["raw_geometry_local"] = json.loads(
                json.dumps(mapping(frame.to_local(geometry)), allow_nan=False)
            )
        except (ValueError, TypeError):
            record["raw_geometry_error"] = (
                "Non-finite or unserializable source geometry"
            )
    return record


def finish_audit(scene, records):
    """Reconcile every raw feature and every clipped road input with final IDs."""
    roads_by_input = {}
    for road in scene.roads:
        road.source_osm_ids = sorted({s.split("/road/")[0] for s in road.source_ids})
        road.processing = ["projected", "clipped", "road_semantics"]
        if len(road.source_ids) > 1:
            road.processing.append("merged")
        for source in road.source_ids:
            roads_by_input.setdefault(source, []).append(road.id)
    for record in records:
        inputs = record["input_segment_ids"]
        final = sorted({r for s in inputs for r in roads_by_input.get(s, [])})
        record["output_ids"] += final
        record["lost_segment_ids"] = [s for s in inputs if s not in roads_by_input]
        if record["lost_segment_ids"]:
            record["status"] = "lost"
        elif final:
            record["status"] = (
                "merged" if any(r.startswith("logical/") for r in final) else "retained"
            )
        elif record["output_ids"]:
            record["status"] = "retained"
        else:
            record["status"] = "filtered"
            if (
                record["source_tags"].get("highway")
                and record.get("geometry_type") == "Point"
            ):
                record["skip_reason"] = "highway_node_not_rendered"
            record["skip_reason"] = (
                record["skip_reason"] or "unsupported_geometry_or_category"
            )
    highway = [
        r
        for r in records
        if r["source_tags"].get("highway") and r.get("geometry_type") != "Point"
    ]
    stats = scene.metadata.road_statistics
    return {
        "version": "1.0",
        "records": records,
        "road_metrics": {
            "rawHighwayWays": sum(
                r["source_osm_id"].startswith("way/") for r in highway
            ),
            "rawHighwayFeatures": len(highway),
            "inputSegments": stats.input_segments,
            "topologySegments": stats.topology_segments,
            "processedLogicalRoads": len(scene.roads),
            "mergedSegments": stats.segments_merged,
            "filteredSegments": sum(r["status"] == "filtered" for r in highway),
            "invalidSegments": sum(
                r["skip_reason"] == "invalid_geometry" for r in highway
            ),
            "outsideSelectionSegments": sum(
                r["skip_reason"] == "outside_selection" for r in highway
            ),
            "lostSegments": sum(len(r["lost_segment_ids"]) for r in highway),
            "skipReasons": dict(
                Counter(r["skip_reason"] for r in highway if r["skip_reason"])
            ),
            "counting": "inputSegments are clipped polylines; "
            "filtered/outside/invalid counts are raw features",
        },
    }
