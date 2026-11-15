"""Resolved buildings and water to the engine-independent scene 1.1 contract."""

import statistics

from shapely.geometry import Polygon

from app.gis.coordinates import polygon_model
from app.gis.processing import geometry_parts
from app.models.candidates import WaterCandidate
from app.models.scene import Area, AreaType, Building


def terrain_height(terrain, x, y):
    nx, ny = terrain.resolution_x, terrain.resolution_y
    gx = min(nx - 1, max(0, (x - terrain.origin[0]) / terrain.cell_size[0]))
    gy = min(ny - 1, max(0, (y - terrain.origin[1]) / terrain.cell_size[1]))
    ix, iy = min(int(gx), nx - 2), min(int(gy), ny - 2)
    u, v = gx - ix, gy - iy
    k = iy * nx + ix
    a, b, c, d = [terrain.heights[i] for i in (k, k + 1, k + nx, k + nx + 1)]
    return a + (b - a) * u + (d - b) * v if u >= v else a + (d - c) * u + (c - a) * v


def ocean_level(scene, batch, geometry):
    terrain = scene.terrain
    if terrain is not None and terrain.vertical_datum == "EGM2008":
        return -terrain.height_offset_m, "sea_level_datum"
    if terrain is not None:
        samples = []
        for candidate in batch.candidates:
            if (
                not isinstance(candidate, WaterCandidate)
                or not candidate.attributes.is_coastline
            ):
                continue
            coast = candidate.geometry.intersection(geometry.boundary.buffer(2))
            if coast.is_empty or coast.length <= 0:
                continue
            for i in range(min(256, max(2, int(coast.length / 5))) + 1):
                point = coast.interpolate(
                    i / min(256, max(2, int(coast.length / 5))), normalized=True
                )
                samples.append(terrain_height(terrain, point.x, point.y))
        if samples:
            return statistics.median(samples), "shoreline_median"
    return 0.0, "fallback"


TAG_FIELDS = {
    "height": "height",
    "floors": "building:levels",
    "min_height": "min_height",
    "min_floor": "building:min_level",
    "roof_height": "roof:height",
    "roof_shape": "roof:shape",
    "roof_color": "roof:colour",
    "roof_material": "roof:material",
    "roof_direction": "roof:direction",
    "roof_orientation": "roof:orientation",
    "facade_color": "building:colour",
    "facade_material": "building:material",
    "building_type": "building",
}


def _prefix(candidate):
    return (
        candidate.provider_feature_id
        if candidate.provider == "osm"
        else f"{candidate.provider}/{candidate.provider_feature_id}"
    )


def apply_fusion(scene, batch, fused):
    """Apply resolved footprints/attributes and deduplicated water atomically in memory.

    Prepare building volumes and ground estimates after parent/water fusion.
    Preserve legacy OSM objects that were not parent-building candidates.
    """
    old_buildings, old_water = scene.buildings, scene.water_areas
    old_tags = {
        sid: obj.source_tags
        for obj in [*old_buildings, *old_water]
        for sid in obj.source_osm_ids
    }
    buildings, waters, replacements = [], [], {}
    for item in fused.buildings:
        attrs = item.attributes
        prov = item.field_provenance["height"]
        height_source = (
            ("levels" if prov.method == "floors_times_3m" else "fallback")
            if prov.estimated
            else f"{prov.source}_height"
        )
        prefix = _prefix(item)
        resolved_tags = {
            tag: str(getattr(attrs, field))
            for field, tag in TAG_FIELDS.items()
            if getattr(attrs, field) is not None
        }
        for i, polygon in enumerate(geometry_parts(item.geometry, Polygon)):
            identifier = f"{prefix}/building/{i}"
            center = polygon.centroid
            buildings.append(
                Building(
                    id=identifier,
                    footprint=polygon_model(polygon),
                    position=(center.x, center.y, 0),
                    height=attrs.height,
                    levels=attrs.floors,
                    height_source=height_source,
                    building_type=attrs.building_type or "yes",
                    source_tags=old_tags.get(prefix, {}),
                    resolved_tags=resolved_tags,
                    sources=item.sources,
                    fusion_method=item.fusion_method,
                    field_provenance={
                        k: v.model_dump() for k, v in item.field_provenance.items()
                    },
                    source="OpenStreetMap" if item.provider == "osm" else "Overture",
                    source_osm_ids=[prefix] if item.provider == "osm" else [],
                    processing=["normalized", "fused", "clipped", *item.warnings],
                )
            )
            replacements.setdefault(prefix, []).append(identifier)
    parent_ids = {
        c.provider_feature_id
        for c in batch.candidates
        if c.kind == "building" and c.provider == "osm"
    }
    for original in old_buildings:
        if not any(sid in parent_ids for sid in original.source_osm_ids):
            original.fusion_method = "osm_legacy_preserved"
            buildings.append(original)
            for sid in original.source_osm_ids:
                replacements.setdefault(sid, []).append(original.id)
    for item in fused.water:
        prefix = _prefix(item)
        ocean = item.water_type == "ocean"
        level, method = (
            ocean_level(scene, batch, item.geometry)
            if ocean
            else (None, "polygon_median")
        )
        provenance = {k: v.model_dump() for k, v in item.field_provenance.items()}
        if level is not None:
            provenance["water_level"] = {
                "value": level,
                "source": (
                    "terrain_datum"
                    if method == "sea_level_datum"
                    else "ground_estimate"
                ),
                "method": method,
                "estimated": method != "sea_level_datum",
            }
        for i, polygon in enumerate(geometry_parts(item.geometry, Polygon)):
            identifier = f"{prefix}/water/{i}"
            waters.append(
                Area(
                    id=identifier,
                    polygon=polygon_model(polygon),
                    area_type=AreaType.WATER,
                    source="OpenStreetMap" if item.provider == "osm" else "Overture",
                    source_tags=old_tags.get(prefix, {}),
                    source_osm_ids=[prefix] if item.provider == "osm" else [],
                    processing=["normalized", "fused", "clipped", *item.warnings],
                    water_type=item.water_type,
                    water_height_method=method,
                    water_level_m=level,
                    geometry_source=item.geometry_source,
                    semantic_source=item.semantic_source,
                    sources=item.sources,
                    fusion_method=item.fusion_method,
                    strategy_used="OCEAN_HORIZONTAL" if ocean else "INLAND_HORIZONTAL",
                    field_provenance=provenance,
                )
            )
            replacements.setdefault(prefix, []).append(identifier)
    replaced_ids = {o.id for o in [*old_buildings, *old_water]}
    for record in (scene.processing_audit or {}).get("records", []):
        old_ids = record["output_ids"]
        new_ids = replacements.get(record["source_osm_id"], [])
        if not new_ids and not any(i in replaced_ids for i in old_ids):
            continue
        record["output_ids"] = [i for i in old_ids if i not in replaced_ids] + new_ids
        record["operations"].append("building_water_fusion")
        if record["status"] != "lost":
            record["status"] = "retained" if record["output_ids"] else "filtered"
            record["skip_reason"] = (
                None if record["output_ids"] else "fusion_duplicate_or_empty_geometry"
            )
    scene.buildings, scene.water_areas = buildings, waters
    scene.metadata.schema_version = "1.1"
    scene.metadata.fusion_mode = "auto"
    scene.metadata.generation_profile = "v05-building-water-fusion"
    scene.metadata.providers = [*batch.providers, *scene.metadata.providers]
    if scene.terrain is not None:
        scene.metadata.providers.append(
            {
                "provider": "copernicus",
                "status": "success",
                "source": scene.terrain.source,
                "attribution": scene.terrain.attribution,
            }
        )
    if any(c.provider == "overture" for c in batch.candidates):
        scene.metadata.attribution += (
            "; Overture Maps Foundation and upstream contributors; "
            "https://docs.overturemaps.org/attribution/"
        )
    scene.fusion_audit = {
        "metrics": fused.metrics,
        "warnings": fused.warnings,
        "normalization_diagnostics": batch.diagnostics,
        "conflicts": [c.model_dump() for c in fused.conflicts],
        "applied_domains": ["buildings", "water"],
        "pending_domains": ["building_part_rendering", "roads", "ground_adaptation"],
        "scene_counts": {"buildings": len(buildings), "water": len(waters)},
    }
    from app.fusion.buildings import polygon, prepare_buildings

    prepare_buildings(scene, batch, fused, polygon(scene.metadata.selection_boundary))
    from app.fusion.water_elevation import resolve_water_elevations

    scene.fusion_audit["water_elevation"] = resolve_water_elevations(scene, batch)
    return scene
