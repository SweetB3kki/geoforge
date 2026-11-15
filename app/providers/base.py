"""Provider boundary. Empty coverage and failed acquisition are distinct results."""

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Protocol

import geopandas as gpd

BBox = tuple[float, float, float, float]


def validate_bbox(bbox: BBox) -> None:
    if len(bbox) != 4 or not all(isfinite(v) for v in bbox):
        raise ValueError("Expected four finite bbox coordinates")
    w, s, e, n = bbox
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("Expected WGS84 west < east and south < north")
    if e - w > 2 or n - s > 1:
        raise ValueError("Provider requests must be local (at most 2 x 1 degrees)")


class ProviderStatus(StrEnum):
    SUCCESS = "success"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


@dataclass
class ProviderResult:
    provider: str
    release: str | None
    feature_type: str
    status: ProviderStatus
    features: gpd.GeoDataFrame = field(
        default_factory=lambda: gpd.GeoDataFrame(geometry=[], crs=4326)
    )
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    download_time: float = 0.0
    # None means not observable through the upstream client, never zero traffic.
    bytes_transferred: int | None = None
    cache_hit: bool | None = False
    metadata: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "provider": self.provider,
            "release": self.release,
            "feature_type": self.feature_type,
            "status": self.status.value,
            "feature_count": len(self.features),
            "warnings": self.warnings,
            "errors": self.errors,
            "download_time": self.download_time,
            "bytes_transferred": self.bytes_transferred,
            "cache_hit": self.cache_hit,
            "metadata": self.metadata,
        }


class DataProvider(Protocol):
    def fetch(self, bbox: BBox, feature_type: str) -> ProviderResult: ...
