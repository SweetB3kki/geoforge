"""Explicit provider mappings; preserve raw values and diagnose every degradation."""

import math
import re
from datetime import date, datetime

import numpy as np
import pandas as pd
from pydantic import ValidationError
from shapely import force_2d, get_coordinates
from shapely.errors import GEOSException

from app.gis.coordinates import LocalFrame
from app.gis.processing import area_type
from app.gis.roads import parse_lanes, parse_layer, parse_oneway, structure
from app.models.candidates import (
    BuildingAttributes,
    BuildingCandidate,
    BuildingPartCandidate,
    CandidateBatch,
    ConnectorCandidate,
    ConnectorReference,
    RoadAttributes,
    RoadCandidate,
    SourceRecord,
    WaterAttributes,
    WaterCandidate,
    WidthRule,
)
from app.models.scene import AreaType
from app.providers.base import ProviderResult, ProviderStatus


def clean(value):
    """Convert Arrow/Pandas scalars and nested arrays to finite JSON without guesses."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.ndarray):
        return [clean(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise ValueError(f"Unsupported source value type: {type(value).__name__}")


def osm_reference(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([nwr])(\d+)(?:@\d+)?", value)
    if match:
        return {"n": "node", "w": "way", "r": "relation"}[match[1]] + "/" + match[2]
    match = re.fullmatch(
        r"(?:https?://(?:www\.)?openstreetmap\.org/)?(node|way|relation)/(\d+)(?:@\d+)?",
        value,
    )
    return f"{match[1]}/{match[2]}" if match else None


def number(value, *, zero=False, meters=False):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a measurement")
    factor = 1
    if meters and isinstance(value, str):
        match = re.fullmatch(
            r"\s*([+]?\d+(?:[.,]\d+)?)\s*(m|metres?|meters?|ft|feet|')?\s*",
            value.lower(),
        )
        if not match:
            raise ValueError("Unsupported length/unit")
        value = match[1].replace(",", ".")
        factor = 0.3048 if match[2] in {"ft", "feet", "'"} else 1
    value = float(value) * factor
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError("Invalid measurement")
    return value


def mapped_number(raw, key, warnings, **options):
    try:
        return number(raw.get(key), **options)
    except (ValueError, TypeError):
        warnings.append(f"invalid_attribute:{key}")
        return None


def text(raw, key, warnings):
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    warnings.append(f"invalid_attribute:{key}")
    return None


def boolean(raw, key, warnings, osm=False):
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if osm and value in ("yes", "no", "true", "false", "1", "0"):
        return value in ("yes", "true", "1")
    warnings.append(f"invalid_attribute:{key}")
    return None


def source_records(raw, provider, identifier, warnings):
    if provider == "osm":
        return [
            SourceRecord(
                dataset="OpenStreetMap",
                record_id=identifier,
                osm_id=osm_reference(identifier),
                license="ODbL-1.0",
            )
        ]
    records = raw.get("sources") or []
    if not isinstance(records, list):
        warnings.append("invalid_attribute:sources")
        return []
    result = []
    for source in records:
        if not isinstance(source, dict):
            warnings.append("invalid_source_record")
            continue
        confidence = source.get("confidence")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            warnings.append("invalid_source_confidence")
            confidence = None
        record_id = text(source, "record_id", warnings)
        dataset = text(source, "dataset", warnings)
        result.append(
            SourceRecord(
                dataset=dataset,
                record_id=record_id,
                osm_id=osm_reference(record_id) if dataset == "OpenStreetMap" else None,
                property=text(source, "property", warnings),
                confidence=confidence,
                updated_at=text(source, "update_time", warnings),
                license=text(source, "license", warnings),
                raw=source,
            )
        )
    return result


def building_attributes(raw, osm, warnings):
    numeric = {
        "height": "height",
        "floors": "building:levels" if osm else "num_floors",
        "min_height": "min_height",
        "min_floor": "building:min_level" if osm else "min_floor",
        "roof_height": "roof:height" if osm else "roof_height",
    }
    values = {
        name: mapped_number(
            raw,
            key,
            warnings,
            zero=name in {"min_height", "min_floor", "roof_height"},
            meters=osm and name in {"height", "min_height", "roof_height"},
        )
        for name, key in numeric.items()
    }
    for name, osm_key in {
        "roof_shape": "roof:shape",
        "roof_color": "roof:colour",
        "roof_material": "roof:material",
        "roof_orientation": "roof:orientation",
        "facade_color": "building:colour",
        "facade_material": "building:material",
    }.items():
        values[name] = text(raw, osm_key if osm else name, warnings)
    direction_key = "roof:direction" if osm else "roof_direction"
    direction = mapped_number(raw, direction_key, warnings, zero=True)
    if direction is not None and direction >= 360:
        warnings.append(f"invalid_attribute:{direction_key}")
        direction = None
    values["roof_direction"] = direction
    values["building_type"] = text(raw, "building" if osm else "class", warnings)
    values["is_underground"] = boolean(raw, "is_underground", warnings)
    if not osm:
        values["has_parts"] = boolean(raw, "has_parts", warnings)
        values["parent_building_id"] = text(raw, "building_id", warnings)
    return BuildingAttributes(**values)


def road_attributes(raw, osm, warnings):
    if osm:
        tags = {k: str(v) for k, v in raw.items() if isinstance(v, (str, int, float))}
        return RoadAttributes(
            subtype="road",
            road_class=text(raw, "highway", warnings),
            explicit_width=mapped_number(raw, "width", warnings, meters=True),
            lanes=parse_lanes(tags.get("lanes")),
            oneway=parse_oneway(tags) if "oneway" in tags else None,
            layer=parse_layer(tags.get("layer")) if "layer" in tags else None,
            bridge=structure(tags["bridge"]) if "bridge" in tags else None,
            tunnel=structure(tags["tunnel"]) if "tunnel" in tags else None,
        )
    values = {
        "subtype": text(raw, "subtype", warnings),
        "road_class": text(raw, "class", warnings),
        "subclass": text(raw, "subclass", warnings),
    }
    for key, model in (("width_rules", WidthRule), ("connectors", ConnectorReference)):
        values[key] = []
        rules = raw.get(key) or []
        if not isinstance(rules, list):
            warnings.append(f"invalid_attribute:{key}")
            continue
        for i, rule in enumerate(rules):
            try:
                if not isinstance(rule, dict):
                    raise ValueError("Expected object")
                if isinstance(rule.get("value", rule.get("at")), bool):
                    raise ValueError("Boolean measurement")
                values[key].append(model.model_validate(rule))
            except (ValidationError, ValueError):
                warnings.append(f"invalid_attribute:{key}/{i}")
    for key in ("road_flags", "level_rules", "road_surface"):
        rules = raw.get(key) or []
        if isinstance(rules, list) and all(isinstance(r, dict) for r in rules):
            values[key] = rules
        else:
            warnings.append(f"invalid_attribute:{key}")
    return RoadAttributes(**values)


def normalize(results: list[ProviderResult], frame: LocalFrame) -> CandidateBatch:
    batch = CandidateBatch(
        crs=frame.crs.to_string(),
        origin_easting=frame.easting,
        origin_northing=frame.northing,
    )
    seen = set()
    for result in sorted(results, key=lambda r: (r.provider, r.feature_type)):
        batch.providers.append(clean(result.summary()))
        if result.status == ProviderStatus.UNAVAILABLE:
            batch.diagnostics.append(
                {"provider": result.provider, "reason": "provider_unavailable"}
            )
            continue
        if result.features.empty:
            continue
        if result.provider not in {"osm", "overture"}:
            continue
        if result.features.crs is None or result.features.crs.to_epsg() != 4326:
            raise ValueError("Candidate normalization expects WGS84 provider geometry")
        for index, row in result.features.iterrows():
            identifier = (
                ("/".join(map(str, index)) if isinstance(index, tuple) else str(index))
                if result.provider == "osm"
                else str(row.get("id"))
            )
            try:
                _normalize_row(result, row, identifier, frame, batch, seen)
            except (ValueError, TypeError, GEOSException) as exc:
                batch.diagnostics.append(
                    {
                        "provider": result.provider,
                        "id": identifier,
                        "reason": "invalid_candidate",
                        "detail": str(exc),
                    }
                )
    batch.candidates.sort(key=lambda c: c.candidate_id)
    batch.diagnostics.sort(
        key=lambda d: (str(d.get("provider")), str(d.get("id")), str(d.get("reason")))
    )
    return batch


def _normalize_row(result, row, identifier, frame, batch, seen):
    raw = clean({k: v for k, v in row.items() if k != "geometry"})
    osm = result.provider == "osm"
    if not osm and (not isinstance(raw.get("id"), str) or not raw["id"].strip()):
        raise ValueError("Missing or invalid provider feature ID")
    kind = result.feature_type
    if osm:
        if raw.get("building:part") not in (None, "", "no"):
            kind = "building_part"
        elif raw.get("building") not in (None, "", "no"):
            kind = "building"
        elif raw.get("highway"):
            kind = "segment"
        elif (
            raw.get("natural") == "coastline"
            or area_type({k: v for k, v in raw.items() if v is not None})
            == AreaType.WATER
        ):
            kind = "water"
        else:
            kind = "unsupported"
    geometry = row.geometry
    allowed = {
        "building": {"Polygon", "MultiPolygon"},
        "building_part": {"Polygon", "MultiPolygon"},
        "segment": {"LineString", "MultiLineString"},
        "connector": {"Point"},
        "water": {"Point", "LineString", "MultiLineString", "Polygon", "MultiPolygon"},
    }
    reason = None
    if kind not in allowed:
        reason = "unsupported_domain"
    elif geometry is None or geometry.is_empty:
        reason = "empty_geometry"
    elif geometry.geom_type not in allowed[kind]:
        reason = "unsupported_geometry"
    elif not np.isfinite(get_coordinates(geometry)).all():
        reason = "nonfinite_geometry"
    if reason:
        batch.diagnostics.append(
            {"provider": result.provider, "id": identifier, "reason": reason}
        )
        return
    geometry = force_2d(frame.to_local(force_2d(geometry)))
    warnings = []
    if not geometry.is_valid:
        warnings.append("invalid_geometry_requires_resolution")
    elif not geometry.intersects(frame.boundary):
        batch.diagnostics.append(
            {
                "provider": result.provider,
                "id": identifier,
                "reason": "outside_selection",
            }
        )
        return
    candidate_id = f"{result.provider}:{kind}:{identifier}"
    if candidate_id in seen:
        batch.candidates = [
            c for c in batch.candidates if c.candidate_id != candidate_id
        ]
        raise ValueError(f"Duplicate candidate ID: {candidate_id}")
    common = dict(
        candidate_id=candidate_id,
        provider=result.provider,
        provider_feature_id=identifier,
        release=result.release,
        geometry=geometry,
        source_records=source_records(raw, result.provider, identifier, warnings),
        raw_attributes=raw,
        license=result.metadata.get("license"),
        attribution_reference=result.metadata.get("attribution_url"),
    )
    if kind in {"building", "building_part"}:
        model = BuildingCandidate if kind == "building" else BuildingPartCandidate
        candidate = model(**common, attributes=building_attributes(raw, osm, warnings))
        if (
            kind == "building_part"
            and not osm
            and not candidate.attributes.parent_building_id
        ):
            warnings.append("missing_parent_building_id")
    elif kind == "segment":
        candidate = RoadCandidate(
            **common, attributes=road_attributes(raw, osm, warnings)
        )
    elif kind == "connector":
        candidate = ConnectorCandidate(**common)
    else:
        coast = osm and raw.get("natural") == "coastline"
        water_type = (
            (
                "coastline"
                if coast
                else raw.get("water") or raw.get("waterway") or "water"
            )
            if osm
            else text(raw, "subtype", warnings)
        )
        candidate = WaterCandidate(
            **common,
            attributes=WaterAttributes(
                water_type=water_type,
                water_class=None if osm else text(raw, "class", warnings),
                is_coastline=coast,
                is_surface=geometry.geom_type in {"Polygon", "MultiPolygon"}
                and not coast
                and water_type != "physical",
                is_salt=boolean(raw, "is_salt", warnings),
                is_intermittent=boolean(
                    raw, "intermittent" if osm else "is_intermittent", warnings, osm=osm
                ),
            ),
        )
    candidate.warnings = sorted(set(warnings))
    seen.add(candidate_id)
    batch.candidates.append(candidate)
