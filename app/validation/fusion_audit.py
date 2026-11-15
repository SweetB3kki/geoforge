"""Resolve saved candidates, validate planar geometry and render a fusion preview."""

import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import Polygon

from app.fusion.resolvers import FusionResult, polygonal, resolve
from app.models.candidates import BuildingCandidate, CandidateBatch, WaterCandidate


def preview(batch, fused, boundary, target):
    fig, axes = plt.subplots(1, 2, figsize=(14, 7), constrained_layout=True)
    for axis, title in zip(
        axes,
        ["OSM candidates (before fusion)", "Resolved buildings and water"],
        strict=True,
    ):
        gpd.GeoSeries([boundary]).boundary.plot(ax=axis, color="#777777", linewidth=0.8)
        axis.set_title(title)
        x1, y1, x2, y2 = boundary.bounds
        axis.set_xlim(x1 - 20, x2 + 20)
        axis.set_ylim(y1 - 20, y2 + 20)
        axis.set_aspect("equal")
        axis.set_xlabel("East, m")
        axis.set_ylabel("North, m")
    groups = [
        (
            axes[0],
            [
                c.geometry.intersection(boundary)
                for c in batch.candidates
                if isinstance(c, BuildingCandidate)
                and c.provider == "osm"
                and c.geometry.is_valid
            ],
            "#8a919c",
        ),
        (
            axes[0],
            [
                polygonal(c.geometry.intersection(boundary))
                for c in batch.candidates
                if isinstance(c, WaterCandidate)
                and c.provider == "osm"
                and c.attributes.is_surface
                and c.geometry.is_valid
            ],
            "#4194c4",
        ),
        (
            axes[1],
            [
                b.geometry
                for b in fused.buildings
                if b.fusion_method != "overture_supplemental"
            ],
            "#8a919c",
        ),
        (
            axes[1],
            [
                b.geometry
                for b in fused.buildings
                if b.fusion_method == "overture_supplemental"
            ],
            "#da963c",
        ),
        (axes[1], [w.geometry for w in fused.water], "#4194c4"),
    ]
    for axis, geometries, color in groups:
        geometries = [g for g in geometries if not g.is_empty]
        if geometries:
            gpd.GeoSeries(geometries).plot(
                ax=axis, color=color, edgecolor="white", linewidth=0.15
            )
    fig.suptitle(
        "Planar fusion audit — orange: supplemental Overture; blue: water (not Unity)"
    )
    fig.savefig(target, dpi=140)
    plt.close(fig)


def audit(candidates: Path, osm_scene: Path, output: Path):
    batch = CandidateBatch.model_validate_json(candidates.read_text(encoding="utf-8"))
    scene = json.loads(osm_scene.read_text(encoding="utf-8"))
    if (
        batch.crs != scene["metadata"]["crs"]
        or abs(batch.origin_easting - scene["origin"]["easting"]) > 0.001
        or abs(batch.origin_northing - scene["origin"]["northing"]) > 0.001
    ):
        raise ValueError("Candidate and scene coordinate frames differ")
    boundary_data = scene["metadata"]["selection_boundary"]
    boundary = Polygon(
        [p[:2] for p in boundary_data["exterior"]],
        [[p[:2] for p in ring] for ring in boundary_data["holes"]],
    )
    start = perf_counter()
    fused = resolve(batch, boundary)
    seconds = perf_counter() - start
    geometry = [o.geometry for o in [*fused.buildings, *fused.water]]
    invalid = sum(not g.is_valid for g in geometry)
    outside = sum(g.difference(boundary).area for g in geometry)
    water_overlap = sum(
        a.geometry.intersection(b.geometry).area
        for i, a in enumerate(fused.water)
        for b in fused.water[i + 1 :]
    )
    summary = {
        "scope": "planar building/water fusion; no Unity generation",
        "metrics": fused.metrics,
        "fusion_seconds": seconds,
        "resolved_buildings": len(fused.buildings),
        "resolved_water": len(fused.water),
        "invalid_geometry": invalid,
        "outside_selection_area_m2": outside,
        "water_overlap_area_m2": water_overlap,
        "warnings": dict(Counter(w["reason"] for w in fused.warnings)),
    }
    output.mkdir(parents=True, exist_ok=True)
    data = fused.model_dump_json(indent=2)
    FusionResult.model_validate_json(data)
    (output / "fused-data.json").write_text(data, encoding="utf-8")
    (output / "fusion-quality.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    preview(batch, fused, boundary, output / "fusion-preview.png")
    if invalid or outside > 0.01 or water_overlap > 0.01:
        raise ValueError("Planar fusion validation failed; inspect fusion-quality.json")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--osm-scene", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.candidates, args.osm_scene, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
