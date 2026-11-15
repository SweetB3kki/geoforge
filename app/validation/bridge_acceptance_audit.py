"""Actual bridge inventory and endpoint/profile acceptance, without inventing ramps."""

import argparse
import hashlib
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.validation.spatial_regression import load, save


def audit(folder):
    scene = load(folder / "scene.json")
    roads = scene["roads"]
    results = []
    for bridge in (r for r in roads if r["bridge"]):
        p = np.array(bridge["vertical_profile"]["points"])
        raw = np.array(bridge["vertical_profile"]["raw_heights"])
        ds = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1))]
        grade = np.diff(p[:, 2]) / np.diff(ds)
        endpoints = []
        for end in (0, -1):
            candidates = []
            for road in roads:
                if road["bridge"] or road["tunnel"] or road["layer"] != 0:
                    continue
                # Steps may be a pedestrian bridge approach. Category mismatch
                # is retained in the evidence rather than silently excluded.
                compatible = road["road_category"] == bridge["road_category"] or (
                    bridge["road_category"] == "pedestrian"
                    and road["road_category"] == "steps"
                )
                if not compatible:
                    continue
                for index in (0, -1):
                    q = road["vertical_profile"]["points"][index]
                    distance = float(np.linalg.norm(p[end, :2] - q[:2]))
                    if distance <= 0.02:
                        rp = np.array(road["vertical_profile"]["points"])
                        rd = np.linalg.norm(np.diff(rp[:, :2], axis=0), axis=1)
                        g = np.diff(rp[:, 2]) / rd
                        candidates.append(
                            dict(
                                road=road["id"],
                                endpoint=index,
                                xyDistance=distance,
                                roadCategory=road["road_category"],
                                roadLayer=road["layer"],
                                heightDifference=float(p[end, 2] - q[2]),
                                approachGrade=float(g[index]),
                                sameSourceNode=bridge["node_ids"][end]
                                == road["node_ids"][index],
                            )
                        )
            endpoints.append(
                dict(
                    endpoint=end,
                    xy=p[end, :2].tolist(),
                    deckHeight=float(p[end, 2]),
                    candidates=candidates,
                    status=(
                        "measured" if candidates else "no_ground_endpoint_in_selection"
                    ),
                )
            )
        results.append(
            dict(
                id=bridge["id"],
                category=bridge["road_category"],
                layer=bridge["layer"],
                method=bridge["vertical_profile"]["bridge_height_method"],
                lengthMeters=float(ds[-1]),
                deckStartGrade=float(grade[0]),
                deckEndGrade=float(grade[-1]),
                maximumGradeChange=float(np.abs(np.diff(grade)).max(initial=0)),
                minSampledTerrainClearance=float((p[:, 2] - raw).min()),
                terrainClearanceScope=(
                    "Source profile sample positions only; "
                    "not a complete mesh/span clearance proof."
                ),
                endpoints=endpoints,
            )
        )
    differences = [
        abs(c["heightDifference"])
        for b in results
        for e in b["endpoints"]
        for c in e["candidates"]
    ]
    report = dict(
        sceneSHA256=hashlib.sha256((folder / "scene.json").read_bytes()).hexdigest(),
        bridgesChecked=len(results),
        automotiveBridges=sum(b["category"] == "automotive" for b in results),
        pedestrianBridges=sum(b["category"] == "pedestrian" for b in results),
        maxApproachStep=max(differences, default=None),
        approachConnectionsAboveTolerance=sum(x > 0.02 for x in differences),
        unmeasuredEndpoints=sum(
            not e["candidates"] for b in results for e in b["endpoints"]
        ),
        toleranceMeters=0.02,
        accepted=not results,
        bridges=results,
        acceptanceReason=(
            "No bridges in selection; synthetic behaviour tests required."
            if not results
            else (
                "Measured endpoint steps block acceptance; "
                "XY matches identify candidates, not topology mutations."
            )
        ),
    )
    save(folder / "bridge-approach-audit.json", report)
    if results:
        fig, axes = plt.subplots(len(results), 1, figsize=(11, 3 * len(results)))
        for ax, result in zip(axes, results, strict=True):
            r = next(r for r in roads if r["id"] == result["id"])
            p = np.array(r["vertical_profile"]["points"])
            ds = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1))]
            ax.plot(ds, p[:, 2], label="resolved deck")
            ax.plot(
                ds, r["vertical_profile"]["raw_heights"], label="raw DSM (unchanged)"
            )
            for e in result["endpoints"]:
                for c in e["candidates"]:
                    ax.scatter(
                        ds[e["endpoint"]],
                        e["deckHeight"] - c["heightDifference"],
                        color="red",
                        marker="x",
                    )
            ax.set(
                title=result["id"],
                xlabel="distance along span (m)",
                ylabel="local height (m)",
            )
            ax.legend()
        fig.tight_layout()
        fig.savefig(folder / "bridge-approach-profiles.png", dpi=110)
        plt.close(fig)
    print(folder.name, {k: v for k, v in report.items() if k != "bridges"}, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("output/v05-g5"))
    args = parser.parse_args()
    for city in ("moscow", "sevastopol"):
        audit(args.root / city)


if __name__ == "__main__":
    main()
