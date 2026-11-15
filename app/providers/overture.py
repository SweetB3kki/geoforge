"""Overture acquisition with pinned release, bbox-only queries and offline cache."""

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter

import geopandas as gpd
from shapely import from_wkb
from shapely.geometry import box

from app.core.config import CACHE_DIR, PROJECT_ROOT
from app.providers.base import BBox, ProviderResult, ProviderStatus, validate_bbox
from app.providers.cache import CacheError, ProviderCache
from app.providers.overture_catalog import THEMES, OvertureCatalog


def decode_features(data: bytes, bbox: BBox) -> gpd.GeoDataFrame:
    import pyarrow.parquet as pq

    table = pq.read_table(io.BytesIO(data))
    if not {"id", "geometry"} <= set(table.column_names):
        raise ValueError("Overture response lacks id/geometry")
    geometry = from_wkb(table["geometry"].to_pylist())
    frame = gpd.GeoDataFrame(
        table.drop(["geometry"]).to_pandas(), geometry=geometry, crs=4326
    )
    if frame["id"].isna().any() or frame["id"].duplicated().any():
        raise ValueError("Overture response contains missing or duplicate IDs")
    if frame.geometry.isna().any():
        raise ValueError("Overture response contains missing geometry")
    # The cloud predicate selects envelopes; exact intersection removes false positives.
    return frame.loc[frame.intersects(box(*bbox))].reset_index(drop=True)


def run_query(query: dict, timeout: float) -> tuple[bytes, dict]:
    with tempfile.TemporaryDirectory(prefix="geoforge-overture-") as folder:
        output = Path(folder) / "features.parquet"
        request = {**query, "output": str(output)}
        process = subprocess.run(
            [sys.executable, "-m", "app.providers.overture_worker"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if process.returncode != 0:
            raise RuntimeError(process.stdout[-2000:] or process.stderr[-2000:])
        metrics = json.loads(process.stdout.strip().splitlines()[-1])
        return output.read_bytes(), metrics


class OvertureProvider:
    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        refresh=False,
        use_cache=True,
        timeout=180,
        catalog=None,
        query_runner=None,
    ):
        self.cache = ProviderCache(cache_dir or CACHE_DIR / "overture")
        self.refresh, self.use_cache, self.timeout = refresh, use_cache, timeout
        self.catalog = catalog or OvertureCatalog(
            self.cache, refresh=refresh, use_cache=use_cache
        )
        self.query_runner = query_runner or run_query

    def fetch(self, bbox: BBox, feature_type: str) -> ProviderResult:
        validate_bbox(bbox)
        if feature_type not in THEMES:
            raise ValueError(f"Unsupported Overture feature type: {feature_type}")
        start = perf_counter()
        catalog_bytes_before = self.catalog.download_bytes
        result = ProviderResult(
            "overture", None, feature_type, ProviderStatus.UNAVAILABLE
        )
        result.metadata = {
            "bbox": list(bbox),
            "attribution": "Overture Maps Foundation and upstream contributors",
            "attribution_url": "https://docs.overturemaps.org/attribution/",
            "cache_policy": "pinned release until explicit refresh",
            "metrics_note": "Network bytes unknown; extract bytes reported separately",
        }
        try:
            release, catalog_url = self.catalog.release()
            result.release = release
            identity = {
                "provider": "overture",
                "release": release,
                "bbox": [float(v) for v in bbox],
                "feature_type": feature_type,
                "options": {"format": 1, "predicate": "envelope+exact_intersection"},
            }
            cached = None
            cache_start = perf_counter()
            if self.use_cache and not self.refresh:
                try:
                    cached = self.cache.read(identity)
                except CacheError as exc:
                    result.warnings.append(str(exc))
            if cached is not None:
                data, info = cached
                result.metadata.update(info["metadata"])
                result.metadata["original_query_seconds"] = result.metadata.get(
                    "query_seconds"
                )
                result.metadata["query_seconds"] = 0.0
                result.warnings.extend(info["metadata"].get("acquisition_warnings", []))
                if info["metadata"].get("empty_spatial_assets"):
                    result.features = gpd.GeoDataFrame(geometry=[], crs=4326)
                else:
                    result.features = decode_features(data, bbox)
                result.cache_hit = True
                result.bytes_transferred = (
                    self.catalog.download_bytes - catalog_bytes_before
                )
                result.metadata["cache_read_seconds"] = perf_counter() - cache_start
                result.metadata["cache_created_at"] = info["created_at"]
            else:
                query = self.catalog.query(feature_type, bbox, release, catalog_url)
                result.warnings.extend(query["warnings"])
                result.metadata.update(
                    {k: v for k, v in query.items() if k != "warnings"}
                )
                if not query["paths"]:
                    data = b""
                    result.metadata["empty_spatial_assets"] = True
                    result.bytes_transferred = (
                        self.catalog.download_bytes - catalog_bytes_before
                    )
                else:
                    data, metrics = self.query_runner(
                        {
                            **query,
                            "bbox": bbox,
                            "kind": feature_type,
                            "release": release,
                        },
                        self.timeout,
                    )
                    result.metadata.update(metrics)
                    result.features = decode_features(data, bbox)
                result.metadata["extract_bytes"] = len(data)
                result.metadata["acquisition_warnings"] = query["warnings"]
                if self.use_cache:
                    try:
                        self.cache.write(identity, data, result.metadata)
                    except OSError as exc:
                        result.warnings.append(f"cache_write_failed: {exc}")
            result.status = (
                ProviderStatus.EMPTY
                if result.features.empty
                else ProviderStatus.SUCCESS
            )
        except Exception as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
        result.warnings.extend(self.catalog.warnings)
        result.metadata["catalog_download_bytes_session"] = self.catalog.download_bytes
        result.metadata["elapsed_seconds"] = perf_counter() - start
        result.download_time = (
            0.0
            if result.cache_hit and result.bytes_transferred == 0
            else result.metadata["elapsed_seconds"]
        )
        return result
