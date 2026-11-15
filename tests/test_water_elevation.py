from types import SimpleNamespace

import pytest
from shapely.geometry import box

from app.fusion.water_elevation import resolve_water_elevations, robust_level
from app.gis.coordinates import polygon_model
from app.models.scene import Area, AreaType


def test_ocean_datum_ignores_cliffs_and_interior_dsm():
    assert robust_level("ocean", [20, 80, 400], [900], "EGM2008", 32)[:2] == (
        -32,
        "sea_level_datum",
    )


@pytest.mark.parametrize(
    "kind", ["river", "lake", "pond", "reservoir", "water", "ocean"]
)
def test_robust_water_rejects_high_objects_and_cannot_flood_sampled_shore(kind):
    level, method, warnings = robust_level(kind, [3] * 20 + [100], [1000] * 10)
    assert level == pytest.approx(3)
    assert method != "polygon_median"
    assert "high_shoreline_DSM_outliers_rejected" in warnings


def test_missing_coast_is_not_replaced_with_interior_dsm():
    assert robust_level("ocean", [], [80])[0] is None


def test_disconnected_water_is_not_grouped_by_provider_id_alone():
    areas = [
        Area(
            id=str(i),
            area_type=AreaType.WATER,
            water_type="lake",
            polygon=polygon_model(g),
            sources=["same"],
            geometry_source="osm",
        )
        for i, g in enumerate([box(1, 1, 3, 3), box(3, 1, 5, 3), box(7, 1, 9, 3)])
    ]
    scene = SimpleNamespace(
        water_areas=areas,
        metadata=SimpleNamespace(selection_boundary=polygon_model(box(0, 0, 10, 10))),
        terrain=SimpleNamespace(
            resolution_x=11,
            resolution_y=11,
            origin=[0, 0, 0],
            cell_size=[1, 1],
            heights=[x for y in range(11) for x in range(11)],
            valid_mask=[True] * 121,
            vertical_datum="unknown",
            height_offset_m=0,
        ),
    )
    audit = resolve_water_elevations(scene, SimpleNamespace(candidates=[]))
    assert audit["waterBodiesChecked"] == 2
    assert areas[0].water_level_m == areas[1].water_level_m
    assert areas[2].water_level_m > areas[0].water_level_m
    assert scene.terrain.heights == [x for y in range(11) for x in range(11)]
