"""Measure vertical gaps on exact planar contacts of connected Unity road meshes."""

import argparse
import hashlib
import json
import struct
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import shapely


def read_faces(path, digest):
    data = memoryview(path.read_bytes())
    if bytes(data[:4]) != b"GFM1" or bytes(data[4:36]).hex() != digest:
        raise ValueError("Unexpected mesh format or different source scene")
    offset = 36

    def take(n):
        nonlocal offset
        if n < 0 or offset + n > len(data):
            raise ValueError("Truncated mesh export")
        offset += n
        return data[offset - n : offset]

    def count(limit):
        n = struct.unpack("<i", take(4))[0]
        if not 0 <= n <= limit:
            raise ValueError("Invalid mesh export count")
        return n

    faces = {}
    for _ in range(count(100000)):
        rid = bytes(take(count(4096))).decode()
        if rid in faces:
            raise ValueError("Duplicate mesh ID")
        triangles = np.frombuffer(take(36 * count(1000000)), dtype="<f4").reshape(
            -1, 3, 3
        )
        if not len(triangles) or not np.isfinite(triangles).all():
            raise ValueError("Empty or nonfinite road mesh")
        faces[rid] = triangles.astype(float)
    if offset != len(data):
        raise ValueError("Unexpected trailing mesh data")
    return faces


def cross(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def height(tri, xy):
    a, b, c = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    p = xy - a[:, :2]
    det = cross(b, c)
    return a[:, 2] + (cross(p, c) * b[:, 2] + cross(b, p) * c[:, 2]) / det


def measure(roads, faces):
    eligible = {
        r["id"]: r
        for r in roads
        if r["road_category"] == "automotive"
        and r["layer"] == 0
        and not r["bridge"]
        and not r["tunnel"]
        and r.get("vertical_profile")
        and r["vertical_profile"].get("surface_visible", True)
    }
    if eligible.keys() != faces.keys():
        raise ValueError("Eligible road IDs and Unity meshes differ")
    owners = defaultdict(set)
    meshes = {}
    degenerate = 0
    for rid, tri in faces.items():
        for node in eligible[rid]["node_ids"]:
            if node:
                owners[node].add(rid)
        keep = cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) != 0
        degenerate += int(np.count_nonzero(~keep))
        tri = tri[keep]
        poly = shapely.polygons(tri[:, :, :2])
        meshes[rid] = tri, poly, shapely.STRtree(poly)
    pairs = sorted(
        {p for group in owners.values() for p in combinations(sorted(group), 2)}
    )
    summary = {
        name: {"face_pairs": 0, "over_2cm": 0, "max_gap_m": None, "worst": None}
        for name in ("point", "edge", "overlap")
    }
    no_contact, failing = [], []
    for a, b in pairs:
        ta, pa, _ = meshes[a]
        tb, _, tree = meshes[b]
        measured = 0
        worst = 0.0
        for start in range(0, len(pa), 256):
            ai, bi = tree.query(pa[start : start + 256], predicate="intersects")
            if not len(ai):
                continue
            ai += start
            contacts = shapely.intersection(pa[ai], tree.geometries[bi])
            xy, indices = shapely.get_coordinates(contacts, return_index=True)
            gaps = np.abs(height(ta[ai[indices]], xy) - height(tb[bi[indices]], xy))
            if not np.isfinite(gaps).all():
                raise ValueError("Nonfinite intersection measurement")
            dims = shapely.get_dimensions(contacts)
            maxima = np.full(len(ai), -1.0)
            np.maximum.at(maxima, indices, gaps)
            for dim, name in enumerate(("point", "edge", "overlap")):
                keep = (dims == dim) & (maxima >= 0)
                if not keep.any():
                    continue
                selected = np.flatnonzero(keep[indices])
                j = selected[np.argmax(gaps[selected])]
                gap = float(gaps[j])
                bucket = summary[name]
                count = int(keep.sum())
                measured += count
                bucket["face_pairs"] += count
                bucket["over_2cm"] += int(np.count_nonzero(maxima[keep] > 0.02))
                if bucket["max_gap_m"] is None or gap > bucket["max_gap_m"]:
                    bucket.update(
                        max_gap_m=gap, worst={"roads": [a, b], "xy": xy[j].tolist()}
                    )
                worst = max(worst, gap)
        if measured == 0:
            no_contact.append([a, b])
        if worst > 0.02:
            failing.append({"roads": [a, b], "max_gap_m": worst})
    return {
        "scope": "Layer-0 automotive ground roads. Exact XY intersections of "
        "mesh faces; no snapping. No-contact pairs are unmeasured, not passes. "
        "Does not measure positive-width horizontal gaps, bridges or other categories.",
        "roads": len(faces),
        "connected_road_pairs": len(pairs),
        "degenerate_planar_faces_excluded": degenerate,
        "contacts": summary,
        "pairs_without_exact_contact": no_contact,
        "pairs_over_2cm": sorted(failing, key=lambda row: -row["max_gap_m"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    scene = parser.parse_args().scene
    raw = scene.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    export = scene.with_name("ground-road-faces.bin")
    report = measure(json.loads(raw)["roads"], read_faces(export, digest))
    report.update(
        scene_sha256=digest,
        faces_sha256=hashlib.sha256(export.read_bytes()).hexdigest(),
    )
    scene.with_name("road-contact-audit.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["contacts"], indent=2))


if __name__ == "__main__":
    main()
