"""Pinned STAC discovery and spatial asset selection, including null collection IDs."""

import io
import json
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

from app.providers.base import BBox
from app.providers.cache import CacheError, ProviderCache

CATALOG_URL = "https://stac.overturemaps.org/catalog.json"
THEMES = {
    "building": "buildings",
    "building_part": "buildings",
    "segment": "transportation",
    "connector": "transportation",
    "water": "base",
}


def resolve_release(catalog: dict, url: str = CATALOG_URL) -> tuple[str, str]:
    release = catalog.get("latest")
    if not isinstance(release, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}\.\d+", release
    ):
        raise ValueError("STAC latest release is missing or unsupported")
    for link in catalog.get("links", []):
        href = urljoin(url, link.get("href", ""))
        if link.get("rel") == "child" and urlsplit(href).path.rstrip("/").endswith(
            f"/{release}/catalog.json"
        ):
            return release, href
    raise ValueError("STAC latest release has no matching child catalog")


def select_assets(items: list[dict], kind: str, bbox: BBox, release: str):
    """Use published Hive partitions when STAC collection IDs are null."""
    w, s, e, n = bbox
    selected, warnings = [], []
    partition = f"/release/{release}/theme={THEMES[kind]}/type={kind}/"
    for item in items:
        if item.get("type") != "Feature":
            continue
        asset = item.get("assets", {}).get("aws", {})
        href = asset.get("href", "")
        if partition not in urlsplit(href).path:
            continue
        collection = item.get("collection")
        if collection not in (None, kind):
            raise ValueError("STAC collection disagrees with published asset partition")
        b = item["bbox"]
        if b["xmin"] <= e and b["xmax"] >= w and b["ymin"] <= n and b["ymax"] >= s:
            if collection is None:
                warnings.append(
                    "stac_collection_null: selected by published asset partition"
                )
            selected.append(href)
    return sorted(set(selected)), sorted(set(warnings))


class OvertureCatalog:
    def __init__(
        self, cache: ProviderCache, *, refresh=False, use_cache=True, get=None
    ):
        self.cache, self.refresh, self.use_cache = cache, refresh, use_cache
        self.get = get or self._download
        self.warnings: list[str] = []
        self.download_bytes = 0
        self._documents: dict[str, bytes] = {}

    @staticmethod
    def _download(url: str) -> bytes:
        with urlopen(url, timeout=30) as response:
            data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024:
            raise ValueError("STAC metadata exceeds 64 MiB limit")
        return data

    def document(self, url: str, release: str) -> bytes:
        if url in self._documents:
            return self._documents[url]
        identity = {
            "provider": "overture",
            "release": release,
            "url": url,
            "feature_type": "catalog",
            "format": 1,
        }
        cached = None
        if self.use_cache and not self.refresh:
            try:
                cached = self.cache.read(identity)
            except CacheError as exc:
                self.warnings.append(str(exc))
        if cached is not None:
            data = cached[0]
        else:
            data = self.get(url)
            self.download_bytes += len(data)
            # Validate structured catalogs before pinning them.
            if url == CATALOG_URL:
                resolve_release(json.loads(data), url)
            elif url.endswith(".json"):
                json.loads(data)
            if self.use_cache:
                try:
                    self.cache.write(identity, data, {"source_url": url})
                except OSError as exc:
                    self.warnings.append(f"catalog_cache_write_failed: {exc}")
        self._documents[url] = data
        return data

    def release(self) -> tuple[str, str]:
        return resolve_release(json.loads(self.document(CATALOG_URL, "pinned")))

    def query(self, kind: str, bbox: BBox, release: str, catalog_url: str) -> dict:
        import pyarrow.parquet as pq

        index_url = urljoin(catalog_url, "collections.parquet")
        index = pq.read_table(io.BytesIO(self.document(index_url, release)))
        paths, warnings = select_assets(index.to_pylist(), kind, bbox, release)
        # Read the published per-type collection for license and available columns.
        collection_url = urljoin(catalog_url, f"{THEMES[kind]}/{kind}/collection.json")
        collection = json.loads(self.document(collection_url, release))
        if collection.get("id") != kind:
            raise ValueError("Unexpected STAC collection ID")
        if not paths and collection.get("partition:file_count", 0) > 0:
            # No spatial assets is valid only if this index actually includes the type.
            prefix = f"/theme={THEMES[kind]}/type={kind}/"
            if not any(
                prefix in r.get("assets", {}).get("aws", {}).get("href", "")
                for r in index.to_pylist()
            ):
                raise ValueError("STAC index is missing the requested collection")
        return {
            "paths": paths,
            "warnings": warnings,
            "backend": "duckdb" if warnings else "overturemaps",
            "catalog_url": catalog_url,
            "index_url": index_url,
            "collection_url": collection_url,
            "license": collection.get("license", "unknown"),
            "available_columns": [
                c["name"] for c in collection.get("table:columns", [])
            ],
        }
