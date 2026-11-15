"""Compare against v0.4 data and benchmark trace overhead on identical raw inputs."""

import argparse
import json
import statistics
from pathlib import Path
from time import perf_counter

import geopandas as gpd
from shapely.geometry import shape

from app.gis.coordinates import BBoxSelection, CenterSelection, LocalFrame
from app.gis.processing import build_scene


def run(city, benchmark=False):
    directory = Path("output/audit-v041") / city
    old_path = Path("output/environment-v04") / city / "scene.json"
    new_path = directory / "scene.json"
    old = json.loads(old_path.read_text(encoding="utf-8"))
    new = json.loads(new_path.read_text(encoding="utf-8"))
    result = {
        "old_bytes": old_path.stat().st_size,
        "new_bytes": new_path.stat().st_size,
    }
    for category in ("buildings", "roads", "water_areas", "green_areas"):
        a = {x["id"]: x for x in old[category]}
        b = {x["id"]: x for x in new[category]}
        ignore = {"source", "source_osm_ids", "processing", "source_tags"}
        result[category] = {
            "added_ids": sorted(b.keys() - a.keys()),
            "removed_ids": sorted(a.keys() - b.keys()),
            "changed_existing_geometry_or_semantics": [
                k
                for k in a.keys() & b.keys()
                if any(a[k][f] != b[k][f] for f in a[k] if f not in ignore)
            ],
            "changed_source_tags": [
                k
                for k in a.keys() & b.keys()
                if a[k]["source_tags"] != b[k]["source_tags"]
            ],
        }
    (directory / "legacy-equality.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    if benchmark:
        selection = (
            CenterSelection(latitude=44.6, longitude=33.5, radius_m=500)
            if city == "sevastopol"
            else BBoxSelection(west=37.585, south=55.728, east=37.605, north=55.738)
        )
        records = new["processing_audit"]["records"]
        rows = [
            {
                **r["source_tags"],
                "geometry": (
                    shape(r["raw_geometry_wgs84"])
                    if r.get("raw_geometry_wgs84")
                    else None
                ),
            }
            for r in records
        ]
        features = gpd.GeoDataFrame(
            rows, index=[r["source_osm_id"] for r in records], crs=4326
        )
        frame = LocalFrame(selection)
        times = {"without_trace": [], "with_trace": []}
        build_scene(features, frame, capture_audit=False)
        for _ in range(3):
            for flag in (False, True):
                start = perf_counter()
                build_scene(features, frame, capture_audit=flag)
                times["with_trace" if flag else "without_trace"].append(
                    perf_counter() - start
                )
        measurement = {
            k: {"seconds": v, "median_seconds": statistics.median(v)}
            for k, v in times.items()
        }
        measurement["method"] = (
            "Identical saved WGS84 features; warm-up then three alternating runs; "
            "no download, DEM, PNG or validation. Baseline is current processing "
            "with capture_audit=False, not an archived binary."
        )
        (directory / "python-performance.json").write_text(
            json.dumps(measurement, indent=2), encoding="utf-8"
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    for city in ("sevastopol", "moscow"):
        print(city, run(city, args.benchmark))
