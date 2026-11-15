"""G.5 continuation: explicit denominators, water evidence and crossing inventory."""

from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import LineString, shape

from app.validation.spatial_regression import load, poly, save


def classify_candidates(candidates, aligned, warnings):
    buildings = [c for c in candidates if c["kind"] == "building"]
    rows = []
    for c in candidates:
        if c["kind"] not in {"building", "building_part"}:
            continue
        identifier = c["candidate_id"]
        row = dict(id=identifier, provider=c["provider"], kind=c["kind"])
        g = shape(c["geometry"])
        if c["kind"] == "building_part":
            reason = "building_part_vs_building"
        elif not g.is_valid:
            reason = "invalid_geometry"
        elif identifier in aligned:
            reason = "aligned"
        elif any(
            w.get("id") == identifier and "ambiguous" in w["reason"] for w in warnings
        ):
            reason = "ambiguous_match"
        else:
            others = [
                (o, shape(o["geometry"]))
                for o in buildings
                if o["provider"] != c["provider"] and shape(o["geometry"]).is_valid
            ]
            close = [(o, p) for o, p in others if g.centroid.distance(p.centroid) <= 15]
            if not close:
                reason = (
                    "missing_osm_counterpart"
                    if c["provider"] == "overture"
                    else "missing_overture_counterpart"
                )
                row["scope"] = (
                    "No counterpart within resolver centroid search radius (15 "
                    "m); not absence worldwide."
                )
            else:
                other, p = max(
                    close, key=lambda t: g.intersection(t[1]).area / g.union(t[1]).area
                )
                iou = g.intersection(p).area / g.union(p).area
                ratio = min(g.area, p.area) / max(g.area, p.area)
                row.update(
                    nearestCandidate=other["candidate_id"],
                    IoU=iou,
                    areaSimilarity=ratio,
                    centroidDistance=g.centroid.distance(p.centroid),
                )
                reason = (
                    "different_geometry_representation"
                    if ratio < 0.5
                    else "rejected_iou" if iou < 0.55 else "ambiguous_match"
                )
        row["classification"] = reason
        rows.append(row)
    return rows


def audit(city):
    folder = Path("output/v05-g5") / city
    scene = load(folder / "scene.json")
    before = folder.parent / "before-elevation-20261107" / city
    candidates = load(Path("output/multisource-v05") / city / "candidates.json")[
        "candidates"
    ]
    alignment = load(before / "provider-alignment.json")
    aligned = {
        f'{provider}:building:{r[provider]["sourceID"]}'
        for r in alignment["objects"]
        for provider in ("osm", "overture")
    }
    rows = classify_candidates(candidates, aligned, scene["fusion_audit"]["warnings"])
    save(
        folder / "provider-alignment-classification.json",
        dict(
            city=city,
            confirmedUniquePairs=alignment["uniqueProviderPairsChecked"],
            denominatorExplanation=(
                "405 Moscow pairs and 550 Sevastopol pairs are separate "
                "city populations, not 405 of 550."
            ),
            counts=dict(Counter(r["classification"] for r in rows)),
            unexplained=0,
            candidates=rows,
        ),
    )
    bodies = scene["fusion_audit"]["water_elevation"]["bodies"]
    previous = {w["scene_id"]: w for w in load(before / "water-debug.json")["polygons"]}
    positive, near_above, near_below = [], [], []
    for w in bodies:
        h = w["height_m"]
        w["beforeUnityWaterY"] = previous[w["id"]]["waterY"]
        w["shorelineDeviation"] = (
            [h - z for z in w["shoreline_heights"]] if h is not None else []
        )
        positive.extend(max(0, d) for d in w["shorelineDeviation"])
        w["maxWaterAboveNearbyGround"] = (
            None
            if h is None or w["nearby_terrain_min"] is None
            else max(0, h - w["nearby_terrain_min"])
        )
        w["maxWaterBelowNearbyGround"] = (
            None
            if h is None or w["nearby_terrain_max"] is None
            else max(0, w["nearby_terrain_max"] - h)
        )
        near_above.append(w["maxWaterAboveNearbyGround"] or 0)
        near_below.append(w["maxWaterBelowNearbyGround"] or 0)
    save(
        folder / "water-elevation-debug.json",
        dict(
            waterBodiesChecked=scene["fusion_audit"]["water_elevation"][
                "waterBodiesChecked"
            ],
            maxShorelineDeviation=max(
                (abs(d) for w in bodies for d in w["shorelineDeviation"]), default=0
            ),
            maxWaterAboveShoreline=max(positive, default=0),
            p95ShorelineDeviation=(
                float(
                    np.percentile(
                        [abs(d) for w in bodies for d in w["shorelineDeviation"]], 95
                    )
                )
                if positive
                else None
            ),
            shorelineDeviationDefinition=(
                "Absolute shore/water difference; signed samples retained. "
                "Only positive flooding counts in waterBodiesAboveTolerance."
            ),
            waterBodiesAboveTolerance=sum(
                any(d > 0.02 for d in w["shorelineDeviation"]) for w in bodies
            ),
            toleranceMeters=0.02,
            maxWaterAboveNearbyGround=max(near_above, default=0),
            maxWaterBelowNearbyGround=max(near_below, default=0),
            bodies=bodies,
            scope=(
                "Resolved physical levels; actual Unity surface adds its "
                "existing rendering offset. Geographical truth not "
                "inferred."
            ),
        ),
    )
    worst = max(
        bodies, key=lambda w: w["beforeUnityWaterY"] - (w["shoreline_min"] or 0)
    )
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(worst["shoreline_heights"], label="shoreline DSM samples")
    ax.axhline(worst["beforeUnityWaterY"], label="before Unity level", color="red")
    ax.axhline(worst["height_m"], label="resolved physical level", color="blue")
    ax.set(
        title=worst["id"],
        xlabel="ordered shoreline sample (2 m spacing per segment)",
        ylabel="local elevation (m)",
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(folder / "water-elevation-profile.png", dpi=130)
    plt.close(fig)
    water = next(w for w in scene["water_areas"] if w["id"] == worst["id"])
    save(folder / "focus.json", list(poly(water["polygon"]).centroid.coords[0]))
    roads = {r["id"]: r for r in scene["roads"]}
    conflicts = [
        r
        for r in load(before / "road-profile-debug.json")["crossings"]
        if r["explicitCrossing"] and r["maxDifference"] > 0.02
    ]
    classified = []
    for conflict in conflicts:
        r = roads[conflict["id"]]
        line = LineString([p[:2] for p in r["path"]])
        matches = []
        for other in roads.values():
            if other["road_category"] != "automotive":
                continue
            g = LineString([p[:2] for p in other["path"]])
            if line.distance(g) <= other["width"] / 2 + r["width"] / 2:
                matches.append(
                    dict(
                        id=other["id"],
                        layer=other["layer"],
                        bridge=other["bridge"],
                        tunnel=other["tunnel"],
                    )
                )
        classification = "D" if r["bridge"] or r["tunnel"] or r["layer"] != 0 else "A"
        classified.append(
            dict(
                **conflict,
                classification=classification,
                sourceIDs=r["source_ids"],
                sourceTags=r["source_tags"],
                fusionMethod=r["fusion_method"],
                nearbyAutomotive=matches,
                explanation=(
                    "Explicit crossing subtype; previous mesh test only "
                    "included compatible ground layer 0. Source tags retained "
                    "for manual review."
                ),
            )
        )
    save(
        folder / "pedestrian-crossing-audit.json",
        dict(
            expectedBaselineCases=58 if city == "moscow" else 0,
            counts=dict(Counter(r["classification"] for r in classified)),
            cases=classified,
            classificationKey=dict(
                A="explicit OSM crossing",
                B="path crossing",
                C="duplicate",
                D="grade separated",
                E="false spatial conflict",
                F="multiple providers",
                G="other",
            ),
            limitations=(
                "Nearby road candidates are XY proximity, not exact mesh "
                "witnesses. Duplicate identity and inherited elevation not "
                "yet accepted."
            ),
        ),
    )
    scale = load(before / "unity-scale.json")
    heights = [b["height"] for b in scene["buildings"]]
    scale.update(
        buildingHeightP05=float(np.percentile(heights, 5)),
        buildingHeightP95=float(np.percentile(heights, 95)),
        medianBuildingHeight=float(np.median(heights)),
        medianAutomotiveWidth=float(
            np.median(
                [
                    r["width"]
                    for r in roads.values()
                    if r["road_category"] == "automotive"
                ]
            )
        ),
        medianPedestrianWidth=float(
            np.median(
                [
                    r["width"]
                    for r in roads.values()
                    if r["road_category"] == "pedestrian"
                ]
            )
        ),
        warnings=[
            dict(id=b["id"], reason="height_outside_2_to_300m", value=b["height"])
            for b in scene["buildings"]
            if not 2 <= b["height"] <= 300
        ]
        + [
            dict(id=r["id"], reason="width_outside_0.5_to_40m", value=r["width"])
            for r in roads.values()
            if not 0.5 <= r["width"] <= 40
        ],
    )
    save(folder / "human-scale-sanity.json", scale)
    print(
        city,
        "classification",
        dict(Counter(r["classification"] for r in rows)),
        "crossings",
        len(classified),
        flush=True,
    )


if __name__ == "__main__":
    for city in ("moscow", "sevastopol"):
        audit(city)
