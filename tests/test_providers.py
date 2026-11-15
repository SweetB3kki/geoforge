"""Offline provider contracts, pinned releases, corruption recovery and fallback."""

import io
import json
import subprocess

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from app.providers.base import ProviderStatus, validate_bbox
from app.providers.cache import CacheError, ProviderCache
from app.providers.manager import DataMode, DataSourceManager
from app.providers.osm import OSMDataProvider
from app.providers.overture import OvertureProvider, decode_features, run_query
from app.providers.overture_catalog import (
    OvertureCatalog,
    resolve_release,
    select_assets,
)

BBOX = (10.0, 20.0, 10.01, 20.01)
RELEASE = "2026-09-23.1"


def payload(rows=None):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    rows = (
        rows
        if rows is not None
        else [
            {
                "id": "b1",
                "geometry": box(10, 20, 10.005, 20.005).wkb,
                "height": 12.5,
                "sources": [{"dataset": "OpenStreetMap", "record_id": "w1@2"}],
            }
        ]
    )
    out = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), out)
    return out.getvalue()


class CatalogStub:
    def __init__(self, release=RELEASE, paths=None):
        self.value = release
        self.paths = ["https://example.test/part.parquet"] if paths is None else paths
        self.warnings = []
        self.download_bytes = 0
        self.queries = 0

    def release(self):
        return self.value, f"https://stac.overturemaps.org/{self.value}/catalog.json"

    def query(self, *args):
        self.queries += 1
        return {
            "paths": self.paths,
            "warnings": ["index fallback"],
            "backend": "duckdb",
            "license": "ODbL-1.0",
        }


def no_network(*args, **kwargs):
    raise AssertionError("Network/query must not be called")


@pytest.mark.parametrize(
    "bbox", [(1, 2, 0, 3), (1, 2, 1, 3), (0, 0, 180, 90), (1, 2, float("nan"), 3)]
)
def test_bbox_rejects_unbounded_and_invalid(bbox):
    with pytest.raises(ValueError):
        validate_bbox(bbox)


@pytest.mark.parametrize("absolute", [False, True])
def test_latest_release_uses_catalog_not_maximum_or_constant(absolute):
    href = f"./{RELEASE}/catalog.json"
    if absolute:
        href = f"https://stac.overturemaps.org/{RELEASE}/catalog.json"
    assert resolve_release(
        {"latest": RELEASE, "links": [{"rel": "child", "href": href}]}
    ) == (RELEASE, f"https://stac.overturemaps.org/{RELEASE}/catalog.json")
    with pytest.raises(ValueError):
        resolve_release({"latest": RELEASE, "links": []})


def test_release_pin_is_offline_until_refresh(tmp_path):
    cache = ProviderCache(tmp_path)

    def document(release):
        return json.dumps(
            {
                "latest": release,
                "links": [{"rel": "child", "href": f"./{release}/catalog.json"}],
            }
        ).encode()

    old = OvertureCatalog(cache, get=lambda url: document(RELEASE))
    assert old.release()[0] == RELEASE
    offline = OvertureCatalog(cache, get=no_network)
    assert offline.release()[0] == RELEASE
    fresh = OvertureCatalog(
        cache, refresh=True, get=lambda url: document("2026-10-21.0")
    )
    assert fresh.release()[0] == "2026-10-21.0"


def test_catalog_malformed_latest_is_not_pinned(tmp_path):
    catalog = OvertureCatalog(ProviderCache(tmp_path), get=lambda url: b"{}")
    with pytest.raises(ValueError):
        catalog.release()
    assert not list(tmp_path.glob("*.bin"))


def asset(kind="water", collection=None, bbox=None):
    return {
        "type": "Feature",
        "collection": collection,
        "bbox": bbox or dict(zip(["xmin", "ymin", "xmax", "ymax"], BBOX, strict=True)),
        "assets": {
            "aws": {
                "href": f"https://example.test/release/{RELEASE}/theme=base/type={kind}/part.parquet"
            }
        },
    }


def test_null_collection_index_selects_only_published_intersecting_type():
    urls, warnings = select_assets(
        [
            asset(),
            asset("land"),
            asset(bbox={"xmin": 50, "ymin": 60, "xmax": 51, "ymax": 61}),
        ],
        "water",
        BBOX,
        RELEASE,
    )
    assert len(urls) == 1 and "/type=water/" in urls[0]
    assert warnings and "stac_collection_null" in warnings[0]
    assert select_assets([asset(collection="water")], "water", BBOX, RELEASE)[1] == []
    with pytest.raises(ValueError):
        select_assets([asset(collection="building")], "water", BBOX, RELEASE)


def test_cache_identity_and_checksum(tmp_path):
    cache = ProviderCache(tmp_path)
    identity = {
        "provider": "overture",
        "release": RELEASE,
        "bbox": BBOX,
        "feature_type": "water",
        "options": {"mode": "full"},
    }
    cache.write(identity, b"data", {"license": "ODbL-1.0"})
    assert cache.read(identity)[0] == b"data"
    for field, value in [
        ("release", "different"),
        ("bbox", (1, 2, 3, 4)),
        ("feature_type", "building"),
        ("options", {"mode": "other"}),
    ]:
        assert cache.read({**identity, field: value}) is None
    cache.paths(identity)[0].write_bytes(b"tampered")
    with pytest.raises(CacheError):
        cache.read(identity)


def test_cold_then_offline_cache_preserves_nested_attributes(tmp_path):
    catalog = CatalogStub()
    cold = OvertureProvider(
        tmp_path,
        catalog=catalog,
        query_runner=lambda *args: (payload(), {"query_seconds": 0.1}),
    )
    result = cold.fetch(BBOX, "building")
    assert result.status == ProviderStatus.SUCCESS
    assert result.bytes_transferred is None and not result.cache_hit
    warm = OvertureProvider(tmp_path, catalog=CatalogStub(), query_runner=no_network)
    hit = warm.fetch(BBOX, "building")
    assert hit.cache_hit and hit.bytes_transferred == 0 and hit.download_time == 0
    assert hit.features.iloc[0]["height"] == 12.5
    assert hit.features.iloc[0]["sources"][0]["record_id"] == "w1@2"
    assert "index fallback" in hit.warnings
    assert warm.catalog.queries == 0


def test_empty_spatial_coverage_is_cached_and_not_a_failure(tmp_path):
    provider = OvertureProvider(
        tmp_path, catalog=CatalogStub(paths=[]), query_runner=no_network
    )
    empty = provider.fetch(BBOX, "water")
    assert empty.status == ProviderStatus.EMPTY and not empty.errors
    provider = OvertureProvider(
        tmp_path, catalog=CatalogStub(), query_runner=no_network
    )
    assert provider.fetch(BBOX, "water").cache_hit


def test_query_failure_is_unavailable_and_never_cached_as_empty(tmp_path):
    def fail(*args):
        raise TimeoutError("offline")

    provider = OvertureProvider(tmp_path, catalog=CatalogStub(), query_runner=fail)
    failed = provider.fetch(BBOX, "building")
    assert failed.status == ProviderStatus.UNAVAILABLE and failed.errors
    assert not list(tmp_path.glob("*.bin"))


def test_corrupt_cache_is_refetched_with_warning(tmp_path):
    provider = OvertureProvider(
        tmp_path, catalog=CatalogStub(), query_runner=lambda *args: (payload(), {})
    )
    provider.fetch(BBOX, "building")
    next(tmp_path.glob("*.bin")).write_bytes(b"bad checksum")
    recovered = provider.fetch(BBOX, "building")
    assert recovered.status == ProviderStatus.SUCCESS and not recovered.cache_hit
    assert any("checksum" in w for w in recovered.warnings)


@pytest.mark.parametrize("options", [{"refresh": True}, {"use_cache": False}])
def test_refresh_and_no_cache_bypass_existing_extract(tmp_path, options):
    calls = []

    def query(*args):
        calls.append(1)
        return payload(), {}

    OvertureProvider(tmp_path, catalog=CatalogStub(), query_runner=query).fetch(
        BBOX, "building"
    )
    second = OvertureProvider(
        tmp_path, catalog=CatalogStub(), query_runner=query, **options
    )
    assert not second.fetch(BBOX, "building").cache_hit
    assert len(calls) == 2


def test_decode_removes_bbox_false_positives_and_preserves_ocean_covering_bbox():
    data = payload(
        [
            {"id": "outside", "geometry": Point(30, 40).wkb},
            {"id": "ocean", "geometry": box(9, 19, 11, 21).wkb},
        ]
    )
    assert decode_features(data, BBOX)["id"].tolist() == ["ocean"]


def test_decode_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate"):
        decode_features(payload([{"id": "a", "geometry": Point(10, 20).wkb}] * 2), BBOX)


def test_worker_timeout_is_enforced(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 0.01
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        run_query({}, 0.01)


def test_osm_adapter_preserves_original_frame_and_failure(features, frame):
    class Source:
        def fetch(self, bbox):
            return features

    result = OSMDataProvider(Source()).fetch(frame.bbox)
    assert result.features is features and result.status == ProviderStatus.SUCCESS
    assert result.cache_hit is None and result.release is None

    class Failed:
        def fetch(self, bbox):
            raise RuntimeError("offline")

    assert (
        OSMDataProvider(Failed()).fetch(frame.bbox).status == ProviderStatus.UNAVAILABLE
    )


def test_manager_osm_only_never_calls_overture_and_auto_keeps_osm(tmp_path):
    class Source:
        def fetch(self, bbox):
            return gpd.GeoDataFrame(geometry=[Point(10, 20)], crs=4326)

    extra = OvertureProvider(tmp_path, catalog=CatalogStub(), query_runner=no_network)
    manager = DataSourceManager(OSMDataProvider(Source()), extra)
    only = manager.fetch(BBOX, DataMode.OSM_ONLY)
    assert only.overture == {} and extra.catalog.queries == 0
    auto = manager.fetch(BBOX)
    assert auto.osm.status == ProviderStatus.SUCCESS
    assert len(auto.overture) == 5
    assert all(r.status == ProviderStatus.UNAVAILABLE for r in auto.overture.values())


def test_elevation_adapter_uses_existing_tile_cache(monkeypatch, tmp_path):
    from app.providers.elevation import CopernicusElevationProvider

    calls = []

    def tile(lat, lon, cache):
        calls.append((lat, lon))
        return tmp_path / "tile.tif", "https://example.test/copernicus.tif"

    monkeypatch.setattr("app.providers.elevation.planetary_tile", tile)
    result = CopernicusElevationProvider().fetch(BBOX)
    assert result.status == ProviderStatus.SUCCESS and calls == [(20, 10)]
    assert result.metadata["vertical_datum"] == "EGM2008"
    assert result.features.iloc[0]["source_url"].endswith("copernicus.tif")


def test_manager_guards_unexpected_optional_provider_exceptions():
    class Broken:
        def fetch(self, *args):
            raise RuntimeError("unexpected provider failure")

    class EmptyOSM:
        def fetch(self, bbox):
            return gpd.GeoDataFrame(geometry=[], crs=4326)

    result = DataSourceManager(OSMDataProvider(EmptyOSM()), Broken()).fetch(BBOX)
    assert result.osm.status == ProviderStatus.EMPTY
    assert all(r.errors for r in result.overture.values())


def test_probe_empty_selection_has_zero_field_coverage(frame):
    from app.providers.base import ProviderResult
    from app.validation.provider_probe import coverage

    result = ProviderResult(
        "overture", RELEASE, "building_part", ProviderStatus.SUCCESS
    )
    result.features = gpd.GeoDataFrame(
        {"id": ["outside"], "height": [12.0]}, geometry=[Point(0, 0)], crs=4326
    )
    profile = coverage(result, frame)
    assert profile["selection_count"] == 0 and profile["non_null"]["id"] == 0


@pytest.mark.integration
def test_live_overture_water_and_repeat_cache(tmp_path):
    pytest.importorskip("overturemaps")
    from app.gis.coordinates import CenterSelection, LocalFrame

    frame = LocalFrame(CenterSelection(latitude=44.6, longitude=33.5, radius_m=500))
    provider = OvertureProvider(tmp_path)
    first = provider.fetch(frame.bbox, "water")
    assert first.status == ProviderStatus.SUCCESS, first.errors
    assert (first.features["subtype"] == "ocean").any()
    second = OvertureProvider(tmp_path, query_runner=no_network).fetch(
        frame.bbox, "water"
    )
    assert second.cache_hit and second.release == first.release
    assert second.features["id"].tolist() == first.features["id"].tolist()
