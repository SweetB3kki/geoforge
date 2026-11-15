import pytest
from pydantic import ValidationError
from pyproj import Geod
from shapely.geometry import Point

from app.gis.coordinates import BBoxSelection, CenterSelection, LocalFrame


def test_center_is_zero(frame):
    point = frame.to_local(Point(33.5, 44.6))
    assert (point.x, point.y) == pytest.approx((0, 0), abs=1e-6)
    assert frame.crs.to_epsg() == 32636
    assert frame.bounds.min_x == -500


def test_metric_scale_and_axes(frame):
    lon, lat, _ = Geod(ellps="WGS84").fwd(33.5, 44.6, 90, 100)
    point = frame.to_local(Point(lon, lat))
    assert point.x == pytest.approx(100, abs=0.1)
    assert point.y == pytest.approx(0, abs=1)


def test_southern_hemisphere():
    frame = LocalFrame(CenterSelection(latitude=-33.9, longitude=151.2, radius_m=200))
    assert frame.crs.to_epsg() == 32756


def test_bbox():
    frame = LocalFrame(BBoxSelection(west=33.49, south=44.59, east=33.51, north=44.61))
    assert frame.boundary.contains(Point(0, 0))


@pytest.mark.parametrize("radius", [0, -1, 10_001, float("nan"), float("inf")])
def test_bad_radius(radius):
    with pytest.raises(ValidationError):
        CenterSelection(latitude=44.6, longitude=33.5, radius_m=radius)


def test_cross_dateline_rejected():
    with pytest.raises(ValueError, match="dateline"):
        LocalFrame(CenterSelection(latitude=0, longitude=179.999, radius_m=500))


def test_large_bbox_rejected():
    with pytest.raises(ValueError, match="20 km"):
        LocalFrame(BBoxSelection(west=33, south=44, east=34, north=44.5))
