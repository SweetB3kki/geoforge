"""Machine-check A-F evidence; later phases have separate acceptance gates."""

import argparse
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

from shapely.geometry import Polygon


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify(folder, phase="F"):
    result = {"scope": f"v0.5 phases A-{phase} only", "cities": {}, "unity_tests": {}}
    suffix = "-" + phase if phase in {"E", "F"} else ""
    for platform in ("EditMode", "PlayMode"):
        root = ElementTree.parse(folder / f"{platform}{suffix}.xml").getroot()
        if root.get("result") != "Passed" or int(root.get("failed", "0")):
            raise ValueError(f"Unity {platform} not passed")
        result["unity_tests"][platform] = int(root.get("passed"))
    for city in ("sevastopol", "moscow"):
        target = folder / city
        path = target / "scene.json"
        scene, quality = read(path), read(target / "unity-quality.json")
        if quality["scene_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f"Stale Unity evidence: {city}")
        assert read(target / "scene-quality.json")["valid"]
        integration = read(target / "fusion-integration.json")
        assert integration["road_topology_unchanged"]
        assert not integration["missing_baseline_buildings"]
        stats = read(target / "unity-statistics.json")
        assert (
            sum(
                stats[k]
                for k in (
                    "buildingsFailed",
                    "roadsFailed",
                    "waterFailed",
                    "greenFailed",
                )
            )
            == 0
        )
        assert stats["playerSpawned"]
        assert stats["water"] == len(scene["water_areas"]) == len(quality["water"])
        shapes = [
            Polygon(a["polygon"]["exterior"], a["polygon"]["holes"])
            for a in scene["water_areas"]
        ]
        assert all(p.is_valid for p in shapes)
        assert (
            sum(
                a.intersection(b).area
                for i, a in enumerate(shapes)
                for b in shapes[i + 1 :]
            )
            < 0.01
        )
        for entry in quality["water"]:
            assert entry["horizontalError"] < 0.001
            assert entry["terrainProtrusionSamples"] == 0
            assert entry["outsidePolygonTriangles"] == 0
            assert entry["areaErrorSquareMeters"] < max(
                0.01, entry["polygonArea"] * 1e-6
            )
        for name in ("unity-top.png", "unity-3d.png", "unity-water-coast.png"):
            assert (target / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        if city == "sevastopol":
            oceans = [a for a in scene["water_areas"] if a["water_type"] == "ocean"]
            assert oceans and scene["terrain"]["vertical_datum"] == "EGM2008"
            for area in oceans:
                assert area["water_height_method"] == "sea_level_datum"
                assert (
                    abs(area["water_level_m"] + scene["terrain"]["height_offset_m"])
                    < 0.001
                )
        if phase in {"E", "F"}:
            assert integration["raw_dsm_unchanged"]
            expected = {}
            for building in scene["buildings"]:
                patches = building["render_footprints"]
                if patches is None:
                    expected[building["id"]] = building
                else:
                    for i, patch in enumerate(patches):
                        assert Polygon(patch["exterior"], patch["holes"]).is_valid
                        expected[f"{building['id']}/remainder/{i}"] = building
                for part in building["parts"]:
                    assert part["parent_id"] == building["id"]
                    expected[part["id"]] = part
            traces = {
                t["scene_object_id"]: t
                for t in quality["trace"]
                if t["gameObject"] != "Foundation"
            }
            assert stats["buildings"] == len(expected)
            assert stats["buildingParts"] == sum(
                len(b["parts"]) for b in scene["buildings"]
            )
            for identifier, volume in expected.items():
                trace = traces[identifier]
                assert (
                    abs(
                        trace["min_y"]
                        - volume["ground_height_m"]
                        - volume["min_height"]
                    )
                    < 0.002
                )
                assert (
                    abs(trace["max_y"] - volume["ground_height_m"] - volume["height"])
                    < 0.002
                )
            if city == "moscow":
                assert stats["buildingParts"] > 0
                assert (
                    (target / "unity-building-parts.png")
                    .read_bytes()
                    .startswith(b"\x89PNG")
                )
        if phase == "F":
            transport = scene["fusion_audit"]["transportation"]
            old_roads = {
                r["id"]: r
                for r in read(folder / "phase-e" / city / "scene.json")["roads"]
            }
            actual_roads = {r["id"]: r for r in scene["roads"]}
            for identifier, old in old_roads.items():
                actual = actual_roads[identifier]
                for key in (
                    "path",
                    "node_ids",
                    "start_node",
                    "end_node",
                    "road_category",
                    "road_type",
                    "bridge",
                    "tunnel",
                    "layer",
                    "source_tags",
                ):
                    assert actual[key] == old[key], (identifier, key)
                if old["width_source"] == "osm_width":
                    assert actual["width"] == old["width"]
            assert stats["logicalRoads"] == len(actual_roads)
            assert transport["matched_roads"] == sum(
                bool(r["transportation_matches"]) for r in scene["roads"]
            )
            assert all(
                0 <= m["confidence"] <= 1
                for r in scene["roads"]
                for m in r["transportation_matches"]
            )
        result["cities"][city] = {
            "scene_sha256": quality["scene_sha256"],
            "statistics": stats,
            "water": quality["water"],
            "integration": integration,
        }
        if phase == "F":
            result["cities"][city]["transportation"] = transport
    (folder / f"phase-{phase.lower()}-verification.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=["D", "E", "F"], default="F")
    args = parser.parse_args()
    result = verify(args.output_dir, args.phase)
    print(
        json.dumps(
            {
                "scope": result["scope"],
                "passed": True,
                "unity_tests": result["unity_tests"],
            }
        )
    )


if __name__ == "__main__":
    main()
