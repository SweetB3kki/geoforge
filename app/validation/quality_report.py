"""Combine independent source/contract and Unity measurements without inventing data."""

import argparse
import hashlib
import json
from pathlib import Path


def combine(directory: Path):
    def load(name):
        path = directory / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    report = load("scene-quality.json")
    if report is None:
        raise ValueError("Run scene_validator first")
    unity, before = load("unity-quality.json"), load("unity-before-quality.json")
    scene_path = directory / "scene.json"
    if unity and scene_path.exists():
        fingerprint = hashlib.sha256(scene_path.read_bytes()).hexdigest()
        for measurement in (unity, before):
            if (
                measurement is not None
                and measurement.get("scene_sha256") != fingerprint
            ):
                raise ValueError(
                    "Unity audit does not match scene.json SHA256; "
                    "rerun RenderAuditExamples"
                )
    report["unity"] = unity
    report["visual_review"] = load("visual-review.json") or []
    report["comparison"] = {
        "before": before,
        "after": unity,
        "play_before": load("play-before.json"),
        "play_after": load("play-after.json"),
    }
    report["comparison"]["python"] = load("python-performance.json")
    report["comparison"]["legacy_data"] = load("legacy-equality.json")
    if unity:
        fits = unity["buildings"]
        report["buildings"].update(
            buildingsChecked=len(fits),
            buildingsWithFoundation=sum(q["foundationDepth"] > 0 for q in fits),
            buildingsWithLargeTerrainDifference=sum(
                q["terrainHeightRange"] > 0.3 for q in fits
            ),
            maxBuildingGapMeters=max((q["maximumGap"] for q in fits), default=0),
            maxRemainingGapMeters=max((q["remainingGap"] for q in fits), default=0),
            maxBuildingPenetrationMeters=max(
                (q["maximumPenetration"] for q in fits), default=0
            ),
            maxFoundationDepthMeters=max(
                (q["foundationDepth"] for q in fits), default=0
            ),
        )
        for category in (
            "automotive",
            "pedestrian",
            "cycle",
            "steps",
            "track",
            "other",
            "green",
        ):
            surfaces = [s for s in unity["surfaces"] if s["category"] == category]
            count = sum(s["samples"] for s in surfaces)
            report.setdefault("surface_terrain", {})[category] = {
                "verticesChecked": sum(s["verticesChecked"] for s in surfaces),
                "trianglesChecked": sum(s["trianglesChecked"] for s in surfaces),
                "floatingSamples": sum(s["floatingSamples"] for s in surfaces),
                "terrainPenetrations": sum(s["terrainPenetrations"] for s in surfaces),
                "maxErrorMeters": max(
                    (s["maxTerrainErrorMeters"] for s in surfaces), default=0
                ),
                "averageErrorMeters": (
                    sum(s["averageTerrainErrorMeters"] * s["samples"] for s in surfaces)
                    / count
                    if count
                    else 0
                ),
                "limitReached": sum(s["limitReached"] for s in surfaces),
            }
        for q in unity["surfaces"]:
            if q["terrainPenetrations"] or q["floatingSamples"] or q["limitReached"]:
                report["warnings"].append(
                    {
                        "code": "surface_conformity_limit",
                        "stage_of_origin": "UNITY_RENDER",
                        "object_id": q["id"],
                        "severity": "warning",
                        "detail": q,
                    }
                )
        for q in fits:
            if q["remainingGap"] > 0.3 or q["maximumPenetration"] > 1:
                report["warnings"].append(
                    {
                        "code": "rigid_building_terrain_fit",
                        "stage_of_origin": "UNITY_RENDER",
                        "object_id": q["id"],
                        "severity": "warning",
                        "detail": {
                            k: q[k]
                            for k in (
                                "remainingGap",
                                "maximumPenetration",
                                "foundationDepth",
                            )
                        },
                    }
                )
        report["water"]["unity"] = unity["water"]
        for q in unity["water"]:
            if q["terrainElevationMismatch"] > 3:
                report["warnings"].append(
                    {
                        "code": "water_plane_terrain_difference",
                        "stage_of_origin": "UNITY_RENDER",
                        "object_id": q["id"],
                        "severity": "warning",
                        "detail": "Horizontal median water differs from DSM "
                        "at boundary by >3m; no hydrological correction is claimed",
                    }
                )
    else:
        report["warnings"].append(
            {
                "code": "unity_audit_unavailable",
                "stage_of_origin": "UNITY_RENDER",
                "severity": "warning",
                "detail": "No Unity measurements; no claim of renderer correctness",
            }
        )
    report["warning_count"] = len(report["warnings"])
    if before:
        baseline_warnings = len(load("scene-quality.json")["warnings"])
        baseline_warnings += sum(
            q["remainingGap"] > 0.3 or q["maximumPenetration"] > 1
            for q in before["buildings"]
        )
        baseline_warnings += sum(
            bool(q["terrainPenetrations"] or q["floatingSamples"] or q["limitReached"])
            for q in before["surfaces"]
        )
        baseline_warnings += sum(
            q["terrainElevationMismatch"] > 3 for q in before["water"]
        )
        report["comparison"]["before_warning_count"] = baseline_warnings
    report["comparison"]["after_warning_count"] = report["warning_count"]
    output = directory / "geometry-quality.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(combine(parser.parse_args().directory))
