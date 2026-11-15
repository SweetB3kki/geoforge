"""Conservative transport enrichment; original OSM paths and topology are immutable."""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from shapely.geometry import LineString
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree

from app.fusion.resolvers import osm_ids
from app.gis.roads import WIDTHS, classify, node_id, node_key
from app.models.candidates import ConnectorCandidate, RoadCandidate
from app.models.scene import Road


@dataclass(frozen=True)
class TransportSettings:
    proximity_m: float = 3.0
    overlap_ratio: float = 0.8
    direction_cosine: float = 0.85
    ambiguity_margin: float = 0.05
    minimum_length_m: float = 5.0
    width_coverage: float = 0.8
    enableSupplementalOvertureRoads: str = "auto"

    def __post_init__(self):
        for key in ("proximity_m", "minimum_length_m"):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) <= 0:
                raise ValueError(f"Invalid {key}")
        for key in (
            "overlap_ratio",
            "direction_cosine",
            "ambiguity_margin",
            "width_coverage",
        ):
            if (
                not math.isfinite(getattr(self, key))
                or not 0 <= getattr(self, key) <= 1
            ):
                raise ValueError(f"Invalid {key}")
        if self.enableSupplementalOvertureRoads not in {"auto", "off"}:
            raise ValueError("Supplemental roads mode must be auto/off")


def identity(road):
    return {s.split("/road/", 1)[0] for s in road.source_ids}


def direction_similarity(a, b):
    short, other = (a, b) if a.length < b.length else (b, a)
    scores = []
    for f in (0.25, 0.5, 0.75):
        at = short.length * f
        delta = min(1, short.length / 10)
        p, q = short.interpolate(at - delta), short.interpolate(at + delta)
        mid = short.interpolate(at)
        t = other.project(mid)
        u, v = other.interpolate(max(0, t - delta)), other.interpolate(
            min(other.length, t + delta)
        )
        dx, dy, ex, ey = q.x - p.x, q.y - p.y, v.x - u.x, v.y - u.y
        norm = math.hypot(dx, dy) * math.hypot(ex, ey)
        if norm > 1e-9:
            scores.append(abs((dx * ex + dy * ey) / norm))
    return min(1.0, sum(scores) / len(scores)) if scores else 0.0


def compare(line, candidate, settings):
    other = candidate.geometry
    short, long = (line, other) if line.length < other.length else (other, line)
    overlap = (
        short.intersection(long.buffer(settings.proximity_m)).length / short.length
    )
    direction = direction_similarity(line, other)
    # Directed proximity supports one logical road matched to several source segments.
    proximity = max(
        short.interpolate(f, normalized=True).distance(long)
        for f in (0, 0.25, 0.5, 0.75, 1)
    )
    return overlap, direction, proximity


def apply_width(road, matches, warnings, settings):
    line = LineString(road.path)
    intervals = []
    for candidate, _ in matches:
        for rule in candidate.attributes.width_rules:
            record = {
                "source_feature_id": candidate.provider_feature_id,
                **rule.model_dump(mode="json"),
            }
            road.width_rules.append(record)
            if rule.value > 100:
                warnings.append({"id": road.id, "reason": "width_over_100m_ignored"})
                continue
            start, end = rule.between or (0, 1)
            piece = substring(candidate.geometry, start, end, normalized=True)
            clipped = piece.intersection(line.buffer(settings.proximity_m))
            for segment in (
                [clipped]
                if clipped.geom_type == "LineString"
                else getattr(clipped, "geoms", [])
            ):
                if segment.geom_type != "LineString" or segment.length <= 0:
                    continue
                a, b = sorted(
                    (
                        line.project(segment.interpolate(0)),
                        line.project(segment.interpolate(segment.length)),
                    )
                )
                if b - a > 0.01:
                    intervals.append((a, b, rule.value, candidate.provider_feature_id))
    road.field_provenance["width"] = {
        "value": road.width,
        "source": "fallback" if road.width_source == "fallback" else "osm",
        "method": road.width_source,
        "estimated": road.width_source not in {"osm_width"},
    }
    if road.width_source == "osm_width":
        if any(abs(v - road.width) > 0.01 for _, _, v, _ in intervals):
            warnings.append(
                {
                    "id": road.id,
                    "reason": "osm_explicit_width_preserved",
                    "alternatives": sorted({v for _, _, v, _ in intervals}),
                }
            )
        return
    if not intervals:
        return
    bounds = sorted(
        {0.0, line.length, *[x for a, b, _, _ in intervals for x in (a, b)]}
    )
    weighted, coverage = [], 0.0
    conflicts = False
    for a, b in zip(bounds, bounds[1:], strict=False):
        values = sorted({v for x, y, v, _ in intervals if x <= (a + b) / 2 <= y})
        if values:
            coverage += b - a
            weighted.append((values[0], b - a))
            conflicts |= len(values) > 1
    if coverage / line.length < settings.width_coverage:
        warnings.append(
            {
                "id": road.id,
                "reason": "partial_width_coverage_not_applied",
                "coverage": coverage / line.length,
            }
        )
        return
    total, value = 0.0, weighted[-1][0]
    for candidate_value, weight in sorted(weighted):
        value = candidate_value
        total += weight
        if total >= coverage / 2:
            break
    degraded = (
        len({v for v, _ in weighted}) > 1 or coverage < line.length - 0.01 or conflicts
    )
    if degraded:
        warnings.append(
            {
                "id": road.id,
                "reason": "piecewise_width_representative",
                "coverage": coverage / line.length,
                "rule": "weighted_lower_median; smaller width in overlapping conflicts",
            }
        )
    road.width, road.width_source = value, "overture_width_rule"
    road.field_provenance["width"] = {
        "value": value,
        "source": "overture",
        "source_feature_ids": sorted({s for _, _, _, s in intervals}),
        "method": "representative_width" if degraded else "explicit_width_rule",
        "estimated": degraded,
    }


def enrich_transport(scene, batch, boundary, settings=None):
    settings = settings or TransportSettings()
    warnings, used = [], set()
    candidates = sorted(
        [
            c
            for c in batch.candidates
            if isinstance(c, RoadCandidate)
            and c.provider == "overture"
            and c.attributes.subtype == "road"
            and c.geometry.geom_type == "LineString"
            and c.geometry.is_valid
            and c.geometry.length > 0
        ],
        key=lambda c: c.candidate_id,
    )
    tree = STRtree([c.geometry for c in candidates])
    references = defaultdict(list)
    for c in candidates:
        for identifier in osm_ids(c):
            references[identifier].append(c)
    matches_by_id = {}
    for road in scene.roads:
        road.width_rules, road.connectors = [], []
        road.field_provenance = dict(road.field_provenance)
        line = LineString(road.path)
        exact = {c.candidate_id: c for sid in identity(road) for c in references[sid]}
        pool = (
            list(exact.values())
            if exact
            else [
                candidates[int(i)]
                for i in tree.query(line.buffer(settings.proximity_m))
            ]
        )
        choices = []
        for c in sorted(pool, key=lambda candidate: candidate.candidate_id):
            provenance = c.candidate_id in exact
            if (
                not provenance
                and classify(c.attributes.road_class) != road.road_category
            ):
                continue
            overlap, direction, proximity = compare(line, c, settings)
            if (
                overlap < settings.overlap_ratio
                or direction < settings.direction_cosine
                or proximity > settings.proximity_m
            ):
                if provenance:
                    warnings.append(
                        {
                            "id": road.id,
                            "source": c.provider_feature_id,
                            "reason": "provenance_geometry_mismatch",
                        }
                    )
                continue
            score = (
                0.6 * overlap
                + 0.3 * direction
                + 0.1 * (1 - min(proximity / settings.proximity_m, 1))
            )
            choices.append(
                (
                    c,
                    {
                        "source_feature_id": c.provider_feature_id,
                        "method": "provenance" if provenance else "spatial",
                        "confidence": 1.0 if provenance else score,
                        "overlap": overlap,
                        "direction": direction,
                        "proximity_m": proximity,
                    },
                )
            )
        # Multiple disjoint source segments can enrich one logical road. Overlapping
        # alternatives without provenance are ambiguous, and neither is silently chosen.
        ambiguous = set()
        for i, (a, ma) in enumerate(choices):
            for b, mb in choices[i + 1 :]:
                if (
                    ma["method"] == mb["method"] == "spatial"
                    and abs(ma["confidence"] - mb["confidence"])
                    <= settings.ambiguity_margin
                ):
                    overlap = a.geometry.intersection(
                        b.geometry.buffer(settings.proximity_m)
                    ).length / min(a.geometry.length, b.geometry.length)
                    if overlap > 0.5:
                        ambiguous.update((a.candidate_id, b.candidate_id))
        if ambiguous:
            warnings.append(
                {
                    "id": road.id,
                    "reason": "ambiguous_transport_match",
                    "candidates": sorted(ambiguous),
                }
            )
        matches = [(c, m) for c, m in choices if c.candidate_id not in ambiguous]
        matches_by_id[road.id] = matches
        road.transportation_matches = [m for _, m in matches]
        road.sources = [*sorted(identity(road)), *[c.candidate_id for c, _ in matches]]
        road.fusion_method = "transport_enriched" if matches else "osm_direct"
        for c, _ in matches:
            used.add(c.candidate_id)
            road.connectors.extend(
                {"source_feature_id": c.provider_feature_id, **r.model_dump()}
                for r in c.attributes.connectors
            )
        road.transportation_attributes = [
            {
                "source_feature_id": c.provider_feature_id,
                "attributes": c.attributes.model_dump(mode="json"),
            }
            for c, _ in matches
        ]
        road.field_provenance["transportation_class"] = {
            "value": sorted(
                {c.attributes.road_class for c, _ in matches if c.attributes.road_class}
            ),
            "source": "overture",
            "source_feature_ids": [c.provider_feature_id for c, _ in matches],
            "method": "matched_class_preserve_osm_semantics",
        }
        apply_width(road, matches, warnings, settings)
    connector_map = {
        c.provider_feature_id: c
        for c in batch.candidates
        if isinstance(c, ConnectorCandidate) and c.provider == "overture"
    }
    connector_roads = defaultdict(set)
    connector_checks = Counter()
    for road_id, matches in matches_by_id.items():
        for c, _ in matches:
            for ref in c.attributes.connectors:
                point = c.geometry.interpolate(ref.at, normalized=True)
                if not boundary.covers(point):
                    connector_checks["outside_selection"] += 1
                    continue
                conn = connector_map.get(ref.connector_id)
                if conn is None:
                    connector_checks["missing"] += 1
                    warnings.append(
                        {
                            "id": road_id,
                            "reason": "missing_connector",
                            "connector": ref.connector_id,
                        }
                    )
                elif conn.geometry.distance(point) > settings.proximity_m:
                    connector_checks["position_mismatch"] += 1
                    warnings.append(
                        {
                            "id": road_id,
                            "reason": "connector_position_mismatch",
                            "connector": ref.connector_id,
                        }
                    )
                else:
                    connector_checks["valid"] += 1
                    if (
                        LineString(
                            next(r.path for r in scene.roads if r.id == road_id)
                        ).distance(point)
                        <= settings.proximity_m
                    ):
                        connector_roads[ref.connector_id].add(road_id)
    by_id = {r.id: r for r in scene.roads}
    for connector, roads in connector_roads.items():
        if len(roads) > 1 and not set.intersection(
            *(set(by_id[r].node_ids) for r in roads)
        ):
            warnings.append(
                {
                    "id": connector,
                    "reason": "connector_not_shared_in_osm_topology",
                    "roads": sorted(roads),
                }
            )
    occupied = unary_union([LineString(r.path) for r in scene.roads])
    known_osm_ids = set().union(*(identity(r) for r in scene.roads))
    supplemental = []
    for c in candidates:
        if c.candidate_id in used or settings.enableSupplementalOvertureRoads == "off":
            continue
        if osm_ids(c) & known_osm_ids:
            warnings.append(
                {"id": c.candidate_id, "reason": "supplement_osm_identity_present"}
            )
            continue
        kind = c.attributes.road_class
        if kind not in WIDTHS or c.attributes.road_flags or c.attributes.level_rules:
            warnings.append(
                {
                    "id": c.candidate_id,
                    "reason": "supplement_unsupported_class_or_structure",
                }
            )
            continue
        clipped = c.geometry.intersection(boundary)
        pieces = (
            [clipped]
            if clipped.geom_type == "LineString"
            else getattr(clipped, "geoms", [])
        )
        for i, line in enumerate(pieces):
            if (
                line.geom_type != "LineString"
                or line.length < settings.minimum_length_m
            ):
                continue
            if (
                not occupied.is_empty
                and line.distance(occupied) <= settings.proximity_m
            ):
                warnings.append(
                    {
                        "id": c.candidate_id,
                        "reason": "supplement_near_existing_requires_topology_review",
                    }
                )
                continue
            road = Road(
                id=f"overture/{c.provider_feature_id}/road/{i}",
                path=[(x, y, 0) for x, y in line.coords],
                road_type=kind,
                road_category=classify(kind),
                width=WIDTHS[kind],
                width_source="fallback",
                source="Overture",
                source_ids=[c.candidate_id],
                source_osm_ids=sorted(osm_ids(c)),
                sources=[c.candidate_id],
                fusion_method="overture_supplemental",
                processing=["normalized", "clipped", "dedup_validated"],
            )
            road.node_ids = [node_id(node_key(road, p)) for p in road.path]
            road.start_node, road.end_node = road.node_ids[0], road.node_ids[-1]
            apply_width(road, [(c, {})], warnings, settings)
            road.field_provenance["geometry"] = {
                "value": c.candidate_id,
                "source": "overture",
                "method": "supplemental_clipped",
            }
            road.connectors = [
                {"source_feature_id": c.provider_feature_id, **r.model_dump()}
                for r in c.attributes.connectors
            ]
            supplemental.append(road)
            occupied = unary_union([occupied, line])
    scene.roads.extend(supplemental)
    stats = scene.metadata.road_statistics
    if stats:
        stats.logical_roads = len(scene.roads)
        stats.input_segments += len(supplemental)
        stats.topology_segments += len(supplemental)
        stats.nodes += len(
            {n for r in supplemental for n in (r.start_node, r.end_node)}
        )
        stats.by_category = dict(Counter(r.road_category.value for r in scene.roads))
        stats.by_type = dict(Counter(r.road_type for r in scene.roads))
        stats.service_roads = sum(r.road_type == "service" for r in scene.roads)
    if scene.processing_audit:
        scene.processing_audit["road_metrics"]["processedLogicalRoads"] = len(
            scene.roads
        )
        scene.processing_audit["road_metrics"]["supplementalOvertureRoads"] = len(
            supplemental
        )
    result = {
        "settings": vars(settings),
        "candidate_road_segments": len(candidates),
        "unmatched_segments": len(candidates) - len(used),
        "retained_width_rules": sum(len(r.width_rules) for r in scene.roads),
        "matched_roads": sum(bool(m) for m in matches_by_id.values()),
        "matched_segments": len(used),
        "widths_enriched": sum(
            r.width_source == "overture_width_rule" for r in scene.roads
        ),
        "supplemental_roads": len(supplemental),
        "connectors": dict(connector_checks),
        "warnings": warnings,
    }
    scene.fusion_audit["transportation"] = result
    scene.fusion_audit["applied_domains"].append("transportation")
    scene.fusion_audit["pending_domains"] = ["road_profiles", "surface_conflicts"]
    if scene.metadata.data_availability:
        scene.metadata.data_availability.roads.update(
            {
                "count": len(scene.roads),
                "overture_widths": result["widths_enriched"],
                "matched_roads": result["matched_roads"],
            }
        )
    return result
