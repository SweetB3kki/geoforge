"""Convert GIS features independently; retain valid parts of multipart geometry."""

import logging
import math
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import geopandas as gpd
from shapely import force_2d, make_valid
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from app.core.config import (
    DEFAULT_BUILDING_HEIGHT,
    DEFAULT_ROAD_WIDTH,
    GREEN_RULES,
    LEVEL_HEIGHT,
    ROAD_WIDTHS,
    WATER_RULES,
)
from app.gis.coordinates import CenterSelection, LocalFrame, polygon_model
from app.gis.roads import build_network
from app.models.scene import Area, AreaType, Building, Metadata, Road, WorldScene
from app.validation.source_audit import begin_record, finish_audit

logger = logging.getLogger(__name__)


def positive_number(value: Any) -> float | None:
    """Parse positive finite scalar values without guessing compound OSM values."""
    try:
        number = float(str(value).strip().replace(",", "."))
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


def building_height_info(tags: dict[str, str]) -> tuple[float, str]:
    """Use explicit meters/feet, then levels × 3 m, then default 9 m."""
    raw = tags.get("height", "").strip().lower()
    match = re.fullmatch(r"([+]?[\d.,]+)\s*(m|meters?|metres?|ft|feet|')?", raw)
    height = positive_number(match[1]) if match else None
    if height is not None:
        return height * (0.3048 if match[2] in {"ft", "feet", "'"} else 1), "osm_height"
    levels = positive_number(tags.get("building:levels"))
    return (
        (levels * LEVEL_HEIGHT, "levels")
        if levels
        else (DEFAULT_BUILDING_HEIGHT, "fallback")
    )


def building_height(tags: dict[str, str]) -> float:
    return building_height_info(tags)[0]


def road_width(road_type: str) -> float:
    """Return configured approximate width in meters."""
    return ROAD_WIDTHS.get(road_type, DEFAULT_ROAD_WIDTH)


def area_type(tags: dict[str, str]) -> AreaType | None:
    """Classify supported polygon tags; water wins over green in conflicts."""
    if tags.get("water", "no") not in {"", "no"} or any(
        tags.get(key) in values for key, values in WATER_RULES.items()
    ):
        return AreaType.WATER
    if any(tags.get(key) in values for key, values in GREEN_RULES.items()):
        return AreaType.GREEN
    return None


def geometry_parts(geometry: BaseGeometry, kind: type) -> Iterator[BaseGeometry]:
    """Recursively unpack Multi* and GeometryCollection geometries."""
    if geometry.is_empty:
        return
    if isinstance(geometry, kind):
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from geometry_parts(part, kind)


def source_tags(row: Any) -> dict[str, str]:
    """Remove missing dataframe values and keep original textual OSM attributes."""
    tags = {}
    for key, value in row.items():
        if key == "geometry" or value is None:
            continue
        if isinstance(value, str):
            tags[str(key)] = value
        elif isinstance(value, (list, tuple)):
            tags[str(key)] = ";".join(map(str, value))
        elif isinstance(value, (int, float)) and math.isfinite(value):
            tags[str(key)] = str(value)
    return tags


def build_scene(
    features: gpd.GeoDataFrame, frame: LocalFrame, *, capture_audit: bool = True
) -> WorldScene:
    """Repair, project, clip and classify each source feature independently."""
    scene = WorldScene(
        metadata=Metadata(
            generated_at=datetime.now(UTC),
            crs=frame.crs.to_string(),
            origin_lat=frame.latitude,
            origin_lon=frame.longitude,
            selection_type=(
                "radius" if isinstance(frame.selection, CenterSelection) else "bbox"
            ),
            selection_boundary=polygon_model(frame.boundary),
        ),
        origin=frame.origin,
        bounds=frame.bounds,
    )
    if features.empty:
        scene.roads, scene.metadata.road_statistics = build_network([])
        scene.processing_audit = finish_audit(scene, []) if capture_audit else None
        logger.info("Processed empty selection: 0 buildings, 0 roads, 0 water, 0 green")
        return scene
    if features.crs is None or features.crs.to_epsg() != 4326:
        raise ValueError("Feature provider must return WGS84 (EPSG:4326) data")
    raw_highways = 0
    skipped_highways = 0
    records = []
    for index, row in features.sort_index().iterrows():
        feature_id = (
            "/".join(map(str, index)) if isinstance(index, tuple) else str(index)
        )
        tags = source_tags(row)
        record = begin_record(
            feature_id, tags, row.geometry if capture_audit else None, frame
        )
        records.append(record)
        try:
            geometry = row.geometry
            tags = source_tags(row)
            highway_feature = bool(tags.get("highway")) and (
                geometry is None or geometry.geom_type != "Point"
            )
            raw_highways += int(highway_feature)
            roads_before = len(scene.roads)
            if geometry is None or geometry.is_empty:
                raise ValueError("Missing or empty geometry")
            geometry = force_2d(geometry)
            if not geometry.is_valid:
                logger.warning("Repairing invalid geometry %s", feature_id)
                geometry = make_valid(geometry)
                scene.metadata.repaired_features += 1
                record["operations"].append("repaired")
            local = frame.to_local(geometry).intersection(frame.boundary)
            record["operations"] += ["projected", "clipped"]
            if local.is_empty:
                record["skip_reason"] = "outside_selection"
            elif hasattr(local, "geoms"):
                record["operations"].append("split")
            if tags.get("building", "no") not in {"", "no"}:
                for i, part in enumerate(geometry_parts(local, Polygon)):
                    if part.area <= 0:
                        continue
                    center = part.centroid
                    scene.buildings.append(
                        Building(
                            id=f"{feature_id}/building/{i}",
                            footprint=polygon_model(part),
                            position=(center.x, center.y, 0),
                            height=building_height(tags),
                            height_source=building_height_info(tags)[1],
                            levels=positive_number(tags.get("building:levels")),
                            building_type=tags["building"],
                            source_tags=tags,
                            source_osm_ids=[feature_id],
                            processing=list(record["operations"]),
                        )
                    )
                    record["output_ids"].append(scene.buildings[-1].id)
            if tags.get("highway") and tags.get("area") != "yes":
                for i, part in enumerate(geometry_parts(local, LineString)):
                    if part.length <= 0:
                        continue
                    scene.roads.append(
                        Road(
                            id=f"{feature_id}/road/{i}",
                            path=[(x, y, 0) for x, y in part.coords],
                            road_type=tags["highway"],
                            width=road_width(tags["highway"]),
                            source_tags=tags,
                        )
                    )
                    record["input_segment_ids"].append(scene.roads[-1].id)
            if tags.get("highway") and tags.get("area") == "yes":
                record["skip_reason"] = "filtered_by_semantic_rule"
            if highway_feature and len(scene.roads) == roads_before:
                skipped_highways += 1
                if record["skip_reason"] is None:
                    record["skip_reason"] = (
                        "non_linear_highway_geometry"
                        if local.geom_type not in {"LineString", "MultiLineString"}
                        else "too_short"
                    )
            category = area_type(tags)
            if category is not None:
                target = (
                    scene.water_areas
                    if category == AreaType.WATER
                    else scene.green_areas
                )
                for i, part in enumerate(geometry_parts(local, Polygon)):
                    if part.area > 0:
                        target.append(
                            Area(
                                id=f"{feature_id}/{category.value}/{i}",
                                polygon=polygon_model(part),
                                area_type=category,
                                source_tags=tags,
                                source_osm_ids=[feature_id],
                                processing=list(record["operations"]),
                            )
                        )
                        record["output_ids"].append(target[-1].id)
            if tags.get("natural") == "coastline":
                record["skip_reason"] = "coastal_reconstruction_not_implemented"
            elif tags.get("waterway") and not record["output_ids"]:
                record["skip_reason"] = (
                    record["skip_reason"] or "linear_waterway_not_rendered"
                )
            elif tags.get("building:part") and not record["output_ids"]:
                record["skip_reason"] = (
                    record["skip_reason"] or "building_parts_not_rendered"
                )
        except Exception:
            record["skip_reason"] = "invalid_geometry"
            if tags.get("highway"):
                skipped_highways += 1
            scene.metadata.skipped_features += 1
            logger.warning("Skipping invalid GIS feature %s", feature_id, exc_info=True)
    scene.roads, scene.metadata.road_statistics = build_network(
        scene.roads, raw_highway_ways=raw_highways, skipped=skipped_highways
    )
    scene.processing_audit = finish_audit(scene, records) if capture_audit else None
    logger.info(
        "Processed %d buildings, %d roads, %d water, %d green; skipped %d features",
        len(scene.buildings),
        len(scene.roads),
        len(scene.water_areas),
        len(scene.green_areas),
        scene.metadata.skipped_features,
    )
    return scene
