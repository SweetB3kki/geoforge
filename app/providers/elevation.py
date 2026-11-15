"""Copernicus tile adapter retaining the established mirror, cache and resampler."""

import math
from time import perf_counter

import geopandas as gpd
from shapely.geometry import box

from app.core.config import PROJECT_ROOT
from app.gis.elevation import ATTRIBUTION, planetary_tile, tile_url
from app.providers.base import BBox, ProviderResult, ProviderStatus, validate_bbox


class CopernicusElevationProvider:
    def fetch(self, bbox: BBox, feature_type: str = "terrain") -> ProviderResult:
        validate_bbox(bbox)
        if feature_type != "terrain":
            raise ValueError("Elevation provider supports terrain tiles only")
        start = perf_counter()
        result = ProviderResult(
            "copernicus", "GLO-30", feature_type, ProviderStatus.UNAVAILABLE
        )
        result.metadata = {
            "bbox": list(bbox),
            "attribution": ATTRIBUTION,
            "source": "Copernicus DEM GLO-30",
            "vertical_datum": "EGM2008",
            "cache_policy": "existing data/dem GeoTIFF and source metadata",
            "license_url": "https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model",
            "release_note": "GLO-30 product; no dated dataset release identifier",
        }
        cache = PROJECT_ROOT / "data" / "dem"
        w, s, e, n = bbox
        tiles, hits = [], []
        try:
            for lat in range(math.floor(s), math.floor(n) + 1):
                for lon in range(math.floor(w), math.floor(e) + 1):
                    name = tile_url(lat, lon).rsplit("/", 1)[-1]
                    hits.append(
                        (cache / name).exists()
                        and (cache / name.replace(".tif", ".source.json")).exists()
                    )
                    path, url = planetary_tile(lat, lon, cache)
                    tiles.append(
                        {
                            "path": str(path),
                            "source_url": url,
                            "geometry": box(lon, lat, lon + 1, lat + 1),
                        }
                    )
            result.features = gpd.GeoDataFrame(tiles, crs=4326)
            result.status = ProviderStatus.SUCCESS
            result.cache_hit = all(hits)
            result.bytes_transferred = 0 if result.cache_hit else None
        except Exception as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
        result.metadata["elapsed_seconds"] = perf_counter() - start
        result.download_time = (
            0 if result.cache_hit else result.metadata["elapsed_seconds"]
        )
        return result
