"""Minimal adapter retaining OSMnx queries, source indices, tags and cache."""

from time import perf_counter

from app.gis.input import FeatureProvider, OSMProvider
from app.providers.base import BBox, ProviderResult, ProviderStatus, validate_bbox


class OSMDataProvider:
    def __init__(self, provider: FeatureProvider | None = None):
        self.provider = provider or OSMProvider()

    def fetch(self, bbox: BBox, feature_type: str = "features") -> ProviderResult:
        validate_bbox(bbox)
        if feature_type != "features":
            raise ValueError("OSM adapter fetches the existing combined feature query")
        start = perf_counter()
        result = ProviderResult(
            provider="osm",
            release=None,
            feature_type=feature_type,
            status=ProviderStatus.UNAVAILABLE,
            cache_hit=None,
            metadata={
                "bbox": list(bbox),
                "license": "ODbL-1.0",
                "attribution": "© OpenStreetMap contributors",
                "attribution_url": "https://www.openstreetmap.org/copyright",
                "cache_policy": "existing OSMnx request cache",
                "metrics_note": "OSMnx cache hits and network bytes are not exposed",
                "release_note": "Live/cached Overpass query; no dataset release ID",
            },
        )
        try:
            result.features = self.provider.fetch(bbox)
            result.status = (
                ProviderStatus.EMPTY
                if result.features.empty
                else ProviderStatus.SUCCESS
            )
        except Exception as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
        result.download_time = perf_counter() - start
        return result
