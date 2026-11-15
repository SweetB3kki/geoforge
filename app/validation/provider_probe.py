"""Reproducible v0.5 acquisition audit, independently of scene fusion/rendering."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.gis.coordinates import BBoxSelection, CenterSelection, LocalFrame
from app.providers.elevation import CopernicusElevationProvider
from app.providers.manager import DataSourceManager
from app.providers.overture import OvertureProvider


def available(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, np.ndarray)):
        return len(value) > 0
    return not bool(pd.isna(value))


def coverage(result, frame: LocalFrame) -> dict:
    features = result.features
    if features.empty:
        return {"bbox_count": 0, "selection_count": 0, "non_null": {}}
    selected = features.loc[
        features.geometry.map(lambda g: frame.to_local(g).intersects(frame.boundary))
    ]
    profile = {
        "bbox_count": len(features),
        "selection_count": len(selected),
        "non_null": {
            key: sum(available(value) for value in selected[key])
            for key in selected.columns
            if key != "geometry"
        },
        "invalid_geometry_count": int((~selected.geometry.is_valid).sum()),
    }
    if "subtype" in selected:
        profile["subtypes"] = {
            str(k): int(v)
            for k, v in selected["subtype"].fillna("unknown").value_counts().items()
        }
    if result.feature_type == "water" and "subtype" in selected:
        ocean = selected.loc[
            (selected["subtype"] == "ocean") & selected.geometry.is_valid
        ]
        profile["ocean_polygon_count"] = len(ocean)
        profile["ocean_area_m2"] = sum(
            frame.to_local(g).intersection(frame.boundary).area for g in ocean.geometry
        )
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", type=float, nargs=4)
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--radius", type=float)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--refresh-data", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--elevation", action="store_true")
    args = parser.parse_args()
    if args.bbox and any(v is not None for v in (args.lat, args.lon, args.radius)):
        parser.error("Use bbox or center/radius")
    if not args.bbox and any(v is None for v in (args.lat, args.lon, args.radius)):
        parser.error("Supply bbox or lat/lon/radius")
    selection = (
        BBoxSelection(
            **dict(zip(("west", "south", "east", "north"), args.bbox, strict=True))
        )
        if args.bbox
        else CenterSelection(
            latitude=args.lat, longitude=args.lon, radius_m=args.radius
        )
    )
    frame = LocalFrame(selection)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "bbox": list(frame.bbox),
        "selection": selection.model_dump(),
        "scope": "provider acquisition only; not a fused/rendered scene",
        "runs": {},
    }
    for name in ("initial", "repeat"):
        provider = OvertureProvider(
            refresh=args.refresh_data and name == "initial", use_cache=not args.no_cache
        )
        bundle = DataSourceManager(overture=provider).fetch(frame.bbox)
        results = [bundle.osm, *bundle.overture.values()]
        if args.elevation:
            results.append(CopernicusElevationProvider().fetch(frame.bbox))
        rows = []
        for result in results:
            row = result.summary()
            if result.provider == "overture":
                row["coverage"] = coverage(result, frame)
                if not result.features.empty and name == "initial":
                    result.features.to_parquet(
                        args.output_dir / f"{result.feature_type}.parquet"
                    )
            rows.append(row)
            print(
                f"{name} {result.provider}/{result.feature_type}: {result.status} "
                f"count={len(result.features)} cache={result.cache_hit}",
                flush=True,
            )
        report["runs"][name] = rows
        (args.output_dir / "providers.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
