"""Rebuild opt-in G.5 candidates without overwriting accepted evidence."""

import argparse
import shutil
from pathlib import Path

from app.exporters.json_exporter import export_json
from app.fusion.road_profiles import apply_road_profiles
from app.gis.road_profiles import RoadProfileSettings
from app.models.scene import WorldScene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant", choices=("section", "bridge", "combined"), required=True
    )
    parser.add_argument("--maximum-iterations", type=int, default=16000)
    args = parser.parse_args()
    root = Path("output/v05-g5")
    settings = RoadProfileSettings(
        junctionCrossSectionRadiusFactor=(
            0.8 if args.variant in ("section", "combined") else 0
        ),
        bridgeApproachContinuity=args.variant in ("bridge", "combined"),
        maximumConstraintIterations=args.maximum_iterations,
    )
    for city in ("moscow", "sevastopol"):
        before = root / "before-roadbed-20261108" / city
        target = root / (args.variant + "-candidate") / city
        target.mkdir(parents=True, exist_ok=True)
        scene = WorldScene.model_validate_json((before / "scene.json").read_bytes())
        terrain = scene.terrain.model_dump()
        result = apply_road_profiles(scene, settings)
        if not result["applied"]:
            raise ValueError(
                {
                    k: result[k]
                    for k in (
                        "reason",
                        "constraint_iterations",
                        "max_relative_constraint_residual",
                    )
                }
            )
        assert scene.terrain.model_dump() == terrain
        export_json(scene, target / "scene.json")
        for name in ("viewpoints.json", "focus.json"):
            shutil.copy2(before / name, target / name)
        print(
            city,
            "zones",
            len(result["junction_sections"]),
            "bridge connections",
            len(result["bridge_approach_connections"]),
            "iterations",
            result["constraint_iterations"],
            flush=True,
        )


if __name__ == "__main__":
    main()
