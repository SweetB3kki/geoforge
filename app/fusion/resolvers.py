"""Deterministic building and water fusion over typed local candidates."""

from dataclasses import dataclass

from pydantic import Field
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from app.core.config import DEFAULT_BUILDING_HEIGHT, LEVEL_HEIGHT
from app.models.candidates import (
    BuildingAttributes,
    BuildingCandidate,
    BuildingPartCandidate,
    Candidate,
    CandidateBatch,
    ResolvedValue,
    WaterCandidate,
)
from app.models.scene import Model


class AttributeConflict(Model):
    object_id: str
    field: str
    kept: ResolvedValue
    alternative: ResolvedValue
    rule: str = "valid_osm_explicit_priority"


class ResolvedBuilding(Candidate):
    attributes: BuildingAttributes
    sources: list[str]
    fusion_method: str
    field_provenance: dict[str, ResolvedValue]
    parts: list[BuildingPartCandidate] = Field(default_factory=list)


class ResolvedWater(Candidate):
    water_type: str
    sources: list[str]
    fusion_method: str
    geometry_source: str
    semantic_source: str
    field_provenance: dict[str, ResolvedValue]


class FusionResult(Model):
    buildings: list[ResolvedBuilding] = Field(default_factory=list)
    water: list[ResolvedWater] = Field(default_factory=list)
    conflicts: list[AttributeConflict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)


@dataclass(frozen=True)
class FusionSettings:
    building_min_area: float = 1.0
    building_iou: float = 0.55
    building_centroid_distance: float = 15.0
    building_area_similarity: float = 0.5
    ambiguity_margin: float = 0.05
    supplemental_overlap: float = 0.2

    def __post_init__(self):
        import math

        if not all(math.isfinite(v) for v in vars(self).values()):
            raise ValueError("Fusion settings must be finite")
        if self.building_min_area <= 0 or self.building_centroid_distance <= 0:
            raise ValueError("Area and distance thresholds must be positive")
        for value in (
            self.building_iou,
            self.building_area_similarity,
            self.ambiguity_margin,
            self.supplemental_overlap,
        ):
            if not 0 <= value <= 1:
                raise ValueError("Fusion ratios must be in [0,1]")


def polygonal(geometry):
    if geometry.is_empty:
        return Polygon()
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    return unary_union([polygonal(g) for g in getattr(geometry, "geoms", [])])


def osm_ids(candidate):
    # A property-specific record must not assert footprint identity.
    return {
        s.osm_id
        for s in candidate.source_records
        if s.osm_id and s.property in (None, "", "/geometry", "geometry")
    }


def value(candidate, field, datum, method="explicit"):
    return ResolvedValue(
        value=datum,
        source=candidate.provider,
        source_feature_id=candidate.provider_feature_id,
        method=method,
    )


def common(candidate, geometry, sources, method):
    return dict(
        candidate_id=candidate.candidate_id,
        provider=candidate.provider,
        provider_feature_id=candidate.provider_feature_id,
        release=candidate.release,
        geometry=geometry,
        source_records=candidate.source_records,
        raw_attributes=candidate.raw_attributes,
        license=candidate.license,
        attribution_reference=candidate.attribution_reference,
        warnings=list(candidate.warnings),
        sources=sources,
        fusion_method=method,
    )


def _match_buildings(osm, overture, settings, output):
    choices = {}
    for building in osm:
        exact = [b for b in overture if osm_ids(building) & osm_ids(b)]
        if len(exact) == 1:
            choices[building.candidate_id] = (exact[0], "provenance_match")
            continue
        if len(exact) > 1:
            output.warnings.append(
                {
                    "id": building.candidate_id,
                    "reason": "ambiguous_provenance_match",
                    "candidates": [b.candidate_id for b in exact],
                }
            )
            continue
        if not building.geometry.is_valid:
            continue
        scores = []
        for other in overture:
            a, b = building.geometry, other.geometry
            if (
                not b.is_valid
                or a.centroid.distance(b.centroid) > settings.building_centroid_distance
            ):
                continue
            similarity = (
                min(a.area, b.area) / max(a.area, b.area) if max(a.area, b.area) else 0
            )
            if similarity < settings.building_area_similarity:
                continue
            intersection = a.intersection(b).area
            union = a.area + b.area - intersection
            iou = intersection / union if union else 0
            if iou >= settings.building_iou:
                scores.append((iou, other))
        scores.sort(key=lambda x: (-x[0], x[1].candidate_id))
        if len(scores) > 1 and scores[0][0] - scores[1][0] <= settings.ambiguity_margin:
            output.warnings.append(
                {
                    "id": building.candidate_id,
                    "reason": "ambiguous_spatial_match",
                    "candidates": [b.candidate_id for _, b in scores],
                }
            )
        elif scores:
            choices[building.candidate_id] = (scores[0][1], "spatial_match")
    # Avoid traversal-order-dependent many-to-one attribute assignment.
    reverse = {}
    for identifier, (other, _) in choices.items():
        reverse.setdefault(other.candidate_id, []).append(identifier)
    for identifier, owners in reverse.items():
        if len(owners) > 1:
            output.warnings.append(
                {
                    "id": identifier,
                    "reason": "ambiguous_many_to_one",
                    "candidates": owners,
                }
            )
            for owner in owners:
                choices.pop(owner)
    return choices


def _resolve_building(base, other, geometry_source, geometry, match_method, output):
    values = base.attributes.model_dump()
    provenance = {
        name: value(base, name, datum)
        for name, datum in values.items()
        if datum is not None
    }
    if other is not None:
        for name, datum in other.attributes.model_dump().items():
            if datum is None or name in {"parent_building_id", "has_parts"}:
                continue
            if values[name] is None:
                values[name] = datum
                provenance[name] = value(
                    other, name, datum, "missing_attribute_enrichment"
                )
            elif values[name] != datum:
                output.conflicts.append(
                    AttributeConflict(
                        object_id=base.candidate_id,
                        field=name,
                        kept=provenance[name],
                        alternative=value(other, name, datum),
                    )
                )
    if values["height"] is None:
        floors = values["floors"]
        values["height"] = (
            floors * LEVEL_HEIGHT if floors is not None else DEFAULT_BUILDING_HEIGHT
        )
        source = provenance.get("floors")
        provenance["height"] = ResolvedValue(
            value=values["height"],
            source=source.source if source else "fallback",
            source_feature_id=source.source_feature_id if source else None,
            method="floors_times_3m" if source else "generic_9m",
            estimated=True,
        )
    provenance["geometry"] = value(
        geometry_source,
        "geometry",
        geometry_source.candidate_id,
        "source_geometry_reference_clipped",
    )
    sources = [base.candidate_id] + ([other.candidate_id] if other else [])
    resolved = ResolvedBuilding(
        **common(base, geometry, sources, match_method),
        attributes=BuildingAttributes(**values),
        field_provenance=provenance,
    )
    if geometry_source is not base:
        resolved.warnings.append("invalid_osm_geometry_replaced_by_matched_overture")
    return resolved


def fuse_buildings(batch, boundary, settings, output):
    osm = [
        c
        for c in batch.candidates
        if isinstance(c, BuildingCandidate) and c.provider == "osm"
    ]
    overture = [
        c
        for c in batch.candidates
        if isinstance(c, BuildingCandidate) and c.provider == "overture"
    ]
    osm.sort(key=lambda c: c.candidate_id)
    overture.sort(key=lambda c: c.candidate_id)
    matches = _match_buildings(osm, overture, settings, output)
    consumed, parent_map = set(), {}
    for base in osm:
        other, method = matches.get(base.candidate_id, (None, "osm_direct"))
        geometry_source = base
        if not base.geometry.is_valid and other is not None and other.geometry.is_valid:
            geometry_source = other
        geometry = polygonal(
            make_valid(geometry_source.geometry).intersection(boundary)
        )
        if geometry.is_empty or geometry.area <= 0:
            output.warnings.append(
                {
                    "id": base.candidate_id,
                    "reason": "building_empty_after_clip",
                }
            )
            continue
        resolved = _resolve_building(
            base, other, geometry_source, geometry, method, output
        )
        if not geometry_source.geometry.is_valid:
            resolved.warnings.append("source_geometry_repaired")
        output.buildings.append(resolved)
        if other:
            consumed.add(other.candidate_id)
            parent_map[other.provider_feature_id] = resolved
    for base in overture:
        if base.candidate_id in consumed:
            continue
        if not base.geometry.is_valid:
            output.warnings.append(
                {"id": base.candidate_id, "reason": "invalid_supplemental_geometry"}
            )
            continue
        geometry = polygonal(base.geometry.intersection(boundary))
        if geometry.area < settings.building_min_area:
            continue
        # An uncorroborated machine footprint in mapped surface water is an
        # observation, not sufficient evidence to generate a generic building.
        # Keep the full candidate for review; never cut its footprint or move water.
        if (
            base.source_records
            and all(
                (s.dataset or "").casefold() == "microsoft ml buildings"
                for s in base.source_records
            )
            and not any(base.attributes.model_dump(exclude_none=True).values())
            and not any(
                base.raw_attributes.get(k) for k in ("names", "class", "subtype")
            )
            and not any(
                isinstance(part, BuildingPartCandidate)
                and part.attributes.parent_building_id == base.provider_feature_id
                for part in batch.candidates
            )
        ):
            independent_water = [
                w
                for w in output.water
                if w.geometry_source == "osm" and w.geometry.intersects(geometry)
            ]
            if independent_water:
                covered = (
                    geometry.intersection(
                        unary_union([w.geometry for w in independent_water])
                    ).area
                    / geometry.area
                )
                if covered >= 0.95:
                    output.warnings.append(
                        {
                            "id": base.candidate_id,
                            "reason": "unconfirmed_ml_building_in_water",
                            "water_candidates": [
                                w.candidate_id for w in independent_water
                            ],
                            "water_fraction": covered,
                        }
                    )
                    continue
        overlaps = [b for b in output.buildings if b.geometry.intersects(geometry)]
        occupied = unary_union([b.geometry for b in overlaps])
        if not occupied.is_empty and (
            geometry.intersection(occupied).area / geometry.area
            > settings.supplemental_overlap
            or any(
                geometry.intersection(b.geometry).area / b.geometry.area
                > settings.supplemental_overlap
                for b in overlaps
            )
        ):
            output.warnings.append(
                {"id": base.candidate_id, "reason": "supplemental_overlap_rejected"}
            )
            continue
        resolved = _resolve_building(
            base, None, base, geometry, "overture_supplemental", output
        )
        output.buildings.append(resolved)
        parent_map[base.provider_feature_id] = resolved
    for part in sorted(
        (
            c
            for c in batch.candidates
            if isinstance(c, BuildingPartCandidate) and c.provider == "overture"
        ),
        key=lambda c: c.candidate_id,
    ):
        parent = parent_map.get(part.attributes.parent_building_id)
        if parent is None:
            output.warnings.append(
                {"id": part.candidate_id, "reason": "unresolved_part_parent"}
            )
        else:
            parent.parts.append(part)
    output.metrics["matchedBuildings"] = len(consumed)
    output.metrics["overtureSupplementalBuildings"] = sum(
        b.fusion_method == "overture_supplemental" for b in output.buildings
    )


def fuse_water(batch, boundary, output):
    candidates = [
        c
        for c in batch.candidates
        if isinstance(c, WaterCandidate) and c.attributes.is_surface
    ]
    candidates.sort(
        key=lambda c: (
            (
                0
                if c.provider == "osm"
                else 1 if c.attributes.water_type == "ocean" else 2
            ),
            c.candidate_id,
        )
    )
    occupied = Polygon()
    preserved_osm = [
        c for c in candidates if c.provider == "osm" and c.geometry.is_valid
    ]
    for candidate in candidates:
        if candidate.provider == "overture" and any(
            osm_ids(candidate) & osm_ids(existing)
            and candidate.geometry.intersects(existing.geometry)
            for existing in preserved_osm
        ):
            output.warnings.append(
                {
                    "id": candidate.candidate_id,
                    "reason": "duplicate_water_source_preserve_osm",
                }
            )
            continue
        if not candidate.geometry.is_valid:
            output.warnings.append(
                {"id": candidate.candidate_id, "reason": "water_geometry_repaired"}
            )
        geometry = polygonal(make_valid(candidate.geometry)).intersection(boundary)
        if geometry.is_empty:
            continue
        original_area = geometry.area
        geometry = polygonal(geometry.difference(occupied))
        if geometry.is_empty or geometry.area < 0.01:
            output.warnings.append(
                {"id": candidate.candidate_id, "reason": "duplicate_water_coverage"}
            )
            continue
        method = (
            "osm_direct"
            if candidate.provider == "osm"
            else (
                "overture_ocean"
                if candidate.attributes.water_type == "ocean"
                else "overture_fallback"
            )
        )
        water_type = candidate.attributes.water_type or "water"
        resolved = ResolvedWater(
            **common(candidate, geometry, [candidate.candidate_id], method),
            water_type=water_type,
            geometry_source=candidate.provider,
            semantic_source=candidate.provider,
            field_provenance={
                "geometry": value(
                    candidate,
                    "geometry",
                    candidate.candidate_id,
                    "source_geometry_reference_clipped",
                ),
                "water_type": value(candidate, "water_type", water_type),
            },
        )
        if geometry.area < original_area - 0.01:
            resolved.warnings.append("existing_water_coverage_subtracted")
        output.water.append(resolved)
        occupied = occupied.union(geometry)


def resolve(batch: CandidateBatch, boundary, settings: FusionSettings | None = None):
    settings = settings or FusionSettings()
    output = FusionResult()
    fuse_water(batch, boundary, output)
    fuse_buildings(batch, boundary, settings, output)
    output.metrics.update(
        {
            "attributeConflicts": len(output.conflicts),
            "attachedBuildingParts": sum(len(b.parts) for b in output.buildings),
            "oceanPolygonCount": sum(w.water_type == "ocean" for w in output.water),
            "waterAreaM2": sum(w.geometry.area for w in output.water),
            "fallbackHeights": sum(
                b.field_provenance["height"].source == "fallback"
                for b in output.buildings
            ),
            "overtureEnrichedHeights": sum(
                b.field_provenance["height"].source == "overture"
                and not b.field_provenance["height"].estimated
                and b.provider == "osm"
                for b in output.buildings
            ),
        }
    )
    original_osm = [
        c
        for c in batch.candidates
        if isinstance(c, BuildingCandidate) and c.provider == "osm"
    ]
    output.metrics["osmFallbackHeightsBefore"] = sum(
        c.attributes.height is None and c.attributes.floors is None
        for c in original_osm
    )
    output.metrics["osmFallbackHeightsAfter"] = sum(
        b.provider == "osm" and b.field_provenance["height"].source == "fallback"
        for b in output.buildings
    )
    output.metrics["supplementalFallbackHeights"] = sum(
        b.provider == "overture" and b.field_provenance["height"].source == "fallback"
        for b in output.buildings
    )
    return output
