import pytest
from shapely.geometry import LineString

from app.gis.roads import (
    build_network,
    classify,
    enrich,
    parse_layer,
    parse_oneway,
    resolve_width,
)
from app.models.scene import Road, WorldScene


def road(id="a", path=((0, 0, 0), (10, 0, 0)), kind="residential", **tags):
    return Road(
        id=id,
        path=list(path),
        road_type=kind,
        width=6,
        source_tags={"highway": kind, **tags},
    )


@pytest.mark.parametrize(
    ("kind", "category"),
    [
        ("motorway", "automotive"),
        ("trunk_link", "automotive"),
        ("primary_link", "automotive"),
        ("residential", "automotive"),
        ("footway", "pedestrian"),
        ("path", "pedestrian"),
        ("steps", "steps"),
        ("cycleway", "cycle"),
        ("track", "track"),
        ("construction", "other"),
    ],
)
def test_classification(kind, category):
    assert classify(kind) == category


@pytest.mark.parametrize(
    ("tags", "width", "source"),
    [
        ({"width": "7.5 m", "lanes": "3"}, 7.5, "osm_width"),
        ({"width": "3,5"}, 3.5, "osm_width"),
        ({"width": "5;7", "lanes": "2"}, 6.4, "lanes"),
        ({"width": "NaN", "lanes": "2"}, 6.4, "lanes"),
        ({"width": "12 ft"}, 6, "fallback"),
        ({"lanes": "2;3"}, 6, "fallback"),
        ({"lanes": "-1", "width": "0"}, 6, "fallback"),
        ({"highway": "footway"}, 1.8, "fallback"),
        ({"highway": "cycleway"}, 2, "fallback"),
        ({"highway": "service", "service": "driveway"}, 2.5, "fallback"),
        ({"highway": "service", "service": "parking_aisle"}, 3, "fallback"),
    ],
)
def test_width(tags, width, source):
    result, origin = resolve_width({"highway": "residential", **tags})
    assert result == pytest.approx(width)
    assert origin == source


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("yes", 1),
        ("1", 1),
        ("true", 1),
        ("no", 0),
        ("-1", -1),
        ("reversible", None),
        ("garbage", None),
    ],
)
def test_oneway(value, expected):
    assert parse_oneway({"oneway": value}) == expected


def test_implicit_oneway():
    assert parse_oneway({"highway": "motorway"}) == 1
    assert parse_oneway({"junction": "roundabout"}) == 1
    assert parse_oneway({"highway": "motorway", "oneway": "no"}) == 0


@pytest.mark.parametrize(
    ("value", "expected"), [(None, 0), ("-1", -1), ("2", 2), ("a", None), ("1;2", None)]
)
def test_layer(value, expected):
    assert parse_layer(value) == expected


def test_same_name_merges_and_preserves_provenance():
    a = road(name="Main", surface="asphalt")
    b = road("b", ((10, 0, 0), (20, 0, 0)), name="Main", surface="asphalt", lit="yes")
    result, stats = build_network([b, a])
    assert len(result) == 1
    assert result[0].path == [(0, 0, 0), (10, 0, 0), (20, 0, 0)]
    assert result[0].source_ids == ["a", "b"]
    assert result[0].source_tags_by_id["b"]["lit"] == "yes"
    assert "lit" not in result[0].source_tags
    assert stats.segments_merged == 1
    assert result == build_network([a, b])[0]


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "primary"},
        {"layer": "1"},
        {"bridge": "yes"},
        {"tunnel": "yes"},
        {"name": "Other"},
        {"oneway": "yes"},
        {"width": "9"},
        {"layer": "bad"},
    ],
)
def test_incompatible_not_merged(changes):
    result, _ = build_network([road(), road("b", ((10, 0, 0), (20, 0, 0)), **changes)])
    assert len(result) == 2


def test_parallel_carriageways_remain_separate():
    roads = [
        road(kind="primary", oneway="yes"),
        road("b", ((0, 5, 0), (10, 5, 0)), kind="primary", oneway="yes"),
    ]
    result, stats = build_network(roads)
    assert len(result) == 2
    assert stats.nodes == 4


def test_shared_interior_node_splits_and_blocks_merge():
    a = road(path=((0, 0, 0), (10, 0, 0), (20, 0, 0)))
    b = road("b", ((10, 0, 0), (10, 10, 0)))
    result, stats = build_network([a, b])
    assert len(result) == 2  # Graph splits internally; renderer keeps whole polylines.
    assert stats.junctions == 1
    assert stats.topology_segments == 3


@pytest.mark.parametrize("tags", [{"layer": "1"}, {"bridge": "yes"}, {"tunnel": "yes"}])
def test_crossing_structures_not_connected(tags):
    a = road(path=((0, 0, 0), (10, 0, 0), (20, 0, 0)))
    b = road("b", ((10, -10, 0), (10, 0, 0), (10, 10, 0)), **tags)
    result, stats = build_network([a, b])
    assert len(result) == 2
    assert stats.junctions == 0


def test_crossing_without_shared_vertex_is_not_a_node():
    result, stats = build_network([road(), road("b", ((5, -5, 0), (5, 5, 0)))])
    assert len(result) == 2
    assert stats.junctions == 0


def test_direction_is_not_reversed_when_merging_oneway():
    result, _ = build_network(
        [road(oneway="yes"), road("b", ((20, 0, 0), (10, 0, 0)), oneway="yes")]
    )
    assert len(result) == 2
    result, _ = build_network(
        [road(oneway="-1"), road("b", ((10, 0, 0), (20, 0, 0)), oneway="-1")]
    )
    assert len(result) == 1 and result[0].oneway == -1


def test_chain_preserves_length_and_duplicate_cleaning():
    roads = [
        road(str(i), ((i * 10, 0, 0), (i * 10, 0, 0), ((i + 1) * 10, 0, 0)))
        for i in range(5)
    ]
    result, stats = build_network(roads)
    assert len(result) == 1
    assert LineString(result[0].path).length == 50
    assert stats.segments_merged == 4


def test_old_model_and_new_roundtrip(features, frame):
    from app.gis.processing import build_scene

    old = Road(id="old", path=[(0, 0, 0), (1, 1, 0)], road_type="footway", width=5)
    assert old.width_source == "legacy"
    assert enrich(old).road_category == "pedestrian"
    scene = build_scene(features, frame)
    assert WorldScene.model_validate_json(scene.model_dump_json()) == scene


@pytest.mark.parametrize(
    "kind", ["residential_link", "service_link", "crossing", "proposed"]
)
def test_strict_other(kind):
    assert classify(kind) == "other"


@pytest.mark.parametrize(
    "kind,tags",
    [
        ("footway", {"footway": "crossing"}),
        ("cycleway", {"cycleway": "crossing"}),
        ("path", {"crossing": "uncontrolled"}),
    ],
)
def test_crossings_keep_geometry_and_do_not_merge(kind, tags):
    inputs = [
        road(kind=kind, **tags),
        road("b", ((10, 0, 0), (20, 0, 0)), kind=kind, **tags),
    ]
    result, stats = build_network(inputs)
    assert len(result) == 2 and stats.crossings == 2
    assert all(r.road_subtype == "crossing" and r.width <= 2 for r in result)
    assert [r.path for r in result] == [r.path for r in inputs]
    assert enrich(road(kind=kind, width="4.5", **tags)).width == 4.5


@pytest.mark.parametrize(
    "first,second",
    [
        ("residential", "footway"),
        ("primary", "primary_link"),
        ("residential", "cycleway"),
        ("residential", "steps"),
        ("footway", "steps"),
    ],
)
def test_category_continuity_barriers(first, second):
    assert (
        len(
            build_network(
                [road(kind=first), road("b", ((10, 0, 0), (20, 0, 0)), kind=second)]
            )[0]
        )
        == 2
    )


@pytest.mark.parametrize(
    "service",
    ["driveway", "parking_aisle", "alley", "emergency_access", "drive-through"],
)
def test_service_subtypes(service):
    item = enrich(road(kind="service", service=service))
    assert item.road_subtype == service
    assert item.width < enrich(road()).width


def test_path_width_hierarchy():
    assert enrich(road(kind="footway")).width < enrich(road(kind="primary")).width / 3
    assert enrich(road(kind="cycleway", lanes="4")).width == 2
    assert enrich(road(kind="steps", lanes="4")).width == 1.5
    assert enrich(road(kind="primary_link")).width < enrich(road(kind="primary")).width


def test_crossing_node_does_not_create_road(frame):
    import geopandas as gpd
    from shapely.geometry import Point

    from app.gis.processing import build_scene

    features = gpd.GeoDataFrame(
        [
            {
                "highway": "crossing",
                "crossing": "traffic_signals",
                "geometry": Point(33.5, 44.6),
            }
        ],
        crs=4326,
    )
    scene = build_scene(features, frame)
    assert not scene.roads
    assert scene.metadata.road_statistics.raw_highway_ways == 0


def test_crossing_does_not_merge_into_plain_path():
    result, _ = build_network(
        [
            road(kind="footway", footway="crossing"),
            road("b", ((10, 0, 0), (20, 0, 0)), kind="footway"),
        ]
    )
    assert len(result) == 2


@pytest.mark.parametrize(
    "mode", ["FULL", "AUTOMOTIVE_ONLY", "AUTOMOTIVE_AND_PEDESTRIAN"]
)
def test_preview_filters_preserve_scene(features, frame, tmp_path, mode):
    from app.gis.processing import build_scene
    from app.visualization.preview import render_preview

    scene = build_scene(features, frame)
    scene.roads.extend(
        enrich(road(str(i), kind=kind))
        for i, kind in enumerate(["footway", "steps", "cycleway", "track"])
    )
    original = scene.model_dump_json()
    result = render_preview(scene, tmp_path / "preview.png", mode)
    assert result.read_bytes().startswith(b"\x89PNG")
    assert scene.model_dump_json() == original


def test_preview_orders_structures_and_crossings():
    from app.visualization.preview import road_draw_order

    ground = enrich(road("ground"))
    bridge = enrich(road("bridge", bridge="yes"))
    tunnel = enrich(road("tunnel", tunnel="yes"))
    elevated = enrich(road("elevated", layer="1"))
    crossing = enrich(road("crossing", kind="footway", footway="crossing"))
    assert [
        r.id
        for r in sorted(
            [elevated, ground, bridge, crossing, tunnel], key=road_draw_order
        )
    ] == ["tunnel", "ground", "crossing", "bridge", "elevated"]
