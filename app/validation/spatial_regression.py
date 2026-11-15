"""G.5: compare recorded provider geometry, fused scenes and measured Unity faces."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import matplotlib
import numpy as np
import shapely
from pyproj import Transformer
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import transform

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.fusion.scene_adapter import terrain_height
from app.validation.road_contact_audit import cross, height, read_faces


def load(path):
    return json.loads(path.read_bytes())


def save(path, data):
    path.write_text(
        json.dumps(data, indent=1, ensure_ascii=False, allow_nan=False), encoding="utf8"
    )


def poly(p):
    return Polygon(
        [v[:2] for v in p["exterior"]], [[v[:2] for v in ring] for ring in p["holes"]]
    )


def info(g):
    return dict(
        area=g.area,
        bounds=list(g.bounds),
        centroid=list(g.centroid.coords[0])[:2],
        type=g.geom_type,
        valid=g.is_valid,
        holes=sum(
            len(p.interiors) for p in shapely.get_parts(g) if p.geom_type == "Polygon"
        ),
    )


def outline(ax, g, color, alpha=1):
    for part in shapely.get_parts(g):
        if part.geom_type == "Polygon":
            for ring in [part.exterior, *part.interiors]:
                ax.plot(*ring.xy, color=color, lw=0.65, alpha=alpha)


def footprints(faces):
    det = cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    polys = shapely.polygons(faces[det != 0, :, :2])
    return shapely.union_all(polys), polys


def intersections(buildings, waters):
    rows = []
    for b in buildings:
        g = poly(b["footprint"])
        for wid, w in waters.items():
            if not g.intersects(w):
                continue
            a = g.intersection(w).area
            if a > 1e-8:
                rows.append(
                    dict(
                        building=b["id"],
                        water=wid,
                        area=a,
                        fraction=a / g.area,
                        sources=b["sources"],
                        method=b["fusion_method"],
                    )
                )
    return sorted(rows, key=lambda r: -r["area"])


def section_hits(tri, coords):
    valid = cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) != 0
    tri = tri[valid]
    pg = shapely.polygons(tri[:, :, :2])
    i, j = shapely.STRtree(pg).query(shapely.points(coords), predicate="intersects")
    z = np.full(len(coords), -np.inf)
    np.maximum.at(z, i, height(tri[j], coords[i]))
    return z


def roughness(x, z):
    ds = np.linalg.norm(np.diff(x, axis=0), axis=1)
    slope = np.diff(z) / ds
    changes = np.diff(slope)
    return dict(
        rawDefinition="RMS adjacent grade change (unitless)",
        roughness=float(np.sqrt(np.mean(changes**2))) if len(changes) else 0,
        netElevationChange=float(z[-1] - z[0]),
        maximumGrade=float(max(abs(slope))),
        maximumGradeChange=float(max(abs(changes), default=0)),
    )


def analyse_roads(scene, faces, folder, junction):
    roads = scene["roads"]
    rows = {}
    nodes = defaultdict(list)
    hits = []
    walks = []
    for r in roads:
        pr = r["vertical_profile"]
        p = np.array(pr["points"])
        raw = np.array(pr["raw_heights"])
        row = dict(
            strategy=pr["strategy"],
            raw=roughness(p[:, :2], raw),
            conditioned=roughness(p[:, :2], p[:, 2]),
            sourceTerrainDeviation=max(abs(raw - p[:, 2])),
        )
        rows[r["id"]] = row
        tri = faces.get("Roads/" + r["id"])
        if tri is None:
            continue
        direction = np.gradient(p[:, :2], axis=0)
        normal = (
            direction[:, [1, 0]]
            * [-1, 1]
            / np.maximum(1e-12, np.linalg.norm(direction, axis=1)[:, None])
        )
        sides = np.concatenate(
            [p[:, :2] + k * r["width"] * normal for k in (-0.4, 0, 0.4)]
        )
        left, center, right = section_hits(tri, sides).reshape(3, -1)
        valid = np.isfinite(left) & np.isfinite(right) & np.isfinite(center)
        row.update(
            crossSections=len(p),
            measuredCrossSections=int(valid.sum()),
            maxEdgeHeightDifference=(
                float(max(abs(left[valid] - right[valid]), default=0))
                if valid.any()
                else None
            ),
            maxTransverseGrade=(
                float(max(abs(left[valid] - right[valid])) / (0.8 * r["width"]))
                if valid.any()
                else None
            ),
        )
        if r["bridge"] or r["tunnel"] or r["layer"] != 0:
            continue
        if r["road_category"] == "automotive":
            lookup = {tuple(np.round(v[:2], 6)): v[2] for v in p}
            for n, v in zip(r["node_ids"], r["path"], strict=True):
                if n and tuple(np.round(v[:2], 6)) in lookup:
                    nodes[n].append((r["id"], lookup[tuple(np.round(v[:2], 6))]))
            hits.append((r, tri))
        elif r["road_category"] in {"pedestrian", "cycle"}:
            walks.append((r, tri))
    shared = {n: v for n, v in nodes.items() if len({rid for rid, h in v}) > 1}
    delta = [max(h for _, h in v) - min(h for _, h in v) for v in shared.values()]
    # Sample both meshes at identical XY; missing triangles break a sign run.
    cars = np.concatenate([t for r, t in hits])
    valid = cross(cars[:, 1] - cars[:, 0], cars[:, 2] - cars[:, 0]) != 0
    cars = cars[valid]
    index = shapely.STRtree(shapely.polygons(cars[:, :, :2]))
    contacts = []
    for r, tri in walks:
        p = np.array(r["vertical_profile"]["points"])
        line = LineString(p[:, :2])
        ds = np.linspace(0, line.length, max(2, int(np.ceil(line.length)) + 1))
        xy = shapely.get_coordinates(shapely.line_interpolate_point(line, ds))
        i, j = index.query(shapely.points(xy), predicate="intersects")
        if not len(i):
            continue
        own = section_hits(tri, xy)
        other = np.full(len(ds), -np.inf)
        np.maximum.at(other, i, height(cars[j], xy[i]))
        good = np.isfinite(own) & np.isfinite(other)
        d = np.zeros(len(ds))
        d[good] = own[good] - other[good]
        if not good.any():
            continue
        last = 0
        switches = 0
        for ok, val in zip(good, d, strict=True):
            if not ok:
                last = 0
                continue
            sign = 1 if val > 0.02 else -1 if val < -0.02 else 0
            if sign:
                switches += int(last != 0 and last != sign)
                last = sign
        contacts.append(
            dict(
                id=r["id"],
                type=r["road_subtype"],
                samples=int(good.sum()),
                maxDifference=float(max(abs(d[good]))),
                signChanges=switches,
                explicitCrossing=r["road_subtype"] == "crossing",
            )
        )
    auto = [r for r, t in hits]
    chosen = {
        "major": max(auto, key=lambda r: r["width"]),
        "complex-junction": next(
            r for r in auto if r["id"] in junction["junctionRoads"]
        ),
        "steepest": max(
            auto, key=lambda r: rows[r["id"]]["conditioned"]["maximumGrade"]
        ),
    }
    if contacts:
        worst = max(contacts, key=lambda c: c["maxDifference"])
        chosen["path-overlap"] = next(r for r in roads if r["id"] == worst["id"])
    fig, axs = plt.subplots(
        len(chosen), 1, figsize=(9, 3 * len(chosen)), layout="constrained"
    )
    for ax, (name, r) in zip(axs, chosen.items(), strict=True):
        p = np.asarray(r["vertical_profile"]["points"])
        ds = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1))]
        mesh = faces["Roads/" + r["id"]].reshape(-1, 3)
        mesh = mesh[:: max(1, len(mesh) // 12000)]
        ax.scatter(
            shapely.line_locate_point(
                LineString(p[:, :2]), shapely.points(mesh[:, :2])
            ),
            mesh[:, 2],
            s=1,
            color="#7d8c9a",
            label="Unity mesh",
        )
        ax.plot(
            ds, r["vertical_profile"]["raw_heights"], label="raw DSM", color="#ae6435"
        )
        ax.plot(ds, p[:, 2], label="resolved profile", color="#14578b")
        for n, v in zip(r["node_ids"], r["path"], strict=True):
            if n in shared:
                ax.scatter(
                    LineString(p[:, :2]).project(Point(v[:2])),
                    shared[n][0][1],
                    marker="x",
                    color="black",
                )
        ax.set(
            title=name + ": " + r["id"],
            xlabel="distance (m)",
            ylabel="local elevation (m)",
        )
        ax.legend()
    fig.savefig(folder / "road-profile-debug.png", dpi=115)
    plt.close(fig)
    save(
        folder / "road-profile-debug.json",
        dict(
            roads=rows,
            plots={k: v["id"] for k, v in chosen.items()},
            crossings=contacts,
            junctionsChecked=len(delta),
            maxEndpointElevationDifference=max(delta, default=None),
            p95EndpointElevationDifference=(
                float(np.percentile(delta, 95)) if delta else None
            ),
            junctionsAboveTolerance=int(sum(v > 0.02 for v in delta)),
            junctionToleranceMeters=0.02,
            scope="Shared automotive profile nodes including interior junctions. "
            "Mesh edges tested separately. "
            "Cross-sections at stations, +/-40% width. "
            "Positive-width gaps and real-world DTM not inferred.",
        ),
    )
    return dict(
        junctions=len(delta),
        junctionMax=max(delta, default=None),
        walkingOverlaps=len(contacts),
        explicitCrossingsOver2cm=sum(
            c["explicitCrossing"] and c["maxDifference"] > 0.02 for c in contacts
        ),
        alternatingRuns=sum(c["signChanges"] >= 2 for c in contacts),
    )


def audit(city, root=Path("output")):
    folder = root / "v05-g5" / city
    base = root / "multisource-v05" / city
    before = load(base.parent / "phase-g" / city / "scene.json")
    scene = load(folder / "scene.json")
    cand = load(base / "candidates.json")
    cs = {c["candidate_id"]: c for c in cand["candidates"]}
    water = {w["id"]: poly(w["polygon"]) for w in scene["water_areas"]}
    bound = poly(scene["metadata"]["selection_boundary"])
    assert scene["terrain"] == before["terrain"] and scene["roads"] == before["roads"]
    digest = hashlib.sha256((folder / "scene.json").read_bytes()).hexdigest()
    faces = read_faces(folder / "unity-faces.bin", digest)
    scale = load(folder / "unity-scale.json")
    q = load(folder / "unity-quality.json")
    assert digest == q["scene_sha256"]
    transform_xy = Transformer.from_crs(4326, cand["crs"], always_xy=True)
    sources = {
        r["source_osm_id"]: shape(r["raw_geometry_wgs84"])
        for r in scene["processing_audit"]["records"]
        if r.get("raw_geometry_wgs84")
    }
    tables = {
        k: gpd.read_parquet(base / (k + ".parquet")).set_index("id")
        for k in ("building", "water")
    }
    assert all(t.crs.to_epsg() == 4326 for t in tables.values())

    def raw(c):
        return (
            sources[c["provider_feature_id"]]
            if c["provider"] == "osm"
            else tables[c["kind"]].loc[c["provider_feature_id"], "geometry"]
        )

    def project(g):
        pr = transform(transform_xy.transform, g)
        return pr, translate(pr, -cand["origin_easting"], -cand["origin_northing"])

    assert (
        cand["origin_easting"] == scene["origin"]["easting"]
        and cand["origin_northing"] == scene["origin"]["northing"]
    )
    matched = []
    fusion = []
    fig, ax = plt.subplots(figsize=(9, 8))
    for b in scene["buildings"]:
        keys = [k for k in b["sources"] if k in cs and cs[k]["kind"] == "building"]
        rr = dict(
            id=b["id"],
            method=b["fusion_method"],
            sources=keys,
            geometrySource=b["field_provenance"].get("geometry"),
            heightSource=b["height_source"],
            parts=[p["sources"] for p in b["parts"]],
            resolved=b["footprint"],
            candidates={k: cs[k]["geometry"] for k in keys},
        )
        fusion.append(rr)
        a = next((cs[k] for k in keys if cs[k]["provider"] == "osm"), None)
        v = next((cs[k] for k in keys if cs[k]["provider"] == "overture"), None)
        if not (a and v):
            continue
        entry = dict(id=b["id"])
        local = []
        for c, color in [(a, "#2670ae"), (v, "#df6439")]:
            wgs = raw(c)
            pr, g = project(wgs)
            local.append(g)
            entry[c["provider"]] = dict(
                sourceID=c["provider_feature_id"],
                sourceCentroidLonLat=list(wgs.centroid.coords[0]),
                projectedCentroid=list(pr.centroid.coords[0]),
                localCentroid=list(g.centroid.coords[0]),
                candidateHausdorffMeters=g.hausdorff_distance(shape(c["geometry"])),
            )
            outline(ax, g, color, 0.85 if c["provider"] == "osm" else 0.5)
        x, y = local
        entry.update(
            centroidDifferenceMeters=x.centroid.distance(y.centroid),
            geometryDistanceMeters=x.distance(y),
            IoU=x.intersection(y).area / x.union(y).area,
        )
        matched.append(entry)
        rr.update(IoU=entry["IoU"], centroidDistance=entry["centroidDifferenceMeters"])
    ds = [m["centroidDifferenceMeters"] for m in matched]
    assert len(ds) >= 20
    alignment = dict(
        matchedObjectsChecked=len(ds),
        uniqueProviderPairsChecked=len(
            {(m["osm"]["sourceID"], m["overture"]["sourceID"]) for m in matched}
        ),
        medianCentroidDifferenceMeters=float(np.median(ds)),
        p95CentroidDifferenceMeters=float(np.percentile(ds, 95)),
        maxCentroidDifferenceMeters=max(ds),
        maxSourceCandidateHausdorffMeters=max(
            m[k]["candidateHausdorffMeters"]
            for m in matched
            for k in ["osm", "overture"]
        ),
        crs=cand["crs"],
        origin=scene["origin"],
        note="Matched footprints can share OSM lineage. "
        "This tests transforms, not survey accuracy.",
        objects=matched,
    )
    save(folder / "provider-alignment.json", alignment)
    ax.set_aspect("equal")
    ax.set_title(city + " | OSM: blue, Overture: orange | local metres")
    fig.savefig(folder / "provider-alignment-preview.png", dpi=130)
    plt.close(fig)
    if max(ds) > 20:
        raise ValueError("Investigate provider matching before accepting scene")
    b0 = intersections(before["buildings"], water)
    b1 = intersections(scene["buildings"], water)
    save(
        folder / "building-water-intersections.json",
        dict(
            before=b0,
            after=b1,
            buildingsIntersectingWater=len({i["building"] for i in b1}),
            intersectionArea=sum(i["area"] for i in b1),
            beforeIntersectionArea=sum(i["area"] for i in b0),
        ),
    )
    fig, axes = plt.subplots(1, 2, figsize=(14, 7), layout="constrained")
    for ax, source, over, label in zip(
        axes, [before, scene], [b0, b1], ["Phase G", "Phase G.5"], strict=True
    ):
        bad = {x["building"] for x in over}
        outline(ax, bound, "#454545")
        for w in water.values():
            ax.fill(*w.exterior.xy, color="#8cd0eb")
            for h in w.interiors:
                ax.fill(*h.xy, color="white")
        for b in source["buildings"]:
            outline(
                ax, poly(b["footprint"]), "#bd261d" if b["id"] in bad else "#565b55"
            )
        ax.set_aspect("equal")
        ax.set_title(f"{city} | {label} | {len(bad)} intersections")
    fig.savefig(folder / "scene-debug.png", dpi=140)
    plt.close(fig)
    terrain = SimpleNamespace(**scene["terrain"])
    bs = {b["id"]: b for b in before["buildings"]}
    waters = []
    traces = []
    waterunion = shapely.union_all(list(water.values()))
    terrainfaces = faces["Terrain/water-only"]
    land, landpg = footprints(terrainfaces)
    expectedland = bound.difference(waterunion)
    missing = expectedland.difference(land)
    excess = land.intersection(waterunion)
    for obj in scene["water_areas"]:
        wid = obj["id"]
        g = water[wid]
        c = cs[obj["sources"][0]]
        src = raw(c)
        _, orig = project(src)
        mesh = faces["Water/" + wid]
        mg, _ = footprints(mesh)
        yy = mesh[:, :, 2]
        wy = float(np.median(yy))
        sample = []
        for ring in [g.exterior, *g.interiors]:
            xy = shapely.get_coordinates(
                shapely.line_interpolate_point(
                    ring, np.linspace(0, ring.length, max(2, int(ring.length / 2) + 1))
                )
            )
            sample.extend(
                terrain_height(terrain, *p)
                for p in xy
                if orig.boundary.distance(Point(p)) <= 0.02
            )
        near = [
            dict(id=b["id"], base=b["ground_height_m"] + b["min_height"])
            for b in scene["buildings"]
            if g.distance(poly(b["footprint"])) <= 20
            and b["ground_height_m"] is not None
        ]
        # Source, candidate, resolved scene and actual Unity world coordinates.
        waters.append(
            dict(
                scene_id=wid,
                provider=c["provider"],
                provider_feature_id=c["provider_feature_id"],
                subtype=obj["water_type"],
                fusion_method=obj["fusion_method"],
                sourceIDs=obj["sources"],
                rawWgs84=mapping(src),
                original=info(orig),
                normalizedGeometry=c["geometry"],
                clipped=info(g),
                resolvedScene=obj["polygon"],
                mesh=info(mg),
                unityWorldXYZ=mesh[:, :, [0, 2, 1]].tolist(),
                areaSymmetricDifferenceMeters2=g.symmetric_difference(mg).area,
                outsideSelectionArea=g.difference(bound).area,
                validRepairArea=shapely.make_valid(orig).area,
                exteriorCCW=g.exterior.is_ccw,
                holeCCW=[h.is_ccw for h in g.interiors],
                waterY=wy,
                waterYRange=[float(yy.min()), float(yy.max())],
                heightMethod=obj["water_height_method"],
                shorelineSamples=len(sample),
                shorelineMin=min(sample, default=None),
                shorelineMedian=float(np.median(sample)) if sample else None,
                maxWaterAboveShoreMeters=max((wy - h for h in sample), default=None),
                nearbyBuildings=near,
                maxWaterAboveNearbyBuildingBaseMeters=max(
                    (wy - b["base"] for b in near), default=None
                ),
            )
        )
    for row in b0[:10]:
        b = bs[row["building"]]
        candidate = cs.get(b["sources"][0])
        w = next(v for v in waters if v["scene_id"] == row["water"])
        traces.append(
            dict(
                **row,
                sceneFootprint=b["footprint"],
                beforeBase=b["ground_height_m"],
                groundAudit=b["ground_audit"],
                candidateGeometry=candidate["geometry"] if candidate else None,
                rawSource=mapping(raw(candidate)) if candidate else None,
                sourceRecords=candidate["source_records"] if candidate else [],
                waterRef=w["scene_id"],
                waterY=w["waterY"],
                debugXY=list(poly(b["footprint"]).centroid.coords[0]),
                renderedAfter="Buildings/" + b["id"] in faces,
            )
        )
    save(folder / "building-water-traces.json", traces)
    waterdata = dict(
        oceanCount=sum(w["subtype"] == "ocean" for w in waters),
        riverCount=sum(w["subtype"] == "river" for w in waters),
        inlandCount=sum(w["subtype"] != "ocean" for w in waters),
        polygons=waters,
        waterOnlyCutout=dict(
            rawMissingLandArea=missing.area,
            rawTerrainInsideWaterArea=excess.area,
            missingLandAreaBeyond2cm=missing.difference(
                expectedland.boundary.buffer(0.02)
            ).area,
            terrainTrianglesRemainingInsideWater=int(
                sum(
                    shapely.area(shapely.intersection(landpg, waterunion.buffer(-0.02)))
                    > 1e-8
                )
            ),
            note="Water-only terrain without road cuts. "
            "Original DEM triangles are retessellated.",
        ),
    )
    save(folder / "water-debug.json", waterdata)
    bmeshes = {k[10:]: v for k, v in faces.items() if k.startswith("Buildings/")}
    volumes = {}
    parts = []
    outside = []
    for b in scene["buildings"]:
        if b["render_footprints"] is None:
            volumes[b["id"]] = poly(b["footprint"])
        else:
            for i, p in enumerate(b["render_footprints"]):
                volumes[b["id"] + f"/remainder/{i}"] = poly(p)
        for part in b["parts"]:
            pg = poly(part["footprint"])
            volumes[part["id"]] = pg
            parts.append(
                dict(
                    id=part["id"],
                    parent=b["id"],
                    parentIDMatches=b["id"] == part["parent_id"],
                    outsideParentArea=pg.difference(poly(b["footprint"])).area,
                )
            )
    unexpected = sorted(set(bmeshes) ^ set(volumes))
    offsets = {}
    for rid in bmeshes.keys() & volumes.keys():
        xy, _ = footprints(bmeshes[rid])
        g = volumes[rid]
        offsets[rid] = dict(
            centroidDistance=g.centroid.distance(xy.centroid),
            footprintDifferenceArea=g.symmetric_difference(xy).area,
        )
    for items, key in [
        (scene["roads"], "path"),
        (scene["buildings"], "footprint"),
        (scene["water_areas"] + scene["green_areas"], "polygon"),
    ]:
        for o in items:
            g = LineString([v[:2] for v in o[key]]) if key == "path" else poly(o[key])
            if not bound.buffer(0.001).covers(g):
                outside.append(
                    dict(
                        id=o["id"],
                        intersects=bound.intersects(g),
                        source=o.get("fusion_method"),
                    )
                )
    dups = []
    geoms = [poly(b["footprint"]) for b in scene["buildings"]]
    tree = shapely.STRtree(geoms)
    for i, b in enumerate(scene["buildings"]):
        if b["fusion_method"] != "overture_supplemental":
            continue
        for j in tree.query(geoms[i], predicate="intersects"):
            if i == j:
                continue
            ratio = geoms[i].intersection(geoms[j]).area / min(
                geoms[i].area, geoms[j].area
            )
            if ratio > 0.2:
                dups.append(
                    dict(
                        first=b["id"],
                        second=scene["buildings"][j]["id"],
                        smallerFootprintFraction=ratio,
                    )
                )
    save(
        folder / "building-audit.json",
        dict(
            fusion=fusion,
            parts=parts,
            worldMeshOffsets=offsets,
            unexpectedVolumeIDs=unexpected,
            supplementalOverlaps=dups,
            outsideSelectionBeyond1mm=outside,
        ),
    )
    roadstats = analyse_roads(scene, faces, folder, scale)
    h = np.median([b["height"] for b in scene["buildings"]])
    scale.update(
        medianBuildingHeight=h,
        medianRoadWidth=float(np.median([r["width"] for r in scene["roads"]])),
        playerBuildingRatio=(
            scale["playerHeight"] / h if scale["playerHeight"] else None
        ),
    )
    save(folder / "scale-audit.json", scale)
    summary = dict(
        city=city,
        sceneSHA256=digest,
        buildingsBefore=len(before["buildings"]),
        buildingsAfter=len(scene["buildings"]),
        intersectionsBefore=len(b0),
        intersectionsAfter=len(b1),
        areaBefore=sum(i["area"] for i in b0),
        areaAfter=sum(i["area"] for i in b1),
        matched=int(len(ds)),
        maxCentroid=max(ds),
        maxTransformError=alignment["maxSourceCandidateHausdorffMeters"],
        waterOnlyCutout=waterdata["waterOnlyCutout"],
        oceanCount=waterdata["oceanCount"],
        maxWaterMeshDifferenceArea=max(
            (w["areaSymmetricDifferenceMeters2"] for w in waters), default=None
        ),
        maxWaterAboveShore=max(
            (
                w["maxWaterAboveShoreMeters"]
                for w in waters
                if w["maxWaterAboveShoreMeters"] is not None
            ),
            default=None,
        ),
        maxPartCentroidDistance=max(
            (offsets[p["id"]]["centroidDistance"] for p in parts if p["id"] in offsets),
            default=None,
        ),
        volumeIDMismatches=len(unexpected),
        supplementalOverlaps=len(dups),
        outsideSelection=len(outside),
        roadStats=roadstats,
        scale=scale,
        failed={k: v for k, v in q["performance"].items() if k.endswith("Failed")},
    )
    save(folder / "g5-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    for name in ("moscow", "sevastopol"):
        audit(name)
