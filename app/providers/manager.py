"""Acquire sources independently; failure of enrichment never discards OSM."""

from dataclasses import dataclass
from enum import StrEnum

from app.providers.base import BBox, DataProvider, ProviderResult, ProviderStatus
from app.providers.osm import OSMDataProvider
from app.providers.overture import OvertureProvider
from app.providers.overture_catalog import THEMES


class DataMode(StrEnum):
    OSM_ONLY = "osm-only"
    AUTO = "auto"


@dataclass
class SourceBundle:
    osm: ProviderResult
    overture: dict[str, ProviderResult]

    def summaries(self) -> list[dict]:
        return [self.osm.summary(), *(r.summary() for r in self.overture.values())]


class DataSourceManager:
    def __init__(
        self, osm: DataProvider | None = None, overture: DataProvider | None = None
    ):
        self.osm = osm or OSMDataProvider()
        self.overture = overture or OvertureProvider()

    def fetch(self, bbox: BBox, mode: DataMode = DataMode.AUTO) -> SourceBundle:
        mode = DataMode(mode)
        osm = self.osm.fetch(bbox, "features")
        extra = {}
        if mode == DataMode.AUTO:
            for kind in THEMES:
                try:
                    extra[kind] = self.overture.fetch(bbox, kind)
                except Exception as exc:
                    extra[kind] = ProviderResult(
                        "overture",
                        None,
                        kind,
                        ProviderStatus.UNAVAILABLE,
                        errors=[f"{type(exc).__name__}: {exc}"],
                    )
        return SourceBundle(osm, extra)
