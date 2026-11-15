"""Normalize saved provider extracts and OSM trace without network requests."""

import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from app.fusion.normalization import normalize
from app.gis.coordinates import BBoxSelection, CenterSelection, LocalFrame
from app.models.candidates import CandidateBatch
from app.providers.base import ProviderResult, ProviderStatus


def audit(provider_dir: Path, osm_scene: Path, output: Path) -> dict:
    report = json.loads((provider_dir / "providers.json").read_text(encoding="utf-8"))
    selected = report["selection"]
    selection = (
        CenterSelection(**selected)
        if "radius_m" in selected
        else BBoxSelection(**selected)
    )
    frame = LocalFrame(selection)
    scene = json.loads(osm_scene.read_text(encoding="utf-8"))
    rows, ids = [], []
    for record in scene["processing_audit"]["records"]:
        if record.get("raw_geometry_wgs84") is None:
            continue
        rows.append(
            {**record["source_tags"], "geometry": shape(record["raw_geometry_wgs84"])}
        )
        ids.append(tuple(record["source_osm_id"].split("/", 1)))
    osm = ProviderResult(
        "osm",
        None,
        "features",
        ProviderStatus.SUCCESS,
        features=gpd.GeoDataFrame(rows, index=pd.MultiIndex.from_tuples(ids), crs=4326),
        metadata={
            "license": "ODbL-1.0",
            "attribution_url": "https://www.openstreetmap.org/copyright",
            "offline_trace": str(osm_scene),
        },
    )
    results = [osm]
    for entry in report["runs"]["initial"]:
        if entry["provider"] != "overture":
            continue
        path = provider_dir / (entry["feature_type"] + ".parquet")
        status = ProviderStatus(entry["status"])
        if status == ProviderStatus.SUCCESS and not path.is_file():
            raise ValueError(f"Missing successful provider extract: {path}")
        results.append(
            ProviderResult(
                "overture",
                entry["release"],
                entry["feature_type"],
                status,
                features=(
                    gpd.read_parquet(path)
                    if path.is_file()
                    else gpd.GeoDataFrame(geometry=[], crs=4326)
                ),
                metadata=entry["metadata"],
                warnings=entry["warnings"],
                errors=entry["errors"],
            )
        )
    start = perf_counter()
    batch = normalize(results, frame)
    seconds = perf_counter() - start
    output.mkdir(parents=True, exist_ok=True)
    data = batch.model_dump_json(indent=2)
    (output / "candidates.json").write_text(data, encoding="utf-8")
    restored = CandidateBatch.model_validate_json(data)
    assert [c.candidate_id for c in restored.candidates] == [
        c.candidate_id for c in batch.candidates
    ]
    summary = {
        "scope": "normalized candidates, before fusion or rendering",
        "normalization_seconds": seconds,
        "counts": dict(Counter(f"{c.provider}/{c.kind}" for c in batch.candidates)),
        "diagnostics": dict(Counter(d["reason"] for d in batch.diagnostics)),
        "warnings": dict(Counter(w for c in batch.candidates for w in c.warnings)),
        "osm_source_links": sum(
            s.osm_id is not None for c in batch.candidates for s in c.source_records
        ),
        "candidate_json_bytes": (output / "candidates.json").stat().st_size,
        "roundtrip_validated": True,
    }
    (output / "candidate-quality.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--osm-scene", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(audit(args.provider_dir, args.osm_scene, args.output_dir), indent=2)
    )


if __name__ == "__main__":
    main()
