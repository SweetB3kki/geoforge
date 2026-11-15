"""Read-only bridge profile diagnostics; spatial candidates do not change topology."""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from shapely.geometry import Point, Polygon

from app.fusion.scene_adapter import terrain_height
from app.models.scene import WorldScene


def xy_key(point):
    return tuple(round(v, 6) for v in point[:2])


def endpoint_candidates(roads):
    """Match original vertices only, across bridge flags/layers, without snapping."""
    vertices = defaultdict(list)
    for road in roads:
        if road.bridge or road.tunnel:
            continue
        for index, point in enumerate(road.path):
            vertices[xy_key(point)].append((road, index))
    result = []
    for bridge in roads:
        if not bridge.bridge:
            continue
        for end in (0, -1):
            point = bridge.path[end]
            profile = bridge.vertical_profile
            height = profile.points[end][2] if profile else None
            candidates = []
            for road, index in vertices[xy_key(point)]:
                if road.road_category != bridge.road_category:
                    continue
                matches = (
                    [
                        p[2]
                        for p in road.vertical_profile.points
                        if xy_key(p) == xy_key(point)
                    ]
                    if road.vertical_profile
                    else []
                )
                # Do not substitute a nearest sample for a missing original vertex.
                ground_height = matches[0] if len(matches) == 1 else None
                candidates.append(
                    {
                        "road_id": road.id,
                        "path_index": index,
                        "at_endpoint": index in (0, len(road.path) - 1),
                        "layer": road.layer,
                        "height": ground_height,
                        "bridge_minus_ground_m": (
                            height - ground_height
                            if height is not None and ground_height is not None
                            else None
                        ),
                    }
                )
            result.append(
                {
                    "bridge_id": bridge.id,
                    "end": "start" if end == 0 else "end",
                    "xy": list(point[:2]),
                    "height": height,
                    "candidates": candidates,
                }
            )
    return result


def cross_sections(road):
    """Five lateral samples per station/tangent, including both sides of bends."""
    points = road.vertical_profile.points
    for index, point in enumerate(points):
        normals = set()
        for a, b in [
            (points[max(0, index - 1)], point),
            (point, points[min(len(points) - 1, index + 1)]),
        ]:
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length > 1e-8:
                normals.add((-dy / length, dx / length))
        for nx, ny in sorted(normals):
            for fraction in (-1, -0.5, 0, 0.5, 1):
                offset = road.width * 0.5 * fraction
                yield (point[0] + nx * offset, point[1] + ny * offset, point[2])


def valid_terrain_sample(terrain, x, y):
    if terrain is None:
        return False
    gx = (x - terrain.origin[0]) / terrain.cell_size[0]
    gy = (y - terrain.origin[1]) / terrain.cell_size[1]
    nx, ny = terrain.resolution_x, terrain.resolution_y
    if not (0 <= gx <= nx - 1 and 0 <= gy <= ny - 1):
        return False
    ix, iy = min(int(gx), nx - 2), min(int(gy), ny - 2)
    k = iy * nx + ix
    return all(terrain.valid_mask[i] for i in (k, k + 1, k + nx, k + nx + 1))


def audit(scene):
    endpoints = endpoint_candidates(scene.roads)
    water = [
        (
            area,
            Polygon(
                [p[:2] for p in area.polygon.exterior],
                [[p[:2] for p in ring] for ring in area.polygon.holes],
            ),
        )
        for area in scene.water_areas
    ]
    results = []
    for road in scene.roads:
        if not road.bridge:
            continue
        terrain_gaps, water_gaps = [], []
        missing_terrain = missing_water_level = samples = 0
        if road.vertical_profile:
            for x, y, height in cross_sections(road):
                samples += 1
                if valid_terrain_sample(scene.terrain, x, y):
                    terrain_gaps.append(height - terrain_height(scene.terrain, x, y))
                else:
                    missing_terrain += 1
                for area, polygon in water:
                    if polygon.covers(Point(x, y)):
                        if area.water_level_m is None:
                            missing_water_level += 1
                        else:
                            water_gaps.append(height - area.water_level_m)
        results.append(
            {
                "road_id": road.id,
                "category": road.road_category,
                "layer": road.layer,
                "profile_available": road.vertical_profile is not None,
                "samples": samples,
                "missing_terrain_samples": missing_terrain,
                "water_samples_without_level": missing_water_level,
                "water_samples_with_level": len(water_gaps),
                "min_profile_above_terrain_m": min(terrain_gaps, default=None),
                "min_profile_above_water_m": min(water_gaps, default=None),
                "samples_below_terrain": sum(g < -0.02 for g in terrain_gaps),
                "samples_below_water": sum(g < -0.02 for g in water_gaps),
            }
        )
    gaps = [
        abs(c["bridge_minus_ground_m"])
        for e in endpoints
        for c in e["candidates"]
        if c["bridge_minus_ground_m"] is not None
    ]
    return {
        "scope": "Exported profiles only, five lateral samples per station/tangent. "
        "No Unity mesh, deck underside, continuous clearance "
        "or connectivity acceptance. "
        "Exact XY candidates across layers are diagnostic, "
        "not authorized topology joins.",
        "summary": {
            "bridges": len(results),
            "missing_terrain_samples": sum(
                r["missing_terrain_samples"] for r in results
            ),
            "water_samples_with_level": sum(
                r["water_samples_with_level"] for r in results
            ),
            "water_samples_without_level": sum(
                r["water_samples_without_level"] for r in results
            ),
            "endpoints": len(endpoints),
            "endpoints_without_candidate": sum(not e["candidates"] for e in endpoints),
            "candidate_pairs": sum(len(e["candidates"]) for e in endpoints),
            "measured_candidate_pairs": len(gaps),
            "candidate_gaps_over_2cm": sum(g > 0.02 for g in gaps),
            "max_abs_candidate_gap_m": max(gaps, default=None),
            "bridges_with_terrain_penetration": sum(
                r["samples_below_terrain"] > 0 for r in results
            ),
            "bridges_with_water_penetration": sum(
                r["samples_below_water"] > 0 for r in results
            ),
        },
        "endpoints": endpoints,
        "cross_sections": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    args = parser.parse_args()
    payload = args.scene.read_bytes()
    result = audit(WorldScene.model_validate_json(payload))
    result["scene_sha256"] = hashlib.sha256(payload).hexdigest()
    args.scene.with_name("road-bridge-audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
