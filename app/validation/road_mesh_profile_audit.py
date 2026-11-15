"""Compare profiles with Unity collider samples without filling missing hits."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from app.gis.road_profiles import RoadGenerationStrategy, RoadProfileSettings, policy


def measure(points, heights, grade_limit, curvature_limit, tolerance=0.0001):
    if len(points) != len(heights) or len(points) < 2:
        raise ValueError(
            "Profile/sample lengths differ or contain fewer than two points"
        )
    if any(not math.isfinite(v) for p in points for v in p):
        raise ValueError("Nonfinite profile coordinate")
    if any(h is not None and not math.isfinite(h) for h in heights):
        raise ValueError("Nonfinite collider height")
    distances = [
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(points[:-1], points[1:], strict=True)
    ]
    if any(d <= 0 for d in distances):
        raise ValueError("Zero-length profile interval")
    grades = [
        None if a is None or b is None else (b - a) / d
        for a, b, d in zip(heights[:-1], heights[1:], distances, strict=True)
    ]
    curvatures = [
        None if a is None or b is None else 2 * (b - a) / (d0 + d1)
        for a, b, d0, d1 in zip(
            grades[:-1], grades[1:], distances[:-1], distances[1:], strict=True
        )
    ]
    return {
        "missing_samples": sum(h is None for h in heights),
        "checked_segments": sum(v is not None for v in grades),
        "checked_triples": sum(v is not None for v in curvatures),
        "max_abs_grade": max((abs(v) for v in grades if v is not None), default=None),
        "max_abs_curvature": max(
            (abs(v) for v in curvatures if v is not None), default=None
        ),
        "grade_exceeded_at_segment": [
            i
            for i, v in enumerate(grades)
            if v is not None and abs(v) > grade_limit + tolerance
        ],
        "curvature_exceeded_at_sample": [
            i + 1
            for i, v in enumerate(curvatures)
            if v is not None and abs(v) > curvature_limit + tolerance
        ],
    }


def audit(scene_path, checks_path):
    payload = scene_path.read_bytes()
    scene = json.loads(payload)
    checks = json.loads(checks_path.read_bytes())
    digest = hashlib.sha256(payload).hexdigest()
    if checks.get("sceneSha256") != digest:
        raise ValueError(
            "Collider audit belongs to a different scene or lacks a source hash"
        )
    settings = RoadProfileSettings(**scene["fusion_audit"]["road_profiles"]["settings"])
    measurements = checks["sampledMeshes"]
    meshes = {entry["roadId"]: entry["heights"] for entry in measurements}
    if len(meshes) != len(measurements):
        raise ValueError("Duplicate collider road measurements")
    results = []
    for road in scene["roads"]:
        profile = road.get("vertical_profile")
        if (
            not profile
            or profile["strategy"] != "AUTOMOTIVE_GROUND"
            or (road.get("layer") or 0) != 0
        ):
            continue
        points = profile["points"]
        _, grade_limit, curvature_limit = policy(
            RoadGenerationStrategy.AUTOMOTIVE_GROUND, settings
        )
        results.append(
            {
                "road_id": road["id"],
                "profile": measure(
                    points, [p[2] for p in points], grade_limit, curvature_limit
                ),
                "mesh": measure(
                    points,
                    meshes.get(road["id"], [None] * len(points)),
                    grade_limit,
                    curvature_limit,
                ),
            }
        )
    summary = {}
    for kind in ("profile", "mesh"):
        values = [r[kind] for r in results]
        summary[kind] = {
            "roads": len(values),
            "missing_samples": sum(v["missing_samples"] for v in values),
            "checked_segments": sum(v["checked_segments"] for v in values),
            "checked_triples": sum(v["checked_triples"] for v in values),
            "roads_exceeding_grade": sum(
                bool(v["grade_exceeded_at_segment"]) for v in values
            ),
            "roads_exceeding_curvature": sum(
                bool(v["curvature_exceeded_at_sample"]) for v in values
            ),
            "max_abs_grade": max(
                (v["max_abs_grade"] for v in values if v["max_abs_grade"] is not None),
                default=None,
            ),
            "max_abs_curvature": max(
                (
                    v["max_abs_curvature"]
                    for v in values
                    if v["max_abs_curvature"] is not None
                ),
                default=None,
            ),
        }
    return {
        "scope": (
            "Automotive ground, layer zero, own collider at exported sample positions "
            "only; missing hits are not interpolated. Not a complete mesh/seam gate."
        ),
        "scene_sha256": digest,
        "checks_sha256": hashlib.sha256(checks_path.read_bytes()).hexdigest(),
        "grade_limit": settings.maxRoadGrade,
        "curvature_limit": settings.maxVerticalCurvature,
        "derivative_tolerance": 0.0001,
        "summary": summary,
        "roads": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.scene, args.scene.with_name("road-profile-render-checks.json"))
    args.scene.with_name("road-mesh-profile-audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
