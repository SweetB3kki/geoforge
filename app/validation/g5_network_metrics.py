import argparse
import hashlib
from pathlib import Path

import numpy as np
import shapely

from app.validation.road_contact_audit import read_faces
from app.validation.spatial_regression import load, save, section_hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("output/v05-g5"))
    args = parser.parse_args()
    for city in ("moscow", "sevastopol"):
        folder = args.root / city
        scene = load(folder / "scene.json")
        digest = hashlib.sha256((folder / "scene.json").read_bytes()).hexdigest()
        faces = read_faces(folder / "unity-faces.bin", digest)
        checks = load(folder / "road-profile-render-checks.json")
        samples = {r["roadId"]: r["heights"] for r in checks["sampledMeshes"]}
        debug = load(folder / "road-profile-debug.json")
        contact = load(folder / "road-contact-audit.json")
        roads = [
            r
            for r in scene["roads"]
            if r["road_category"] == "automotive"
            and not r["bridge"]
            and not r["tunnel"]
            and r["layer"] == 0
        ]
        endpoints = []
        sections = []
        station_rows = []
        for road in roads:
            points = np.array(road["vertical_profile"]["points"])
            hs = samples.get(road["id"], [None] * len(points))
            for i in (0, len(points) - 1):
                endpoints.append(
                    dict(
                        road=road["id"],
                        endpoint=i,
                        error=(
                            None
                            if hs[i] is None
                            else float(abs(hs[i] - 0.03 - points[i, 2]))
                        ),
                    )
                )
            d = np.gradient(points[:, :2], axis=0)
            n = (
                d[:, [1, 0]]
                * [-1, 1]
                / np.maximum(1e-12, np.linalg.norm(d, axis=1)[:, None])
            )
            xy = np.concatenate(
                [points[:, :2] + k * road["width"] * n for k in (-0.4, 0, 0.4)]
            )
            values = section_hits(faces["Roads/" + road["id"]], xy).reshape(3, -1)
            valid = np.isfinite(values).all(axis=0)
            for j in range(len(points)):
                station_rows.append(
                    dict(
                        road=road["id"],
                        station=j,
                        xy=points[j, :2].tolist(),
                        measured=bool(valid[j]),
                        leftY=float(values[0, j]) if valid[j] else None,
                        centerY=float(values[1, j]) if valid[j] else None,
                        rightY=float(values[2, j]) if valid[j] else None,
                        crossSectionDelta=(
                            float(np.ptp(values[:, j])) if valid[j] else None
                        ),
                    )
                )
            if valid.any():
                gaps = np.full(len(points), -1.0)
                gaps[valid] = abs(values[0, valid] - values[2, valid])
                i = int(np.argmax(gaps))
                sections.append(
                    dict(
                        road=road["id"],
                        checked=int(valid.sum()),
                        missing=int((~valid).sum()),
                        maximumDifference=float(gaps[i]),
                        station=i,
                        center=points[i].tolist(),
                        width=road["width"],
                        leftHeight=float(values[0, i]),
                        rightHeight=float(values[2, i]),
                        leftXY=xy[i].tolist(),
                        rightXY=xy[2 * len(points) + i].tolist(),
                    )
                )
        errors = [r["error"] for r in endpoints if r["error"] is not None]
        report = dict(
            sceneSHA256=digest,
            toleranceMeters=0.02,
            junctionsChecked=debug["junctionsChecked"],
            sameLayerJunctions=debug["junctionsChecked"],
            maxEndpointMismatch=debug["maxEndpointElevationDifference"],
            p95EndpointMismatch=debug["p95EndpointElevationDifference"],
            junctionsAboveTolerance=debug["junctionsAboveTolerance"],
            roadProfilesChecked=len(roads),
            endpointConstraintViolations=sum(v > 0.02 for v in errors),
            maxEndpointConstraintError=max(errors, default=None),
            unmeasuredMeshEndpoints=len(endpoints) - len(errors),
            junctionPatchDiscontinuities=len(contact["pairs_over_2cm"]),
            meshContactScope=contact["scope"],
            noExactContactPairs=len(contact["pairs_without_exact_contact"]),
            crossSectionScope=(
                "Ground automotive profile stations, +/-40% width. "
                "Includes junction zones; large differences need classification, "
                "not an automatic camber pass."
            ),
            maxCrossSectionDifference=max(
                (r["maximumDifference"] for r in sections), default=None
            ),
            crossSectionRoadsOver2cm=sum(
                r["maximumDifference"] > 0.02 for r in sections
            ),
            crossSections=sorted(sections, key=lambda r: -r["maximumDifference"]),
            endpoints=endpoints,
        )
        deltas = [r["crossSectionDelta"] for r in station_rows if r["measured"]]
        report.update(
            maxCrossSectionDelta=max(deltas, default=None),
            p95CrossSectionDelta=float(np.percentile(deltas, 95)) if deltas else None,
            meanCrossSectionDelta=float(np.mean(deltas)) if deltas else None,
            roadsAboveTolerance=len(
                {
                    r["road"]
                    for r in station_rows
                    if r["measured"] and r["crossSectionDelta"] > 0.02
                }
            ),
            unmeasuredCrossSectionStations=sum(not r["measured"] for r in station_rows),
        )
        save(
            folder / "cross-section-stations.json",
            dict(
                scope=(
                    "Actual mesh samples at all automotive ground stations; "
                    "missing samples are not passes."
                ),
                toleranceMeters=0.02,
                stations=station_rows,
            ),
        )
        save(folder / "road-network-elevation-debug.json", report)
        crossing = load(folder / "crossing-mesh-contact-audit.json")
        road_shapes = [
            shapely.union_all(shapely.polygons(faces["Roads/" + r["id"]][:, :, :2]))
            for r in roads
        ]
        union = shapely.union_all(road_shapes)
        by_id = {r["id"]: r for r in scene["roads"]}
        for case in crossing["cases"]:
            if case["measured"]:
                continue
            tri = faces["Roads/" + case["id"]]
            pg = shapely.union_all(shapely.polygons(tri[:, :, :2]))
            case["distanceToAutomotiveMeshMeters"] = float(pg.distance(union))
            case["sourceNodeIDs"] = by_id[case["id"]]["node_ids"]
            case["classification"] = "no_actual_automotive_surface_overlap"
            case["acceptance"] = "unmeasured; cannot claim vertical agreement"
        save(folder / "crossing-mesh-contact-audit.json", crossing)
        print(
            city,
            {
                k: v
                for k, v in report.items()
                if k not in ("crossSections", "endpoints")
            },
            flush=True,
        )


if __name__ == "__main__":
    main()
