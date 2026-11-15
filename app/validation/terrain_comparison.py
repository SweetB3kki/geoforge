"""Compare pre-water terrain to actual water-only terrain, without road cuts."""

import hashlib
from pathlib import Path

import shapely

from app.validation.road_contact_audit import read_faces
from app.validation.spatial_regression import footprints, load, poly, save


def compare(city):
    folder = Path("output/v05-g5") / city
    scene = load(folder / "scene.json")
    digest = hashlib.sha256((folder / "scene.json").read_bytes()).hexdigest()
    dry, triangles = footprints(
        read_faces(folder / "terrain-reference.bin", digest)["Terrain/dry"]
    )
    wet, _ = footprints(
        read_faces(folder / "unity-faces.bin", digest)["Terrain/water-only"]
    )
    water = shapely.union_all([poly(w["polygon"]) for w in scene["water_areas"]])
    boundary = poly(scene["metadata"]["selection_boundary"])
    lost = dry.difference(wet).difference(water)
    missing = boundary.difference(water).difference(wet)
    robust = lost.buffer(-0.001)
    touched = shapely.area(shapely.intersection(triangles, lost)) > 1e-6
    result = dict(
        sceneSHA256=digest,
        dryMissingSelectionArea=boundary.difference(dry).area,
        terrainAreaRemovedOutsideWater=lost.area,
        terrainTrianglesRemovedOutsideWater=int(sum(touched)),
        triangleCountDefinition="Dry triangles with >1e-6 m2 loss outside water. "
        "Partial loss counts. Retessellation does not preserve triangle IDs.",
        removedOutsideWaterAfter1mmErosion=robust.area,
        missingLandAfter1mmErosion=missing.buffer(-0.001).area,
        largestMissingLandPieces=[
            dict(area=g.area, bounds=list(g.bounds))
            for g in sorted(shapely.get_parts(missing), key=lambda g: -g.area)[:10]
        ],
    )
    save(folder / "terrain-cutout-comparison.json", result)
    print(city, result, flush=True)


if __name__ == "__main__":
    for city in ("moscow", "sevastopol"):
        compare(city)
