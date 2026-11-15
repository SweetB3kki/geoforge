"""Command-line interface: python -m app.cli --lat ... --lon ... --radius ..."""

import argparse
import json
import logging
from pathlib import Path

from app.core.config import OUTPUT_DIR, configure_logging
from app.gis.coordinates import BBoxSelection, CenterSelection
from app.services.generation import generate


def main() -> int:
    """Generate a scene and return a nonzero exit code on failure."""
    parser = argparse.ArgumentParser(
        description="Generate a local scene from OpenStreetMap"
    )
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument(
        "--radius", type=float, help="Selection radius in meters (max 10000)"
    )
    parser.add_argument(
        "--bbox", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH")
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--data-mode", choices=["osm-only", "auto"], default="osm-only")
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Refresh Overture release and extracts",
    )
    parser.add_argument("--no-cache", action="store_true", help="Bypass Overture cache")
    parser.add_argument(
        "--supplemental-overture-roads",
        choices=["auto", "off"],
        default="auto",
        help="AUTO adds supported isolated segments after dedup validation",
    )
    parser.add_argument(
        "--elevation", action="store_true", help="Attach real Copernicus GLO-30 DEM"
    )
    parser.add_argument(
        "--terrain-resolution", type=int, choices=[33, 65, 129, 257, 513], default=129
    )
    args = parser.parse_args()
    configure_logging(args.verbose)
    center_values = (args.lat, args.lon, args.radius)
    if args.bbox is not None and any(v is not None for v in center_values):
        parser.error("Use either --bbox or --lat, --lon, --radius")
    if args.bbox is None and not all(v is not None for v in center_values):
        parser.error("Supply --lat, --lon and --radius, or --bbox")
    try:
        selection = (
            BBoxSelection(
                **dict(zip(("west", "south", "east", "north"), args.bbox, strict=True))
            )
            if args.bbox
            else CenterSelection(
                latitude=args.lat, longitude=args.lon, radius_m=args.radius
            )
        )
        from app.fusion.transportation import TransportSettings

        result = generate(
            selection,
            args.output_dir,
            elevation=args.elevation,
            terrain_resolution=args.terrain_resolution,
            data_mode=args.data_mode,
            refresh_data=args.refresh_data,
            use_cache=not args.no_cache,
            transport_settings=TransportSettings(
                enableSupplementalOvertureRoads=args.supplemental_overture_roads
            ),
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "buildings": len(result.scene.buildings),
                    "roads": len(result.scene.roads),
                    "water_areas": len(result.scene.water_areas),
                    "green_areas": len(result.scene.green_areas),
                    "scene_path": str(result.scene_path),
                    "preview_path": str(result.preview_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        logging.getLogger(__name__).error(
            "Generation failed: %s", exc, exc_info=args.verbose
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
