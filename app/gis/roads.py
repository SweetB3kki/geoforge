"""Road semantics and conservative vertex-based topology; no geometric noding."""

import hashlib
import logging
import math
import re
from collections import Counter, defaultdict

from app.models.scene import Road, RoadCategory, RoadStatistics

logger = logging.getLogger(__name__)
AUTOMOTIVE = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "living_street",
    "unclassified",
    "service",
}
LINKS = {
    f"{kind}_link" for kind in ("motorway", "trunk", "primary", "secondary", "tertiary")
}
WIDTHS = {
    "motorway": 12.0,
    "trunk": 11.0,
    "primary": 10.0,
    "secondary": 8.0,
    "tertiary": 7.0,
    "residential": 6.0,
    "living_street": 4.0,
    "unclassified": 5.0,
    "service": 4.0,
    "pedestrian": 3.0,
    "footway": 1.8,
    "path": 1.2,
    "steps": 1.5,
    "cycleway": 2.0,
    "track": 3.0,
}
SERVICE_WIDTHS = {
    "parking_aisle": 3.0,
    "driveway": 2.5,
    "alley": 3.0,
    "emergency_access": 3.0,
    "drive-through": 2.5,
}
LANE_WIDTH = 3.2


def classify(road_type: str) -> RoadCategory:
    """Include link ramps in automotive while keeping non-motor paths distinct."""
    if road_type in AUTOMOTIVE | LINKS:
        return RoadCategory.AUTOMOTIVE
    if road_type in {"pedestrian", "footway", "path"}:
        return RoadCategory.PEDESTRIAN
    if road_type == "cycleway":
        return RoadCategory.CYCLE
    if road_type == "steps":
        return RoadCategory.STEPS
    if road_type == "track":
        return RoadCategory.TRACK
    return RoadCategory.OTHER


def subtype(tags: dict[str, str]) -> str | None:
    kind = tags.get("highway", "")
    if classify(kind) in {RoadCategory.PEDESTRIAN, RoadCategory.CYCLE} and (
        tags.get("footway") == "crossing"
        or tags.get("cycleway") == "crossing"
        or tags.get("crossing", "").strip().lower() not in {"", "no", "false", "0"}
    ):
        return "crossing"
    if kind == "service":
        return tags.get("service")
    if kind in LINKS:
        return "link"
    return None


def parse_lanes(value: str | None) -> int | None:
    if value and re.fullmatch(r"[1-9]\d?", value.strip()):
        result = int(value)
        return result if result <= 20 else None
    return None


def parse_layer(value: str | None) -> int | None:
    if value is None:
        return 0
    if re.fullmatch(r"[+-]?\d{1,3}", value.strip()):
        return int(value)
    return None  # Unknown layers are never joined to any other source.


def parse_oneway(tags: dict[str, str]) -> int | None:
    value = tags.get("oneway", "").strip().lower()
    if value in {"yes", "true", "1"}:
        return 1
    if value in {"no", "false", "0"}:
        return 0
    if value in {"-1", "reverse"}:
        return -1
    if value:
        return None
    if tags.get("highway") == "motorway" or tags.get("junction") == "roundabout":
        return 1
    return 0


def structure(value: str | None) -> bool:
    return value is not None and value.strip().lower() not in {"", "no", "false", "0"}


def resolve_width(tags: dict[str, str]) -> tuple[float, str]:
    """Accept one positive metric width, then integral lane count, then type rules."""
    value = tags.get("width", "").strip().lower()
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:m|metres?|meters?)?", value)
    if match:
        width = float(match[1].replace(",", "."))
        if 0 < width <= 100:
            return width, "osm_width"
    if subtype(tags) == "crossing":
        return (2.0 if tags.get("highway") == "cycleway" else 1.8), "fallback"
    lanes = parse_lanes(tags.get("lanes"))
    if (
        lanes is not None
        and classify(tags.get("highway", "")) == RoadCategory.AUTOMOTIVE
    ):
        return lanes * LANE_WIDTH, "lanes"
    kind = tags.get("highway", "")
    if kind == "service":
        return SERVICE_WIDTHS.get(tags.get("service"), WIDTHS["service"]), "fallback"
    if kind in LINKS:
        return 4.0, "fallback"
    return WIDTHS.get(kind, 2.0), "fallback"


def enrich(road: Road) -> Road:
    """Add semantics to a raw or legacy road without changing its path."""
    tags = {**road.source_tags, "highway": road.road_type}
    width, source = resolve_width(tags)
    return road.model_copy(
        update={
            "width": width,
            "width_source": source,
            "road_category": classify(road.road_type),
            "road_subtype": subtype(tags),
            "lanes": parse_lanes(tags.get("lanes")),
            "oneway": parse_oneway(tags),
            "name": tags.get("name"),
            "ref": tags.get("ref"),
            "surface": tags.get("surface"),
            "bridge": structure(tags.get("bridge")),
            "tunnel": structure(tags.get("tunnel")),
            "layer": parse_layer(tags.get("layer")),
            "source_ids": road.source_ids or [road.id],
            "source_tags_by_id": road.source_tags_by_id or {road.id: road.source_tags},
        }
    )


def node_key(road: Road, point: tuple) -> tuple:
    # Same original OSM vertices transform identically. A micrometer key handles
    # floating arithmetic; this does not snap nearby carriageways together.
    level = road.layer if road.layer is not None else road.id
    return (*(round(v, 6) for v in point), level, road.bridge, road.tunnel)


def node_id(key: tuple) -> str:
    return "node/" + hashlib.sha256(repr(key).encode()).hexdigest()[:16]


def compatible(a: Road, b: Road) -> bool:
    """Conservative exact type/name/ref/surface semantics, width tolerance 0.25 m."""

    def normalized(value: str | None) -> str:
        return " ".join((value or "").casefold().split())

    return (
        a.road_type == b.road_type
        and a.road_category == b.road_category
        and a.road_subtype == b.road_subtype
        and a.road_subtype != "crossing"
        and a.oneway is not None
        and a.oneway == b.oneway
        and a.layer is not None
        and a.layer == b.layer
        and a.bridge == b.bridge
        and a.tunnel == b.tunnel
        and normalized(a.name) == normalized(b.name)
        and normalized(a.ref) == normalized(b.ref)
        and a.surface == b.surface
        and a.lanes == b.lanes
        and a.width_source == b.width_source
        and abs(a.width - b.width) <= 0.25
        and a.source_tags.get("service") == b.source_tags.get("service")
        and a.source_tags.get("junction") == b.source_tags.get("junction")
    )


def build_network(
    roads: list[Road],
    *,
    raw_highway_ways: int | None = None,
    skipped: int = 0,
) -> tuple[list[Road], RoadStatistics]:
    """Build shared-vertex connectivity; merge compatible degree-two chains only."""
    inputs = []
    for road in sorted(roads, key=lambda r: r.id):
        cleaned = [road.path[0]]
        for point in road.path[1:]:
            if math.dist(cleaned[-1], point) > 1e-6:
                cleaned.append(point)
        if len(cleaned) < 2:
            skipped += 1
            continue
        inputs.append(enrich(road.model_copy(update={"path": cleaned})))
    owners: dict[tuple, set[int]] = defaultdict(set)
    for i, road in enumerate(inputs):
        for point in road.path:
            owners[node_key(road, point)].add(i)
    # Graph edges are split at shared interior vertices, but rendering retains
    # the input polyline across its own intersections (no gratuitous extra meshes).
    topology_segments = len(inputs)
    adjacency: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
    for i, road in enumerate(inputs):
        adjacency[node_key(road, road.path[0])].append((i, 0))
        adjacency[node_key(road, road.path[-1])].append((i, -1))
        for point in road.path[1:-1]:
            key = node_key(road, point)
            if len(owners[key]) > 1:
                topology_segments += 1
                adjacency[key].extend([(i, 1), (i, 1)])
    visited: set[int] = set()
    output = []
    for seed, original in enumerate(inputs):
        if seed in visited:
            continue
        visited.add(seed)
        path = list(original.path)
        chain = [original]
        for at_start in (False, True):
            while True:
                point = path[0] if at_start else path[-1]
                edges = adjacency[node_key(original, point)]
                if len(edges) != 2:
                    break
                candidates = [(i, side) for i, side in edges if i not in visited]
                if len(candidates) != 1:
                    break
                index, side = candidates[0]
                other = inputs[index]
                if not compatible(original, other):
                    break
                reverse = (side == 0) if at_start else (side == -1)
                if reverse and original.oneway != 0:
                    break
                oriented = list(reversed(other.path)) if reverse else list(other.path)
                # Avoid connecting two arms of a hairpin into an unrelated chain.
                u = (path[0], path[1]) if at_start else (path[-1], path[-2])
                v = (
                    (oriented[-1], oriented[-2])
                    if at_start
                    else (oriented[0], oriented[1])
                )
                first = [u[1][k] - u[0][k] for k in range(2)]
                second = [v[1][k] - v[0][k] for k in range(2)]
                cosine = sum(a * b for a, b in zip(first, second, strict=True)) / (
                    math.hypot(*first) * math.hypot(*second)
                )
                if (
                    cosine > 0.5
                ):  # Interior angle <60 degrees: retain separate segments.
                    break
                path = oriented[:-1] + path if at_start else path + oriented[1:]
                visited.add(index)
                chain.append(other)
        all_ids = sorted({source_id for item in chain for source_id in item.source_ids})
        provenance = {k: v for item in chain for k, v in item.source_tags_by_id.items()}
        common = {
            k: v
            for k, v in original.source_tags.items()
            if all(item.source_tags.get(k) == v for item in chain)
        }
        identifier = (
            original.id
            if len(chain) == 1
            else "logical/"
            + hashlib.sha256(
                "|".join(sorted(item.id for item in chain)).encode()
            ).hexdigest()[:20]
        )
        output.append(
            original.model_copy(
                update={
                    "id": identifier,
                    "path": path,
                    "source_ids": all_ids,
                    "source_tags_by_id": provenance,
                    "source_tags": common,
                    "width": sum(item.width for item in chain) / len(chain),
                    "start_node": node_id(node_key(original, path[0])),
                    "end_node": node_id(node_key(original, path[-1])),
                    "node_ids": [node_id(node_key(original, p)) for p in path],
                }
            )
        )
    stats = RoadStatistics(
        raw_highway_ways=(
            raw_highway_ways if raw_highway_ways is not None else len(roads)
        ),
        input_segments=len(roads),
        topology_segments=topology_segments,
        logical_roads=len(output),
        segments_merged=len(inputs) - len(output),
        segments_skipped=skipped,
        nodes=len(adjacency),
        junctions=sum(len(edges) > 2 for edges in adjacency.values()),
        by_category=dict(Counter(road.road_category.value for road in output)),
        by_type=dict(Counter(road.road_type for road in output)),
        crossings=sum(r.road_subtype == "crossing" for r in output),
        service_roads=sum(r.road_type == "service" for r in output),
    )
    logger.info("Road topology: %s", stats.model_dump())
    for road in output[:10]:
        logger.debug(
            "Road %s highway=%s category=%s subtype=%s width=%s "
            "layer=%s bridge=%s tunnel=%s",
            road.id,
            road.road_type,
            road.road_category,
            road.road_subtype,
            road.width,
            road.layer,
            road.bridge,
            road.tunnel,
        )
    return sorted(output, key=lambda r: r.id), stats
