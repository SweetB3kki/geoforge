"""Engine-neutral, typed source candidates. Heights are not estimated here."""

from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, JsonValue, field_serializer, field_validator
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from app.models.scene import Model

Positive = Annotated[FiniteFloat, Field(gt=0)]
Nonnegative = Annotated[FiniteFloat, Field(ge=0)]
Confidence = Annotated[FiniteFloat, Field(ge=0, le=1)]


class SourceRecord(Model):
    dataset: str | None = None
    record_id: str | None = None
    osm_id: str | None = None
    property: str | None = None
    confidence: Confidence | None = None
    updated_at: str | None = None
    license: str | None = None
    raw: dict[str, JsonValue] = Field(default_factory=dict)


class ResolvedValue(Model):
    value: JsonValue
    source: str
    source_feature_id: str | None = None
    method: str
    confidence: Confidence | None = None
    estimated: bool = False


class BuildingAttributes(Model):
    height: Positive | None = None
    floors: Positive | None = None
    min_height: Nonnegative | None = None
    min_floor: Nonnegative | None = None
    roof_height: Nonnegative | None = None
    roof_shape: str | None = None
    roof_color: str | None = None
    roof_material: str | None = None
    roof_direction: Annotated[FiniteFloat, Field(ge=0, lt=360)] | None = None
    roof_orientation: str | None = None
    facade_color: str | None = None
    facade_material: str | None = None
    building_type: str | None = None
    has_parts: bool | None = None
    is_underground: bool | None = None
    parent_building_id: str | None = None


class WidthRule(Model):
    value: Positive
    between: tuple[Nonnegative, Nonnegative] | None = None

    @field_validator("between")
    @classmethod
    def range_valid(cls, value):
        if value is not None and not 0 <= value[0] < value[1] <= 1:
            raise ValueError("Expected normalized non-empty range [start,end]")
        return value


class ConnectorReference(Model):
    connector_id: str
    at: Annotated[FiniteFloat, Field(ge=0, le=1)]


class RoadAttributes(Model):
    subtype: str | None = None
    road_class: str | None = None
    subclass: str | None = None
    explicit_width: Positive | None = None
    lanes: Annotated[int, Field(gt=0)] | None = None
    oneway: Literal[-1, 0, 1] | None = None
    width_rules: list[WidthRule] = Field(default_factory=list)
    connectors: list[ConnectorReference] = Field(default_factory=list)
    road_flags: list[dict[str, JsonValue]] = Field(default_factory=list)
    level_rules: list[dict[str, JsonValue]] = Field(default_factory=list)
    road_surface: list[dict[str, JsonValue]] = Field(default_factory=list)
    bridge: bool | None = None
    tunnel: bool | None = None
    layer: int | None = None


class WaterAttributes(Model):
    water_type: str | None = None
    water_class: str | None = None
    is_surface: bool = False
    is_coastline: bool = False
    is_salt: bool | None = None
    is_intermittent: bool | None = None


class Candidate(Model):
    model_config = {**Model.model_config, "arbitrary_types_allowed": True}
    candidate_id: str
    provider: str
    provider_feature_id: str
    release: str | None = None
    geometry: BaseGeometry
    source_records: list[SourceRecord] = Field(default_factory=list)
    raw_attributes: dict[str, JsonValue] = Field(default_factory=dict)
    confidence: Confidence | None = None
    updated_at: str | None = None
    license: str | None = None
    attribution_reference: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("geometry", mode="before")
    @classmethod
    def read_geometry(cls, value):
        return shape(value) if isinstance(value, dict) else value

    @field_serializer("geometry")
    def write_geometry(self, value):
        return mapping(value)


class BuildingCandidate(Candidate):
    kind: Literal["building"] = "building"
    attributes: BuildingAttributes


class BuildingPartCandidate(Candidate):
    kind: Literal["building_part"] = "building_part"
    attributes: BuildingAttributes


class RoadCandidate(Candidate):
    kind: Literal["road"] = "road"
    attributes: RoadAttributes


class WaterCandidate(Candidate):
    kind: Literal["water"] = "water"
    attributes: WaterAttributes


class ConnectorCandidate(Candidate):
    kind: Literal["connector"] = "connector"


CandidateType = Annotated[
    BuildingCandidate
    | BuildingPartCandidate
    | RoadCandidate
    | WaterCandidate
    | ConnectorCandidate,
    Field(discriminator="kind"),
]


class CandidateBatch(Model):
    crs: str
    origin_easting: FiniteFloat
    origin_northing: FiniteFloat
    candidates: list[CandidateType] = Field(default_factory=list)
    diagnostics: list[dict[str, JsonValue]] = Field(default_factory=list)
    providers: list[dict[str, JsonValue]] = Field(default_factory=list)
