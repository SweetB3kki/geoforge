"""Building volumes, availability-driven strategy and surrounding DSM estimation."""

from collections import Counter

import numpy as np
from shapely import make_valid
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from app.fusion.resolvers import (
    FusionResult,
    FusionSettings,
    _match_buildings,
    _resolve_building,
)
from app.gis.coordinates import polygon_model
from app.gis.processing import geometry_parts
from app.models.candidates import BuildingPartCandidate
from app.models.scene import Building, BuildingAvailability, DataAvailabilityProfile

# Generic typological estimates, never advertised as measured heights.
TYPE_HEIGHTS = {
    "garage": 3.0,
    "garages": 3.0,
    "shed": 3.0,
    "hut": 3.0,
    "industrial": 8.0,
    "warehouse": 8.0,
    "apartments": 12.0,
}


def polygon(model):
    return Polygon(
        [(p[0], p[1]) for p in model.exterior],
        [[(p[0], p[1]) for p in ring] for ring in model.holes],
    )


def strategy(profile, building_type):
    if profile.parts:
        return "PARTS_EXPLICIT"
    if profile.explicit_height:
        return "EXPLICIT_HEIGHT"
    if profile.floors:
        return "FLOORS_ESTIMATED"
    return (
        "TYPE_BASED_FALLBACK" if building_type in TYPE_HEIGHTS else "GENERIC_FALLBACK"
    )


def ground_estimate(terrain, footprint, occupied, boundary):
    from app.fusion.scene_adapter import terrain_height

    if terrain is None:
        return 0.0, "flat_no_dem", {"sample_count": 0, "old_footprint_median": 0.0}
    old = sorted(
        terrain_height(terrain, x, y) for x, y in list(footprint.exterior.coords)[:-1]
    )
    old_median = old[len(old) // 2]  # Same upper median as legacy Unity PolygonHeight.
    cell = max(terrain.cell_size)
    values, points = [], []
    # Native DSM nodes outside every building avoid interpolation of roof elevations.
    radius = max(5.0, cell * 1.5)
    for scale in (1, 2, 3):
        ring = footprint.buffer(radius * scale).difference(footprint)
        x0, y0, x1, y1 = ring.bounds
        ix0 = max(0, int(np.floor((x0 - terrain.origin[0]) / terrain.cell_size[0])))
        iy0 = max(0, int(np.floor((y0 - terrain.origin[1]) / terrain.cell_size[1])))
        ix1 = min(
            terrain.resolution_x - 1,
            int(np.ceil((x1 - terrain.origin[0]) / terrain.cell_size[0])),
        )
        iy1 = min(
            terrain.resolution_y - 1,
            int(np.ceil((y1 - terrain.origin[1]) / terrain.cell_size[1])),
        )
        values, points = [], []
        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                k = iy * terrain.resolution_x + ix
                if not terrain.valid_mask[k]:
                    continue
                p = Point(
                    terrain.origin[0] + ix * terrain.cell_size[0],
                    terrain.origin[1] + iy * terrain.cell_size[1],
                )
                if not ring.covers(p) or not boundary.covers(p):
                    continue
                if len(occupied.query(p, predicate="intersects")):
                    continue
                points.append([p.x, p.y])
                values.append(terrain.heights[k])
        if len(values) >= 8:
            break
    if len(values) < 3:
        return (
            old_median,
            "footprint_median_fallback",
            {
                "sample_count": len(values),
                "old_footprint_median": old_median,
                "warning": "insufficient_surrounding_ground_samples",
            },
        )
    ground = float(np.percentile(values, 35))
    return (
        ground,
        "surrounding_p35",
        {
            "sample_count": len(values),
            "old_footprint_median": old_median,
            "new_ground": ground,
            "delta_m": ground - old_median,
            "percentile": 35,
            "ring_radius_m": radius * scale,
            "sample_min": min(values),
            "sample_max": max(values),
            "sample_points": points,
        },
    )


def prepare_buildings(scene, batch, fused, boundary):
    from app.fusion.scene_adapter import TAG_FIELDS, _prefix

    warnings = scene.fusion_audit["warnings"]
    parents = {b.id: b for b in scene.buildings}
    geometries = {b.id: polygon(b.footprint) for b in scene.buildings}
    assigned = {b.id: [] for b in scene.buildings}
    # Provider parent reference is authoritative; choose a single multipart component.
    for resolved in fused.buildings:
        choices = [
            b
            for b in scene.buildings
            if b.id.startswith(_prefix(resolved) + "/building/")
        ]
        for part in resolved.parts:
            if not choices:
                continue
            best = max(
                choices,
                key=lambda b: geometries[b.id]
                .intersection(make_valid(part.geometry))
                .area,
            )
            assigned[best.id].append(part)
    osm_parts = [
        c
        for c in batch.candidates
        if isinstance(c, BuildingPartCandidate) and c.provider == "osm"
    ]
    aliases = {}
    for part in osm_parts:
        shape = make_valid(part.geometry).intersection(boundary)
        if shape.is_empty or shape.area <= 0:
            continue
        own = f"{_prefix(part)}/building/0"
        matches = sorted(
            (g.area, identifier)
            for identifier, g in geometries.items()
            if identifier != own
            and parents[identifier].source_tags.get("building:part", "no") in ("", "no")
            and g.intersection(shape).area / shape.area >= 0.8
        )
        if matches and (len(matches) == 1 or matches[1][0] > matches[0][0] * 1.05):
            identifier = matches[0][1]
            if own in parents:
                aliases[own] = identifier
        else:
            identifier = own
            if matches:
                warnings.append(
                    {
                        "id": part.candidate_id,
                        "reason": "ambiguous_osm_part_parent_standalone",
                    }
                )
            if own not in parents:
                for i, piece in enumerate(geometry_parts(shape, Polygon)):
                    key = f"{_prefix(part)}/building/{i}"
                    center = piece.centroid
                    parent = Building(
                        id=key,
                        footprint=polygon_model(piece),
                        position=(center.x, center.y, 0),
                        height=9,
                        building_type=part.attributes.building_type or "yes",
                        height_source="fallback",
                        source_tags={
                            k: str(v)
                            for k, v in part.raw_attributes.items()
                            if v is not None
                        },
                        source_osm_ids=[part.provider_feature_id],
                        fusion_method="standalone_osm_part",
                    )
                    scene.buildings.append(parent)
                    parents[key], geometries[key], assigned[key] = parent, piece, []
            own_keys = sorted(
                k for k in parents if k.startswith(_prefix(part) + "/building/")
            )
            for key in own_keys:
                piece = shape.intersection(geometries[key])
                if piece.area > 0:
                    assigned[key].append(part.model_copy(update={"geometry": piece}))
            continue
        assigned[identifier].append(part)
    part_indices = Counter()
    for identifier, candidates in assigned.items():
        if not candidates:
            continue
        parent = parents[identifier]
        conflicts = FusionResult()
        osm = sorted(
            [c for c in candidates if c.provider == "osm"], key=lambda c: c.candidate_id
        )
        extra = sorted(
            [c for c in candidates if c.provider != "osm"], key=lambda c: c.candidate_id
        )
        matches = _match_buildings(osm, extra, FusionSettings(), conflicts)
        consumed = {other.candidate_id for other, _ in matches.values()}
        pairs = [
            (c, *matches.get(c.candidate_id, (None, "osm_part_direct"))) for c in osm
        ]
        pairs += [
            (c, None, "overture_part_direct")
            for c in extra
            if c.candidate_id not in consumed
        ]
        for base, other, method in pairs:
            geom = make_valid(base.geometry).intersection(boundary)
            resolved = _resolve_building(base, other, base, geom, method, conflicts)
            attrs = resolved.attributes
            bottom = (
                attrs.min_height
                if attrs.min_height is not None
                else (attrs.min_floor or 0) * 3
            )
            top = attrs.height
            if top <= bottom:
                warnings.append(
                    {
                        "id": base.candidate_id,
                        "reason": "invalid_part_vertical_interval",
                        "height": top,
                        "min_height": bottom,
                    }
                )
                continue
            tags = {
                tag: str(getattr(attrs, field))
                for field, tag in TAG_FIELDS.items()
                if getattr(attrs, field) is not None
            }
            # Missing style inherits; vertical dimensions remain explicit.
            tags = {
                **{
                    k: v
                    for k, v in parent.resolved_tags.items()
                    if k.startswith("roof:")
                    or k in ("building:colour", "building:material")
                },
                **tags,
            }
            provenance = {
                k: v.model_dump() for k, v in resolved.field_provenance.items()
            }
            if attrs.min_height is None:
                floor_prov = provenance.get("min_floor", {})
                provenance["min_height"] = {
                    "value": bottom,
                    "source": floor_prov.get("source", "fallback"),
                    "method": (
                        "min_floor_times_3m"
                        if attrs.min_floor is not None
                        else "ground_default"
                    ),
                    "estimated": True,
                }
            for field, tag in TAG_FIELDS.items():
                if (
                    tag in tags
                    and field not in provenance
                    and field in parent.field_provenance
                ):
                    provenance[field] = {
                        **parent.field_provenance[field],
                        "method": "parent_style_inheritance",
                    }
            height_source = (
                "levels"
                if provenance["height"]["method"] == "floors_times_3m"
                else (
                    "fallback"
                    if provenance["height"]["estimated"]
                    else provenance["height"]["source"] + "_height"
                )
            )
            for piece in geometry_parts(geom, Polygon):
                if piece.area < 0.01:
                    continue
                center = piece.centroid
                component = part_indices[_prefix(base)]
                part_indices[_prefix(base)] += 1
                child = Building(
                    id=f"{_prefix(base)}/part/{component}",
                    parent_id=identifier,
                    footprint=polygon_model(piece),
                    position=(center.x, center.y, 0),
                    height=top,
                    min_height=bottom,
                    levels=attrs.floors,
                    height_source=height_source,
                    building_type=attrs.building_type or parent.building_type,
                    resolved_tags=tags,
                    sources=resolved.sources,
                    field_provenance=provenance,
                    source=base.provider,
                    source_osm_ids=(
                        [base.provider_feature_id] if base.provider == "osm" else []
                    ),
                    source_tags=(
                        {
                            k: str(v)
                            for k, v in base.raw_attributes.items()
                            if v is not None
                        }
                        if base.provider == "osm"
                        else {}
                    ),
                    fusion_method=method,
                )
                parent.parts.append(child)
        warnings.extend(conflicts.warnings)
        scene.fusion_audit["conflicts"].extend(
            c.model_dump() for c in conflicts.conflicts
        )
        if parent.parts:
            occupied = unary_union([polygon(p.footprint) for p in parent.parts])
            parent.render_footprints = [
                polygon_model(g)
                for g in geometry_parts(
                    geometries[identifier].difference(occupied), Polygon
                )
                if g.area > 0.01
            ]
    for own, target in aliases.items():
        if parents[target].parts:
            parents[own].render_footprints = []
            parents[own].processing.append("rendered_as_part_of:" + target)
    all_shapes = [
        *geometries.values(),
        *[polygon(p.footprint) for b in scene.buildings for p in b.parts],
    ]
    occupied = STRtree(all_shapes)
    for parent in scene.buildings:
        bottom = parent.field_provenance.get("min_height", {}).get("value")
        if bottom is None:
            floor = parent.field_provenance.get("min_floor", {}).get("value")
            bottom = floor * 3 if floor is not None else 0
        if 0 <= bottom < parent.height:
            parent.min_height = bottom
        else:
            warnings.append(
                {"id": parent.id, "reason": "invalid_parent_min_height_ignored"}
            )
        ground, method, audit = ground_estimate(
            scene.terrain, geometries[parent.id], occupied, boundary
        )
        parent.ground_height_m, parent.ground_method, parent.ground_audit = (
            ground,
            method,
            audit,
        )
        for obj in [parent, *parent.parts]:
            obj.ground_height_m, obj.ground_method = ground, method
            obj.availability = BuildingAvailability(
                explicit_height=obj.height_source in ("osm_height", "overture_height"),
                floors=obj.levels is not None,
                roof_shape=bool(
                    obj.resolved_tags.get("roof:shape")
                    or obj.source_tags.get("roof:shape")
                ),
                parts=len(obj.parts),
                terrain=scene.terrain is not None,
            )
            obj.strategy_used = strategy(obj.availability, obj.building_type)
            if obj.strategy_used == "TYPE_BASED_FALLBACK" and not obj.parts:
                obj.height = max(TYPE_HEIGHTS[obj.building_type], obj.min_height + 3)
                obj.resolved_tags["height"] = str(obj.height)
                obj.field_provenance["height"] = {
                    "value": obj.height,
                    "source": "fallback",
                    "method": "type_height_table",
                    "estimated": True,
                }
            obj.field_provenance["ground_height"] = {
                "value": ground,
                "source": "copernicus_dsm" if scene.terrain else "fallback",
                "method": method,
                "estimated": True,
            }
    counts = Counter(b.strategy_used for b in scene.buildings)
    scene.metadata.data_availability = DataAvailabilityProfile(
        buildings={
            "count": len(scene.buildings),
            "explicit_height": sum(
                b.availability.explicit_height for b in scene.buildings
            ),
            "floors": sum(b.availability.floors for b in scene.buildings),
            "roof_shape": sum(b.availability.roof_shape for b in scene.buildings),
            "with_parts": sum(bool(b.parts) for b in scene.buildings),
            "parts": sum(len(b.parts) for b in scene.buildings),
            "strategies": dict(counts),
        },
        roads={
            "count": len(scene.roads),
            "explicit_width": sum(r.width_source == "osm_width" for r in scene.roads),
            "lanes": sum(r.lanes is not None for r in scene.roads),
            "connectivity": bool(scene.roads),
        },
        water={
            "inland_polygons": sum(a.water_type != "ocean" for a in scene.water_areas),
            "ocean_polygons": sum(a.water_type == "ocean" for a in scene.water_areas),
            "coastline": any(
                c.kind == "water" and c.attributes.is_coastline
                for c in batch.candidates
            ),
        },
        terrain={"DSM": scene.terrain is not None},
    )
    counts = scene.metadata.data_availability.buildings
    counts["coverage_fraction"] = {
        key: counts[key] / counts["count"] if counts["count"] else None
        for key in ("explicit_height", "floors", "roof_shape", "with_parts")
    }
    scene.fusion_audit["scene_counts"]["buildings"] = len(scene.buildings)
    scene.fusion_audit["metrics"]["resolvedPartVolumes"] = counts["parts"]
    scene.fusion_audit["metrics"]["attributeConflicts"] = len(
        scene.fusion_audit["conflicts"]
    )
    scene.fusion_audit["applied_domains"].extend(["building_parts", "building_ground"])
    scene.fusion_audit["pending_domains"] = ["roads", "surface_conflicts"]
    scene.fusion_audit["building_generation"] = (
        scene.metadata.data_availability.buildings
    )
    # Link formerly filtered OSM parts to their actual scene volumes.
    outputs = {}
    for b in scene.buildings:
        for p in b.parts:
            for sid in p.source_osm_ids:
                outputs.setdefault(sid, []).append(p.id)
    for record in (scene.processing_audit or {}).get("records", []):
        if record["source_osm_id"] in outputs:
            record["output_ids"] = sorted(
                set(record["output_ids"] + outputs[record["source_osm_id"]])
            )
            record["status"], record["skip_reason"] = "retained", None
            record["operations"].append("building_parts_resolved")
