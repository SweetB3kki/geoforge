"""Small deterministic WGS84 dataset; no network required."""

import geopandas as gpd
import pytest
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.ops import transform

from app.gis.coordinates import CenterSelection, LocalFrame


@pytest.fixture
def selection():
    return CenterSelection(latitude=44.6, longitude=33.5, radius_m=500)


@pytest.fixture
def frame(selection):
    return LocalFrame(selection)


@pytest.fixture
def features(frame):
    local_geometries = [
        Polygon(
            [(-50, -50), (50, -50), (50, 50), (-50, 50)],
            [[(-10, -10), (-10, 10), (10, 10), (10, -10)]],
        ),
        LineString([(-600, 100), (600, 100)]),
    ]
    geometries = [
        transform(
            frame.inverse.transform,
            affinity.translate(g, frame.easting, frame.northing),
        )
        for g in local_geometries
    ]
    return gpd.GeoDataFrame(
        [
            {
                "building": "apartments",
                "building:levels": "4",
                "geometry": geometries[0],
            },
            {"highway": "residential", "geometry": geometries[1]},
        ],
        crs=4326,
    )


class StaticProvider:
    def __init__(self, features):
        self.features = features

    def fetch(self, bbox):
        return self.features.copy()
