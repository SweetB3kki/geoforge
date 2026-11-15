"""Resolve water levels in scene metres; never modify source DSM or XY geometry."""

import math

import numpy as np
import shapely
from shapely.geometry import Polygon


def polygon(model):
    return Polygon(
        [p[:2] for p in model.exterior], [[p[:2] for p in r] for r in model.holes]
    )


def robust_level(kind, shoreline, interior, datum=None, offset=0):
    """A horizontal estimate constrained by measured shore, not a fitted DTM.

    High DSM objects cannot raise the shore constraint. A low shore measurement
    remains an upper bound: rejecting it would silently permit flooding. Missing
    shore measurements are explicitly unavailable, never sampled on a clip edge.
    """
    if kind in {"ocean", "sea"} and datum == "EGM2008":
        return -offset, "sea_level_datum", []
    if not shoreline:
        return None, "unavailable_no_shoreline", ["no_physical_shoreline_samples"]
    shore = np.asarray(shoreline, dtype=float)
    q25, q75 = np.percentile(shore, [25, 75])
    ceiling = q75 + 1.5 * max(q75 - q25, 0.05)
    clean = shore[shore <= ceiling]
    warnings = ["DSM_estimate_not_surveyed_water_level"]
    if len(clean) != len(shore):
        warnings.append("high_shoreline_DSM_outliers_rejected")
    if kind in {"ocean", "sea"}:
        estimate = float(np.percentile(clean, 10))
        method = "coastal_lower_decile_shore_constrained"
    elif kind == "river":
        estimate = float(np.percentile(clean, 10))
        method = "river_local_reach_shore_constrained"
        if float(np.ptp(clean)) > 1:
            warnings.append("horizontal_reach_cannot_model_longitudinal_water_slope")
    elif kind in {"lake", "reservoir", "pond"}:
        samples = [*clean, *(h for h in interior if h <= ceiling)]
        estimate = float(np.percentile(samples, 20))
        method = "standing_water_lower_quintile_shore_constrained"
    else:
        estimate = float(np.percentile(clean, 20))
        method = "inland_unknown_shore_constrained"
        warnings.append("water_subtype_has_no_independent_level_evidence")
    level = min(estimate, float(min(shore)))
    if estimate - level > 1:
        warnings.append("shore_constraint_below_robust_estimate_requires_review")
    return level, method, warnings


def resolve_water_elevations(scene, batch, spacing=2.0):
    from app.fusion.scene_adapter import terrain_height

    terrain = scene.terrain
    if terrain is None:
        return {"status": "unavailable", "reason": "no_terrain", "bodies": []}
    boundary = polygon(scene.metadata.selection_boundary)
    all_water = shapely.union_all([polygon(w.polygon) for w in scene.water_areas])
    candidates = {c.candidate_id: c for c in batch.candidates}
    rows = []

    def sample(point):
        if not boundary.covers(point):
            return None
        gx = (point.x - terrain.origin[0]) / terrain.cell_size[0]
        gy = (point.y - terrain.origin[1]) / terrain.cell_size[1]
        ix, iy = math.floor(gx), math.floor(gy)
        if (
            ix < 0
            or iy < 0
            or ix >= terrain.resolution_x - 1
            or iy >= terrain.resolution_y - 1
        ):
            return None
        k = iy * terrain.resolution_x + ix
        if not all(
            terrain.valid_mask[j]
            for j in (k, k + 1, k + terrain.resolution_x, k + terrain.resolution_x + 1)
        ):
            return None
        return terrain_height(terrain, point.x, point.y)

    for water in scene.water_areas:
        geometry = polygon(water.polygon)
        source = next(
            (
                candidates[k]
                for k in water.sources
                if k in candidates and candidates[k].provider == water.geometry_source
            ),
            None,
        )
        # Source boundary before selection clipping: never call the bbox a shore.
        if water.water_type in {"ocean", "sea"}:
            edges = [
                c.geometry.intersection(geometry.buffer(2))
                for c in batch.candidates
                if c.kind == "water" and c.attributes.is_coastline
            ]
            shore = shapely.union_all(edges)
        else:
            shore = (
                source.geometry.boundary if source is not None else geometry.boundary
            )
            shore = shore.intersection(geometry.buffer(0.001)).intersection(boundary)
        coords, heights, near, interior = [], [], [], []
        for line in shapely.get_parts(shore):
            if line.geom_type not in {"LineString", "LinearRing"} or line.length == 0:
                continue
            count = max(1, math.ceil(line.length / spacing))
            for i in range(count + 1):
                point = line.interpolate(i / count, normalized=True)
                h = sample(point)
                if h is not None:
                    coords.append([point.x, point.y])
                    heights.append(h)
        step = max(terrain.cell_size)
        xmin, ymin, xmax, ymax = geometry.buffer(step).bounds
        for y in np.arange(ymin, ymax + step, step):
            for x in np.arange(xmin, xmax + step, step):
                point = shapely.Point(x, y)
                if point.distance(geometry) > step:
                    continue
                h = sample(point)
                if h is None:
                    continue
                if geometry.covers(point):
                    interior.append(h)
                elif not all_water.covers(point):
                    near.append(h)
        level, method, warnings = robust_level(
            water.water_type,
            heights,
            interior,
            terrain.vertical_datum,
            terrain.height_offset_m,
        )
        rows.append(
            dict(
                id=water.id,
                water_type=water.water_type,
                height_m=level,
                height_method=method,
                shoreline_sample_count=len(heights),
                shoreline_min=min(heights, default=None),
                shoreline_max=max(heights, default=None),
                shoreline_median=float(np.median(heights)) if heights else None,
                nearby_terrain_median=float(np.median(near)) if near else None,
                nearby_terrain_min=min(near, default=None),
                nearby_terrain_max=max(near, default=None),
                vertical_datum_info=dict(
                    datum=terrain.vertical_datum,
                    height_offset_m=terrain.height_offset_m,
                    units="local_metres",
                ),
                warnings=warnings,
                sources=water.sources,
                shoreline_xy=coords,
                shoreline_heights=heights,
                interior_sample_count=len(interior),
                logical_body=[water.id],
            )
        )

    # Only connect touching pieces with the same source and type. A shared name
    # or a disconnected multipart feature alone is not proof of equal water level.
    groups = [{i} for i in range(len(rows))]
    for i, water in enumerate(scene.water_areas):
        for j in range(i):
            other = scene.water_areas[j]
            if (
                water.water_type == other.water_type
                and set(water.sources) & set(other.sources)
                and polygon(water.polygon).intersects(polygon(other.polygon))
            ):
                a = next(g for g in groups if i in g)
                b = next(g for g in groups if j in g)
                if a is not b:
                    a.update(b)
                    groups.remove(b)
    for group in groups:
        selected = [rows[i] for i in sorted(group)]
        levels = [r["height_m"] for r in selected if r["height_m"] is not None]
        if not levels:
            continue
        level = min(levels)
        for i in group:
            row = rows[i]
            row["height_m"] = level
            row["logical_body"] = [r["id"] for r in selected]
            water = scene.water_areas[i]
            water.water_level_m = level
            water.water_height_method = row["height_method"]
            water.field_provenance["water_level"] = dict(
                value=level,
                source=(
                    "terrain_datum"
                    if row["height_method"] == "sea_level_datum"
                    else "ground_estimate"
                ),
                method=row["height_method"],
                estimated=row["height_method"] != "sea_level_datum",
            )
            water.field_provenance["water_elevation_audit"] = row
    return dict(
        status="estimated",
        bodies=rows,
        waterBodiesChecked=len(groups),
        note="Shore is an upper constraint; cliff banks need not equal water level.",
    )
