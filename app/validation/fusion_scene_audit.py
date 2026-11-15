"""Replay complete AUTO generation from saved source extracts and cached DEM."""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from app.gis.coordinates import BBoxSelection, CenterSelection
from app.providers.base import ProviderResult, ProviderStatus
from app.services.generation import generate


class TraceOSM:
    def __init__(self, scene):
        records = [
            r
            for r in scene["processing_audit"]["records"]
            if r.get("raw_geometry_wgs84")
        ]
        self.features = gpd.GeoDataFrame(
            [
                {**r["source_tags"], "geometry": shape(r["raw_geometry_wgs84"])}
                for r in records
            ],
            index=pd.MultiIndex.from_tuples(
                [tuple(r["source_osm_id"].split("/", 1)) for r in records]
            ),
            crs=4326,
        )

    def fetch(self, bbox):
        return self.features.copy()


class SavedOverture:
    def __init__(self, folder, report):
        self.folder = folder
        self.entries = {
            e["feature_type"]: e
            for e in report["runs"]["initial"]
            if e["provider"] == "overture"
        }

    def fetch(self, bbox, kind):
        entry = self.entries[kind]
        path = self.folder / f"{kind}.parquet"
        return ProviderResult(
            "overture",
            entry["release"],
            kind,
            ProviderStatus(entry["status"]),
            features=(
                gpd.read_parquet(path)
                if path.exists()
                else gpd.GeoDataFrame(geometry=[], crs=4326)
            ),
            metadata={**entry["metadata"], "validation_replay": str(path)},
            warnings=entry["warnings"],
            errors=entry["errors"],
            cache_hit=True,
            bytes_transferred=0,
        )


def audit(folder, baseline_path):
    report = json.loads((folder / "providers.json").read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    selected = report["selection"]
    selection = (
        CenterSelection(**selected)
        if "radius_m" in selected
        else BBoxSelection(**selected)
    )
    result = generate(
        selection,
        folder,
        TraceOSM(baseline),
        data_mode="auto",
        overture_provider=SavedOverture(folder, report),
    )
    scene = result.scene
    assert scene.terrain is not None, "Real integration audit requires DEM"
    roads_by_id = {r.id: r.model_dump(mode="json") for r in scene.roads}
    for old in baseline["roads"]:
        current = roads_by_id[old["id"]]
        assert all(
            current[k] == v
            for k, v in old.items()
            if k not in {"width", "width_source"}
        ), "OSM road topology/semantics changed"
        if old["width_source"] == "osm_width":
            assert current["width"] == old["width"], "Explicit OSM width changed"
    assert (
        scene.terrain.model_dump(mode="json") == baseline["terrain"]
    ), "Raw DSM changed"
    old_ids = {b["id"] for b in baseline["buildings"]}
    new_ids = {b.id for b in scene.buildings}
    missing = sorted(old_ids - new_ids)
    if missing:
        raise AssertionError(f"OSM buildings lost: {missing}")
    summary = {
        "scope": "full Python AUTO generation from recorded sources and cached DEM",
        "road_topology_unchanged": True,
        "raw_dsm_unchanged": True,
        "missing_baseline_buildings": missing,
        "buildings_before": len(old_ids),
        "buildings_after": len(new_ids),
        "water_before": len(baseline["water_areas"]),
        "water_after": len(scene.water_areas),
        "schema_version": scene.metadata.schema_version,
        "fusion_metrics": scene.fusion_audit["metrics"],
    }
    (folder / "fusion-integration.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.provider_dir, args.baseline), indent=2))


if __name__ == "__main__":
    main()
