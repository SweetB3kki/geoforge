"""Processing rules and project paths."""

import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
DEFAULT_BUILDING_HEIGHT = 9.0
LEVEL_HEIGHT = 3.0
DEFAULT_ROAD_WIDTH = 5.0
ROAD_WIDTHS = {
    "motorway": 12.0,
    "primary": 10.0,
    "secondary": 8.0,
    "residential": 6.0,
    "service": 4.0,
}
WATER_RULES = {
    "natural": {"water"},
    "landuse": {"reservoir", "basin"},
    "waterway": {"riverbank"},
}
GREEN_RULES = {
    "leisure": {"park", "garden", "nature_reserve"},
    "landuse": {
        "grass",
        "forest",
        "meadow",
        "recreation_ground",
        "village_green",
        "orchard",
    },
    "natural": {"wood", "grassland", "scrub", "heath"},
}
OSM_TAGS: dict[str, bool | list[str]] = {
    "building": True,
    "highway": True,
    "water": True,
    **{
        key: sorted(WATER_RULES.get(key, set()) | GREEN_RULES.get(key, set()))
        for key in sorted(WATER_RULES.keys() | GREEN_RULES.keys())
    },
}
# Diagnostic source inventory; these do not imply sea reconstruction or new geometry.
OSM_TAGS["natural"] = sorted(set(OSM_TAGS["natural"]) | {"coastline"})
OSM_TAGS["waterway"] = True
OSM_TAGS["building:part"] = True


def configure_logging(verbose: bool = False) -> None:
    """Configure human-readable logs on stderr for CLI and API."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
