import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.gis.elevation import build_terrain, tile_url
from app.gis.processing import build_scene
from app.models.scene import WorldScene


def write_dem(tmp_path, scene, nodata=False):
    b = scene.bounds
    dx, dy = (b.max_x - b.min_x) / 32, (b.max_y - b.min_y) / 32
    rows, cols = np.indices((33, 33))
    values = (100 + cols * 2 + (32 - rows) * 3).astype("float32")
    if nodata:
        values[10:20, 10:20] = -9999
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=33,
        height=33,
        count=1,
        dtype="float32",
        crs=scene.metadata.crs,
        nodata=-9999,
        transform=from_origin(
            b.min_x + scene.origin.easting - dx / 2,
            b.max_y + scene.origin.northing + dy / 2,
            dx,
            dy,
        ),
    ) as raster:
        raster.write(values, 1)
    return path


def test_real_raster_reprojection_orientation_mask_and_roundtrip(
    features, frame, tmp_path
):
    scene = build_scene(features, frame)
    path = write_dem(tmp_path, scene)
    terrain = build_terrain(scene, [path], 33)
    assert terrain.height_offset_m == pytest.approx(180)
    assert terrain.heights[0] == pytest.approx(-80)
    assert terrain.heights[-1] == pytest.approx(80)
    assert terrain.heights[32] == pytest.approx(-16)
    assert terrain.valid_mask[0] is False
    assert terrain.valid_mask[16 * 33 + 16] is True
    assert terrain.vertical_datum == "unspecified"
    scene.terrain = terrain
    assert WorldScene.model_validate_json(scene.model_dump_json()) == scene


def test_missing_dem_is_explicit_error(features, frame, tmp_path):
    scene = build_scene(features, frame)
    with pytest.raises(ValueError, match="nodata"):
        build_terrain(scene, [write_dem(tmp_path, scene, True)], 33)


def test_grid_bounds_and_lengths_rejected(features, frame, tmp_path):
    scene = build_scene(features, frame)
    scene.terrain = build_terrain(scene, [write_dem(tmp_path, scene)], 33)
    value = scene.model_dump()
    value["terrain"]["origin"] = (0, 0, 0)
    with pytest.raises(ValueError, match="bounds"):
        WorldScene.model_validate(value)
    value = scene.model_dump()
    value["terrain"]["heights"].pop()
    with pytest.raises(ValueError, match="length"):
        WorldScene.model_validate(value)


def test_old_scene_without_terrain(features, frame):
    data = build_scene(features, frame).model_dump()
    data.pop("terrain")
    assert WorldScene.model_validate(data).terrain is None


def test_tile_hemispheres():
    assert "N44_00_E033_00" in tile_url(44, 33)
    assert "S01_00_W002_00" in tile_url(-1, -2)


@pytest.mark.parametrize(
    "tags,source",
    [
        ({"height": "12 m"}, "osm_height"),
        ({"height": "bad", "building:levels": "3"}, "levels"),
        ({}, "fallback"),
    ],
)
def test_height_provenance(tags, source):
    from app.gis.processing import building_height_info

    assert building_height_info(tags)[1] == source
