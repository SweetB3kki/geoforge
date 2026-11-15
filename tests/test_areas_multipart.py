import geopandas as gpd
import pytest
from shapely import affinity
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import transform

from app.gis.processing import area_type, build_scene


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"natural": "water"}, "water"),
        ({"water": "lake"}, "water"),
        ({"landuse": "reservoir"}, "water"),
        ({"water": "no"}, None),
        ({"leisure": "park"}, "green"),
        ({"landuse": "grass"}, "green"),
        ({"natural": "wood"}, "green"),
        ({"landuse": "industrial"}, None),
        ({"water": "pond", "leisure": "park"}, "water"),
    ],
)
def test_classification(tags, expected):
    assert area_type(tags) == expected


def test_multipart_and_repair(frame, tmp_path):
    from app.visualization.preview import render_preview

    rows = [
        {
            "building": "yes",
            "geometry": MultiPolygon(
                [box(-100, -100, -80, -80), box(80, 80, 100, 100)]
            ),
        },
        {
            "highway": "primary",
            "geometry": MultiLineString([[(-600, 0), (600, 0)], [(0, -600), (0, 600)]]),
        },
        {
            "natural": "water",
            "geometry": MultiPolygon(
                [box(-200, -200, -150, -150), box(150, 150, 200, 200)]
            ),
        },
        {
            "leisure": "park",
            "geometry": GeometryCollection([box(-300, 100, -200, 200), Point(1, 1)]),
        },
        {
            "building": "yes",
            "geometry": Polygon([(10, 10), (30, 30), (10, 30), (30, 10), (10, 10)]),
        },
        {"highway": "bus_stop", "geometry": Point(0, 0)},
        {"highway": "pedestrian", "area": "yes", "geometry": box(50, 50, 60, 60)},
        {"natural": "water", "geometry": LineString([(1, 1), (2, 2)])},
    ]
    for row in rows:
        row["geometry"] = transform(
            frame.inverse.transform,
            affinity.translate(row["geometry"], frame.easting, frame.northing),
        )
    scene = build_scene(gpd.GeoDataFrame(rows, crs=4326), frame)
    assert len(scene.buildings) == 4
    assert len(scene.roads) == 4  # Crossing is split by GEOS intersection.
    assert len(scene.water_areas) == 2
    assert len(scene.green_areas) == 1
    assert scene.metadata.repaired_features == 1
    assert scene.metadata.skipped_features == 0
    ids = [
        item.id
        for items in [
            scene.buildings,
            scene.roads,
            scene.water_areas,
            scene.green_areas,
        ]
        for item in items
    ]
    assert len(ids) == len(set(ids))
    assert render_preview(scene, tmp_path / "areas.png").is_file()
