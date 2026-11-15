"""Optional Copernicus GLO-30 raster import, isolated from the OSM pipeline."""

import argparse
import json
import logging
import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

import numpy as np
from pyproj import Transformer
from shapely import intersects_xy
from shapely.geometry import Polygon

from app.core.config import PROJECT_ROOT, configure_logging
from app.exporters.json_exporter import export_json
from app.models.scene import TerrainData, WorldScene

logger = logging.getLogger(__name__)
BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
ATTRIBUTION = (
    "© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018; "
    "produced using Copernicus WorldDEM-30; modified by GeoForge (reprojection, "
    "bilinear resampling and local height normalization)."
)


def tile_url(latitude: int, longitude: int) -> str:
    """Return a public COG URL for the southwest integer-degree tile corner."""
    lat = f"{'N' if latitude >= 0 else 'S'}{abs(latitude):02d}"
    lon = f"{'E' if longitude >= 0 else 'W'}{abs(longitude):03d}"
    name = f"Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM"
    return f"{BASE_URL}/{name}/{name}.tif"


def download_tile(url: str, cache: Path) -> Path:
    """Download atomically. Missing tiles/network errors are explicit failures."""
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / Path(urlsplit(url).path).name
    if target.is_file():
        return target
    logger.info("Downloading elevation tile %s", url.split("?", 1)[0])
    temporary = None
    try:
        with (
            urlopen(url, timeout=90) as response,
            tempfile.NamedTemporaryFile(
                dir=cache, suffix=".part", delete=False
            ) as stream,
        ):
            temporary = Path(stream.name)
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def build_terrain(
    scene: WorldScene,
    paths: list[Path],
    resolution: int = 129,
    source_urls: list[str] | None = None,
) -> TerrainData:
    """Reproject raster samples to the scene CRS; preserve node-aligned bounds."""
    try:
        import rasterio
        from rasterio.transform import from_origin
        from rasterio.warp import Resampling, reproject
    except ImportError as exc:
        raise RuntimeError(
            'Install elevation support: pip install -e ".[elevation]"'
        ) from exc
    if resolution not in {33, 65, 129, 257, 513}:
        raise ValueError("Resolution must be 33, 65, 129, 257 or 513")
    b = scene.bounds
    dx, dy = (b.max_x - b.min_x) / (resolution - 1), (b.max_y - b.min_y) / (
        resolution - 1
    )
    transform = from_origin(
        b.min_x + scene.origin.easting - dx / 2,
        b.max_y + scene.origin.northing + dy / 2,
        dx,
        dy,
    )
    grid = np.full((resolution, resolution), np.nan, dtype=np.float64)
    for path in paths:
        with rasterio.open(path) as raster:
            if raster.crs is None:
                raise ValueError(f"DEM CRS missing: {path}")
            destination = np.full_like(grid, np.nan)
            reproject(
                source=rasterio.band(raster, 1),
                destination=destination,
                src_transform=raster.transform,
                src_crs=raster.crs,
                src_nodata=raster.nodata,
                dst_transform=transform,
                dst_crs=scene.metadata.crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
            valid = np.isfinite(destination)
            grid[valid] = destination[valid]
    if not np.isfinite(grid).all():
        raise ValueError(
            "DEM has missing/nodata samples in scene bounds; "
            "no fake heights substituted"
        )
    grid = np.flipud(grid)  # Raster north-first -> scene south-first.
    reference = float(grid[resolution // 2, resolution // 2])
    local = np.round(grid - reference, 3)
    x, y = np.meshgrid(
        np.linspace(b.min_x, b.max_x, resolution),
        np.linspace(b.min_y, b.max_y, resolution),
    )
    boundary = scene.metadata.selection_boundary
    mask = intersects_xy(Polygon(boundary.exterior, boundary.holes), x, y)
    logger.info(
        "Terrain %dx%d, elevation reference %.3f m, local range %.3f..%.3f m",
        resolution,
        resolution,
        reference,
        local.min(),
        local.max(),
    )
    return TerrainData(
        resolution_x=resolution,
        resolution_y=resolution,
        origin=(b.min_x, b.min_y, 0),
        cell_size=(dx, dy),
        heights=local.ravel().tolist(),
        valid_mask=mask.ravel().tolist(),
        min_height=float(local.min()),
        max_height=float(local.max()),
        height_offset_m=reference,
        vertical_datum="EGM2008" if source_urls else "unspecified",
        source=(
            "Copernicus DEM GLO-30"
            if source_urls
            else "Local DEM (verify vertical datum)"
        ),
        source_urls=source_urls or [],
        attribution=ATTRIBUTION if source_urls else "User supplied raster",
    )


def planetary_tile(latitude: int, longitude: int, cache: Path) -> tuple[Path, str]:
    """Public Copernicus mirror; never persist short-lived anonymous access tokens."""
    name = Path(urlsplit(tile_url(latitude, longitude)).path).stem
    metadata_path = cache / (name + ".source.json")
    cached = cache / (name + ".tif")
    if cached.is_file() and metadata_path.is_file():
        return cached, json.loads(metadata_path.read_text(encoding="utf-8"))["source"]
    endpoint = "https://planetarycomputer.microsoft.com/api/"
    with urlopen(
        endpoint + "stac/v1/collections/cop-dem-glo-30/items/" + name, timeout=30
    ) as response:
        source = json.load(response)["assets"]["data"]["href"]
    cache.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps({"source": source}), encoding="utf-8")
    cached = cache / Path(urlsplit(source).path).name
    if cached.is_file():
        return cached, source
    with urlopen(
        endpoint + "sas/v1/sign?" + urlencode({"href": source}), timeout=30
    ) as response:
        signed = json.load(response)["href"]
    return download_tile(signed, cache), source


def add_elevation(
    scene: WorldScene, resolution: int = 129, provider: str = "planetary"
) -> WorldScene:
    """Attach real DEM data without changing footprints, roads or metadata axes."""
    b = scene.bounds
    inverse = Transformer.from_crs(scene.metadata.crs, 4326, always_xy=True)
    west, south, east, north = inverse.transform_bounds(
        b.min_x + scene.origin.easting,
        b.min_y + scene.origin.northing,
        b.max_x + scene.origin.easting,
        b.max_y + scene.origin.northing,
        densify_pts=21,
    )
    indices = [
        (lat, lon)
        for lat in range(math.floor(south), math.floor(north) + 1)
        for lon in range(math.floor(west), math.floor(east) + 1)
    ]
    cache = PROJECT_ROOT / "data" / "dem"
    if provider == "planetary":
        tiles = [planetary_tile(lat, lon, cache) for lat, lon in indices]
        paths, urls = [t[0] for t in tiles], [t[1] for t in tiles]
    elif provider == "aws":
        urls = [tile_url(lat, lon) for lat, lon in indices]
        paths = [download_tile(url, cache) for url in urls]
    else:
        raise ValueError("Unknown DEM provider")
    scene.terrain = build_terrain(scene, paths, resolution, urls)
    return scene


def main() -> int:
    """Enrich an existing scene, without downloading OSM again."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=129)
    parser.add_argument(
        "--dem",
        type=Path,
        nargs="+",
        help="Optional local rasters instead of Copernicus",
    )
    parser.add_argument(
        "--dem-provider", choices=["planetary", "aws"], default="planetary"
    )
    args = parser.parse_args()
    configure_logging()
    try:
        scene = WorldScene.model_validate_json(args.scene.read_text(encoding="utf-8"))
        if args.dem:
            scene.terrain = build_terrain(scene, args.dem, args.resolution)
        else:
            add_elevation(scene, args.resolution, args.dem_provider)
        export_json(scene, args.output)
        return 0
    except Exception as exc:
        logger.error("Elevation generation failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
