"""OpenStreetMap feature provider; network errors are not empty scenes."""

import logging
from threading import Lock
from typing import Protocol

import geopandas as gpd
import osmnx as ox
from osmnx._errors import InsufficientResponseError

from app.core.config import CACHE_DIR, OSM_TAGS

logger = logging.getLogger(__name__)
_FETCH_LOCK = Lock()


class DownloadError(RuntimeError):
    """OSM service could not supply usable data."""


class FeatureProvider(Protocol):
    def fetch(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        # OSMnx temporarily changes process-wide DNS state during Overpass calls.
        with _FETCH_LOCK:
            return self._fetch(bbox)

    def _fetch(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        """Return WGS84 features indexed by OSM element type and id."""
        ...


class OSMProvider:
    """Fetch all requested categories in one cached Overpass query."""

    def fetch(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        logger.info("Starting OSM download, bbox=%s", bbox)
        ox.settings.use_cache = True
        ox.settings.cache_folder = str(CACHE_DIR)
        ox.settings.requests_timeout = 90
        ox.settings.log_console = False
        try:
            result = ox.features_from_bbox(bbox, tags=OSM_TAGS)
        except InsufficientResponseError as exc:
            # OSMnx uses the same exception for empty features and invalid replies.
            if "No matching features" not in str(exc):
                raise DownloadError(f"Invalid OSM response: {exc}") from exc
            logger.info("OSM returned no matching features")
            result = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        except Exception as exc:
            raise DownloadError(f"OSM download failed: {exc}") from exc
        logger.info("Received %d OSM features", len(result))
        return result
