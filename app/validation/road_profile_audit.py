"""Run phase G numerical prototype on a saved scene, without rewriting it."""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.fusion.scene_adapter import terrain_height  # noqa: E402
from app.gis.road_profiles import resolve_profiles  # noqa: E402
from app.models.scene import WorldScene  # noqa: E402


def audit(path):
    payload = path.read_bytes()
    scene = WorldScene.model_validate_json(payload)
    if scene.terrain is None:
        raise ValueError("Real profile audit requires a recorded DEM")
    started = perf_counter()
    profiles, result = resolve_profiles(
        scene.roads, lambda x, y: terrain_height(scene.terrain, x, y)
    )
    result["elapsed_seconds"] = perf_counter() - started
    result["scene_sha256"] = hashlib.sha256(payload).hexdigest()
    result["source_scene_unchanged"] = payload == path.read_bytes()
    result["profile_count"] = len(profiles)
    result["sample_count"] = sum(len(p.heights) for p in profiles)
    ground = [p for p in profiles if p.strategy == "AUTOMOTIVE_GROUND"]
    deviations = (
        np.concatenate([np.array(p.heights) - p.raw_heights for p in ground])
        if ground
        else np.array([])
    )
    result["automotive_ground"] = {
        "count": len(ground),
        "grade_limit_exceeded": sum(
            p.metrics["conditioned"]["max_abs_grade"] > p.max_grade + 0.0001
            for p in ground
        ),
        "curvature_limit_exceeded": sum(
            p.metrics["conditioned"]["max_abs_curvature"] > p.max_curvature + 0.0001
            for p in ground
        ),
        "max_terrain_deviation_m": max(
            (p.metrics["max_abs_terrain_deviation"] for p in ground), default=0
        ),
        "max_above_raw_dsm_m": float(np.max(deviations, initial=0)),
        "max_below_raw_dsm_m": float(np.max(-deviations, initial=0)),
        "samples_below_raw_dsm_over_2cm": int(np.sum(deviations < -0.02)),
        "raw_max_grade": max(
            (p.metrics["raw"]["max_abs_grade"] for p in ground), default=0
        ),
        "conditioned_max_grade": max(
            (p.metrics["conditioned"]["max_abs_grade"] for p in ground), default=0
        ),
        "raw_max_curvature": max(
            (p.metrics["raw"]["max_abs_curvature"] for p in ground), default=0
        ),
        "conditioned_max_curvature": max(
            (p.metrics["conditioned"]["max_abs_curvature"] for p in ground), default=0
        ),
    }
    result["profiles"] = [asdict(p) for p in profiles]
    path.with_name("road-profile-prototype.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    selected = sorted(
        ground,
        key=lambda p: p.metrics["raw"]["max_abs_curvature"],
        reverse=True,
    )[:3]
    if selected:
        fig, axes = plt.subplots(
            len(selected), 1, figsize=(11, 3 * len(selected)), squeeze=False
        )
        for axis, profile in zip(axes[:, 0], selected, strict=True):
            axis.plot(
                profile.distances, profile.raw_heights, label="Raw DSM", color="#9a6955"
            )
            axis.plot(
                profile.distances,
                profile.heights,
                label="Conditioned prototype",
                color="#1778a8",
            )
            axis.set(
                title=profile.road_id,
                xlabel="Distance (m)",
                ylabel="Local elevation (m)",
            )
            axis.grid(alpha=0.2)
            axis.legend()
        fig.suptitle("Numerical diagnostic only — not a Unity render")
        fig.tight_layout()
        fig.savefig(path.with_name("road-profile-prototype.png"), dpi=150)
        plt.close(fig)
    return {k: v for k, v in result.items() if k != "profiles"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--export-profiled-scene", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.scene), indent=2))
    if args.export_profiled_scene:
        from app.fusion.road_profiles import apply_road_profiles

        scene = WorldScene.model_validate_json(args.scene.read_bytes())
        report = apply_road_profiles(scene)
        if not report["applied"]:
            raise ValueError(f"Experimental profile export failed: {report}")
        args.export_profiled_scene.parent.mkdir(parents=True, exist_ok=True)
        args.export_profiled_scene.write_text(
            scene.model_dump_json(indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
