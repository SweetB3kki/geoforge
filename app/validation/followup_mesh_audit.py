"""Final G.5 mesh checks: water visibility and complete crossing intersections."""

import argparse
import hashlib
from pathlib import Path

import numpy as np
import shapely

from app.validation.road_contact_audit import cross, height, read_faces
from app.validation.spatial_regression import analyse_roads, load, poly, save


def audit(city, root=Path("output/v05-g5")):
    folder = root / city
    scene = load(folder / "scene.json")
    digest = hashlib.sha256((folder / "scene.json").read_bytes()).hexdigest()
    faces = read_faces(folder / "unity-faces.bin", digest)
    quality = load(folder / "unity-quality.json")
    assert quality["scene_sha256"] == digest
    summary = analyse_roads(scene, faces, folder, load(folder / "unity-scale.json"))
    save(folder / "road-elevation-summary.json", summary)
    water = []
    for w in scene["water_areas"]:
        tri = faces["Water/" + w["id"]]
        expected = w["water_level_m"] + 0.01
        water.append(
            {
                "id": w["id"],
                "expectedRenderedY": expected,
                "minY": float(tri[:, :, 2].min()),
                "maxY": float(tri[:, :, 2].max()),
                "maxHeightError": float(abs(tri[:, :, 2] - expected).max()),
            }
        )
    inset = shapely.union_all(
        [poly(w["polygon"]) for w in scene["water_areas"]]
    ).buffer(-0.02)
    count = 0
    area = 0
    for key, tri in faces.items():
        if not key.startswith("Green/"):
            continue
        good = abs(cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])) > 1e-10
        pg = shapely.polygons(tri[good, :, :2])
        overlap = shapely.area(shapely.intersection(pg, inset))
        count += int((overlap > 1e-8).sum())
        area += float(overlap.sum())
    save(
        folder / "water-render-acceptance.json",
        {
            "sceneSHA256": digest,
            "polygons": water,
            "greenTrianglesInsideWater": count,
            "greenAreaInsideWater": area,
            "planarBoundaryToleranceMeters": 0.02,
        },
    )
    cars = [
        r
        for r in scene["roads"]
        if r["road_category"] == "automotive"
        and not r["bridge"]
        and not r["tunnel"]
        and r["layer"] == 0
    ]
    triangles = np.concatenate([faces["Roads/" + r["id"]] for r in cars])
    owner = np.concatenate(
        [np.full(len(faces["Roads/" + r["id"]]), i) for i, r in enumerate(cars)]
    )
    good = (
        abs(cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]))
        > 1e-10
    )
    triangles = triangles[good]
    owner = owner[good]
    tree = shapely.STRtree(shapely.polygons(triangles[:, :, :2]))
    results = []
    for r in scene["roads"]:
        if (
            r["road_subtype"] != "crossing"
            or r["bridge"]
            or r["tunnel"]
            or r["layer"] != 0
        ):
            continue
        ts = faces["Roads/" + r["id"]]
        ts = ts[abs(cross(ts[:, 1] - ts[:, 0], ts[:, 2] - ts[:, 0])) > 1e-10]
        pg = shapely.polygons(ts[:, :, :2])
        ai, bi = tree.query(pg, predicate="intersects")
        if not len(ai):
            results.append({"id": r["id"], "measured": False})
            continue
        intersection = shapely.intersection(pg[ai], tree.geometries[bi])
        xy, indices = shapely.get_coordinates(intersection, return_index=True)
        delta = height(ts[ai[indices]], xy) - height(triangles[bi[indices]], xy)
        k = int(np.argmax(abs(delta)))
        results.append(
            {
                "id": r["id"],
                "measured": True,
                "maxAbsDifference": float(abs(delta[k])),
                "minDifference": float(delta.min()),
                "maxDifference": float(delta.max()),
                "witnessXY": xy[k].tolist(),
                "automotive": cars[int(owner[bi[indices[k]]])]["id"],
                "facePairs": len(ai),
            }
        )
    save(
        folder / "crossing-mesh-contact-audit.json",
        {
            "sceneSHA256": digest,
            "scope": (
                "Exact triangle intersections, including crossing edges. "
                "Compares every compatible automotive plane, "
                "not only the upper envelope."
            ),
            "toleranceMeters": 0.02,
            "crossingsChecked": len(results),
            "crossingsAboveTolerance": sum(
                r.get("maxAbsDifference", 0) > 0.02 for r in results
            ),
            "unmeasured": sum(not r["measured"] for r in results),
            "cases": results,
        },
    )
    scale = (
        load(folder / "human-scale-sanity.json")
        if (folder / "human-scale-sanity.json").exists()
        else {}
    )
    scale.update(load(folder / "unity-scale.json"))
    save(folder / "human-scale-sanity.json", scale)
    print(
        city,
        "roads",
        summary,
        "green-water",
        count,
        area,
        "crossings",
        sum(r.get("maxAbsDifference", 0) > 0.02 for r in results),
        len(results),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("output/v05-g5"))
    args = parser.parse_args()
    for city in ("moscow", "sevastopol"):
        audit(city, args.root)
