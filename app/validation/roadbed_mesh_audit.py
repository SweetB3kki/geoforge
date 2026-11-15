"""Measured derived-ground/road relations. Explicitly records sampling coverage."""

import argparse
import hashlib
from pathlib import Path

import numpy as np
import shapely

from app.validation.road_contact_audit import cross, height, read_faces
from app.validation.spatial_regression import load, save


def indexed(tri):
    tri = tri[abs(cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])) > 1e-10]
    return tri, shapely.STRtree(shapely.polygons(tri[:, :, :2]))


def sample(tri, tree, points, maximum=True):
    result = np.full(len(points), -np.inf if maximum else np.inf)
    operation = np.maximum.at if maximum else np.minimum.at
    for start in range(0, len(points), 10000):
        xy = points[start : start + 10000, :2]
        ai, bi = tree.query(shapely.points(xy), predicate="intersects")
        operation(result, start + ai, height(tri[bi], xy[ai]))
    return result


def audit(folder):
    scene = load(folder / "scene.json")
    digest = hashlib.sha256((folder / "scene.json").read_bytes()).hexdigest()
    faces = read_faces(folder / "unity-faces.bin", digest)
    terrain = faces["Terrain/rendered"]
    roads = [
        r
        for r in scene["roads"]
        if not r["bridge"]
        and not r["tunnel"]
        and r["layer"] == 0
        and (r["road_category"] == "automotive" or r["road_subtype"] == "crossing")
    ]
    road, road_tree = indexed(
        np.concatenate([faces["Roads/" + r["id"]] for r in roads])
    )
    terrain = terrain[
        abs(cross(terrain[:, 1] - terrain[:, 0], terrain[:, 2] - terrain[:, 0])) > 1e-10
    ]
    vertices = np.unique(terrain.reshape(-1, 3), axis=0)
    road_y = sample(road, road_tree, vertices, maximum=False)
    measured = np.isfinite(road_y)
    vdelta = vertices[:, 2] - road_y
    centers = terrain.mean(axis=1)
    cy = sample(road, road_tree, centers, maximum=False)
    cdelta = centers[:, 2] - cy
    conflict = cdelta > 0.02
    areas = abs(cross(terrain[:, 1] - terrain[:, 0], terrain[:, 2] - terrain[:, 0])) / 2
    maximum = max(
        float(np.max(vdelta[measured], initial=0)),
        float(np.max(cdelta[np.isfinite(cy)], initial=0)),
    )
    witnesses = []
    for i in np.argsort(vdelta)[-10:][::-1]:
        if not np.isfinite(road_y[i]) or vdelta[i] <= 0.02:
            continue
        witnesses.append(
            dict(
                xy=vertices[i, :2].tolist(),
                terrainY=float(vertices[i, 2]),
                roadY=float(road_y[i]),
                delta=float(vdelta[i]),
            )
        )
    del road_tree
    terrain, tree = indexed(terrain)
    rc = road.mean(axis=1)
    ground_y = sample(terrain, tree, rc)
    good = np.isfinite(ground_y)
    gaps = rc[good, 2] - ground_y[good]
    result = dict(
        sceneSHA256=digest,
        scope=(
            "All rendered terrain vertices plus terrain triangle centroids "
            "covered by eligible road faces. Gap sampling at road triangle "
            "centroids. Bridges/tunnels/nonzero layers excluded. "
            "This is not an exact area intersection proof."
        ),
        terrainVerticesChecked=int(measured.sum()),
        terrainTrianglesChecked=int(np.isfinite(cy).sum()),
        roadTerrainConflicts=int(conflict.sum()),
        terrainVerticesAboveRoad=int((vdelta > 0.02).sum()),
        maxTerrainAboveRoad=maximum,
        conflictAreaApprox=float(areas[conflict].sum()),
        conflictAreaDefinition=(
            "Sum of entire terrain triangle areas whose centroid is above "
            "a road; approximate, overlaps are not unioned."
        ),
        maxRoadGroundGap=float(np.max(gaps, initial=0)),
        p95RoadGroundGap=float(np.percentile(gaps, 95)) if len(gaps) else None,
        roadGapSamples=int(good.sum()),
        unmeasuredRoadGapSamples=int((~good).sum()),
        intentionalRoadbedSeparationMeters=0.03,
        toleranceMeters=0.02,
        worstPokeThrough=witnesses,
    )
    save(folder / "roadbed-mesh-audit.json", result)
    print(folder.name, result, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("output/v05-g5/roadbed-candidate")
    )
    args = parser.parse_args()
    for city in ("moscow", "sevastopol"):
        audit(args.root / city)


if __name__ == "__main__":
    main()
