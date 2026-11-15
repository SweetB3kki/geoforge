"""Adversarial fixtures for G.5 measurement and shared-frame guarantees."""

import numpy as np
import pytest
from shapely.geometry import box

from app.fusion.normalization import normalize
from app.gis.coordinates import BBoxSelection, polygon_model
from app.validation.spatial_regression import intersections, section_hits
from tests.test_candidates import result


def test_same_source_geometry_uses_shared_provider_frame(frame):
    expected = box(37, -83, 49, -71)
    osm = result(
        frame,
        "features",
        [{"building": "yes", "geometry": expected}],
        "osm",
        [("way", 7)],
    )
    overture = result(frame, "building", [{"id": "b", "geometry": expected}])
    batch = normalize([osm, overture], frame)
    assert len(batch.candidates) == 2
    assert batch.origin_easting == frame.easting
    assert batch.origin_northing == frame.northing
    for candidate in batch.candidates:
        assert candidate.geometry.hausdorff_distance(expected) < 1e-6


def test_projected_input_cannot_be_projected_twice(frame):
    source = result(frame, "building", [{"id": "b"}])
    source.features = source.features.to_crs(frame.crs)
    with pytest.raises(ValueError, match="WGS84"):
        normalize([source], frame)


@pytest.mark.parametrize("coords", [(2, 3, 1, 4), (1, 4, 2, 3)])
def test_bbox_axis_order_rejected(coords):
    with pytest.raises(ValueError, match="west < east"):
        BBoxSelection(
            **dict(zip(["west", "south", "east", "north"], coords, strict=True))
        )


def test_swapped_lon_lat_outside_selection_is_not_admitted(frame):
    from shapely.ops import transform

    source = result(frame, "building", [{"id": "b"}])
    source.features.geometry = source.features.geometry.map(
        lambda g: transform(lambda x, y: (y, x), g)
    )
    batch = normalize([source], frame)
    assert not batch.candidates
    assert batch.diagnostics[0]["reason"] == "outside_selection"


def test_intersection_detector_preserves_island_and_ignores_touch():
    water = box(0, 0, 10, 10).difference(box(3, 3, 7, 7))

    def building(name, geometry):
        return dict(
            id=name,
            footprint=polygon_model(geometry).model_dump(),
            sources=[],
            fusion_method="fixture",
        )

    buildings = [
        building("island", box(4, 4, 6, 6)),
        building("touch", box(10, 2, 12, 4)),
        building("overlap", box(1, 1, 2, 2)),
    ]
    rows = intersections(buildings, {"lake": water})
    assert len(rows) == 1
    assert rows[0]["building"] == "overlap"
    assert rows[0]["area"] == pytest.approx(1)


def test_final_mesh_section_measures_plane_and_reports_uncovered_point():
    triangle = np.array([[[0, 0, 1], [10, 0, 3], [0, 10, 5]]], dtype=float)
    hits = section_hits(triangle, np.array([[2, 3], [20, 20]], dtype=float))
    assert hits[0] == pytest.approx(2.6)
    assert np.isneginf(hits[1])
