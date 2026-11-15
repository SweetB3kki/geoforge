"""Rebuild experimental G.5 scenes from the saved v0.5 provider extracts."""

import json
from pathlib import Path

from app.exporters.json_exporter import export_json
from app.fusion.road_profiles import apply_road_profiles
from app.gis.coordinates import BBoxSelection, CenterSelection
from app.services.generation import generate
from app.validation.fusion_scene_audit import SavedOverture, TraceOSM


def replay(root=Path("output")):
    for city in ("moscow", "sevastopol"):
        inputs = root / "multisource-v05" / city
        baseline = json.loads((root / "audit-v041" / city / "scene.json").read_bytes())
        report = json.loads((inputs / "providers.json").read_bytes())
        selection = report["selection"]
        out = root / "v05-g5" / city
        out.mkdir(parents=True, exist_ok=True)
        scene = generate(
            (CenterSelection if "radius_m" in selection else BBoxSelection)(
                **selection
            ),
            out,
            TraceOSM(baseline),
            data_mode="auto",
            overture_provider=SavedOverture(inputs, report),
        ).scene
        if not apply_road_profiles(scene).get("applied"):
            raise ValueError("Road profile solver did not converge")
        export_json(scene, out / "scene.json")
        before = json.loads(
            (inputs.parent / "phase-g" / city / "scene.json").read_bytes()
        )
        after = json.loads((out / "scene.json").read_bytes())
        for key in ("terrain", "roads"):
            if before[key] != after[key]:
                raise ValueError(f"Unexpected replay drift: {city} {key}")
        assert [w["polygon"] for w in before["water_areas"]] == [
            w["polygon"] for w in after["water_areas"]
        ]
        print(city, len(before["buildings"]), len(after["buildings"]), flush=True)


if __name__ == "__main__":
    replay()
