import pytest

from app.gis.processing import building_height, road_width


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"height": "12", "building:levels": "10"}, 12),
        ({"height": "12.5 m"}, 12.5),
        ({"height": "10 ft"}, 3.048),
        ({"height": "7,5"}, 7.5),
        ({"building:levels": "4"}, 12),
        ({"height": "bad", "building:levels": "2"}, 6),
        ({"height": "-1", "building:levels": "0"}, 9),
        ({"height": "NaN"}, 9),
        ({"height": "inf"}, 9),
        ({}, 9),
    ],
)
def test_height(tags, expected):
    assert building_height(tags) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("motorway", 12),
        ("primary", 10),
        ("secondary", 8),
        ("residential", 6),
        ("service", 4),
        ("footway", 5),
    ],
)
def test_width(kind, expected):
    assert road_width(kind) == expected
