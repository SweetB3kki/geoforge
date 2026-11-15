"""Versioned scene contract. Geometry coordinates are local meters."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Positive = Annotated[FiniteFloat, Field(gt=0)]
Point3D = tuple[FiniteFloat, FiniteFloat, FiniteFloat]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PolygonModel(Model):
    """Closed exterior and interior rings in absolute scene coordinates."""

    exterior: list[Point3D] = Field(min_length=4)
    holes: list[list[Point3D]] = Field(default_factory=list)

    @model_validator(mode="after")
    def closed_rings(self) -> Self:
        for ring in [self.exterior, *self.holes]:
            if len(ring) < 4 or ring[0] != ring[-1] or len(set(ring[:-1])) < 3:
                raise ValueError(
                    "Polygon rings must be closed with 3 distinct vertices"
                )
        return self


class Provenance(Model):
    source: str = "OpenStreetMap"
    source_osm_ids: list[str] = Field(default_factory=list)
    processing: list[str] = Field(default_factory=list)


class BuildingAvailability(Model):
    footprint: bool = True
    explicit_height: bool = False
    floors: bool = False
    roof_shape: bool = False
    parts: int = Field(default=0, ge=0)
    terrain: bool = False


class DataAvailabilityProfile(Model):
    buildings: dict = Field(default_factory=dict)
    roads: dict = Field(default_factory=dict)
    water: dict = Field(default_factory=dict)
    terrain: dict = Field(default_factory=dict)


class Building(Provenance):
    id: str
    footprint: PolygonModel
    position: Point3D
    height: Positive
    levels: Positive | None = None
    height_source: Literal[
        "osm_height", "overture_height", "levels", "fallback", "legacy"
    ] = "legacy"
    building_type: str
    source_tags: dict[str, str] = Field(default_factory=dict)
    resolved_tags: dict[str, str] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    fusion_method: str | None = None
    field_provenance: dict = Field(default_factory=dict)
    parts: list["Building"] = Field(default_factory=list)
    parent_id: str | None = None
    min_height: FiniteFloat = Field(default=0, ge=0)
    ground_height_m: FiniteFloat | None = None
    ground_method: str | None = None
    ground_audit: dict = Field(default_factory=dict)
    availability: BuildingAvailability | None = None
    strategy_used: str | None = None
    render_footprints: list[PolygonModel] | None = None

    @model_validator(mode="after")
    def valid_vertical_extent(self) -> Self:
        if self.min_height >= self.height:
            raise ValueError("Building top height must exceed min_height")
        if any(p.parts or p.parent_id != self.id for p in self.parts):
            raise ValueError("Parts must refer to their parent and cannot nest")
        return self


class RoadCategory(StrEnum):
    AUTOMOTIVE = "automotive"
    PEDESTRIAN = "pedestrian"
    CYCLE = "cycle"
    STEPS = "steps"
    TRACK = "track"
    OTHER = "other"


class RoadVerticalProfile(Model):
    points: list[Point3D] = Field(min_length=2)
    raw_heights: list[FiniteFloat]
    strategy: Literal[
        "AUTOMOTIVE_GROUND",
        "AUTOMOTIVE_BRIDGE",
        "AUTOMOTIVE_TUNNEL",
        "PEDESTRIAN",
        "CYCLE",
        "STEPS",
        "TRACK",
        "OTHER",
    ]
    surface_visible: bool = True
    bridge_height_method: str | None = None
    estimated: bool = True
    metrics: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_profile(self) -> Self:
        if len(self.raw_heights) != len(self.points):
            raise ValueError("Road profile sample lengths differ")
        for a, b in zip(self.points[:-1], self.points[1:], strict=True):
            if (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 <= 1e-16:
                raise ValueError("Zero-length road profile span")
        return self


class Road(Provenance):
    id: str
    path: list[Point3D] = Field(min_length=2)
    road_type: str
    width: Positive
    source_tags: dict[str, str] = Field(default_factory=dict)
    road_category: RoadCategory = RoadCategory.AUTOMOTIVE
    road_subtype: str | None = None
    width_source: Literal[
        "osm_width", "overture_width_rule", "lanes", "fallback", "legacy"
    ] = "legacy"
    lanes: int | None = Field(default=None, gt=0)
    oneway: Literal[-1, 0, 1] | None = None
    name: str | None = None
    ref: str | None = None
    surface: str | None = None
    bridge: bool = False
    tunnel: bool = False
    layer: int | None = 0
    source_ids: list[str] = Field(default_factory=list)
    source_tags_by_id: dict[str, dict[str, str]] = Field(default_factory=dict)
    start_node: str | None = None
    end_node: str | None = None
    node_ids: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    field_provenance: dict = Field(default_factory=dict)
    width_rules: list[dict] = Field(default_factory=list)
    connectors: list[dict] = Field(default_factory=list)
    transportation_matches: list[dict] = Field(default_factory=list)
    transportation_attributes: list[dict] = Field(default_factory=list)
    fusion_method: str | None = None
    strategy_used: str | None = None
    vertical_profile: RoadVerticalProfile | None = None


class AreaType(StrEnum):
    WATER = "water"
    GREEN = "green"


class Area(Provenance):
    id: str
    polygon: PolygonModel
    area_type: AreaType
    source_tags: dict[str, str] = Field(default_factory=dict)
    water_type: str | None = None
    water_height_method: str | None = None
    water_level_m: FiniteFloat | None = None
    geometry_source: str | None = None
    semantic_source: str | None = None
    sources: list[str] = Field(default_factory=list)
    fusion_method: str | None = None
    strategy_used: str | None = None
    field_provenance: dict = Field(default_factory=dict)


class Origin(Model):
    """Projected location represented by scene coordinate (0, 0, 0)."""

    easting: FiniteFloat
    northing: FiniteFloat
    altitude_m: FiniteFloat = 0


class Bounds(Model):
    min_x: FiniteFloat
    min_y: FiniteFloat
    max_x: FiniteFloat
    max_y: FiniteFloat

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.min_x >= self.max_x or self.min_y >= self.max_y:
            raise ValueError("Bounds must have positive width and height")
        return self


class RoadStatistics(Model):
    raw_highway_ways: int = 0
    input_segments: int = 0
    topology_segments: int = 0
    logical_roads: int = 0
    segments_merged: int = 0
    segments_skipped: int = 0
    nodes: int = 0
    junctions: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    crossings: int = 0
    service_roads: int = 0


class Metadata(Model):
    schema_version: Literal["1.0", "1.1"] = "1.0"
    source: str = "OpenStreetMap"
    attribution: str = "В© OpenStreetMap contributors; ODbL 1.0"
    generated_at: datetime
    crs: str
    origin_lat: FiniteFloat
    origin_lon: FiniteFloat
    units: Literal["meters"] = "meters"
    axes: Literal["X=east,Y=north,Z=up"] = "X=east,Y=north,Z=up"
    selection_type: Literal["radius", "bbox"]
    selection_boundary: PolygonModel
    skipped_features: int = 0
    repaired_features: int = 0
    road_statistics: RoadStatistics | None = None
    providers: list[dict] = Field(default_factory=list)
    fusion_mode: str | None = None
    generation_profile: str | None = None
    data_availability: DataAvailabilityProfile | None = None


class TerrainData(Model):
    """Node grid in local meters, flattened row-major south to north, west to east."""

    available: Literal[True] = True
    resolution_x: int = Field(ge=3, le=513)
    resolution_y: int = Field(ge=3, le=513)
    origin: Point3D
    cell_size: tuple[Positive, Positive]
    heights: list[FiniteFloat]
    valid_mask: list[bool]
    min_height: FiniteFloat
    max_height: FiniteFloat
    height_offset_m: FiniteFloat
    vertical_datum: str = "EGM2008"
    source: str
    source_urls: list[str] = Field(default_factory=list)
    attribution: str
    sampling: Literal["south_to_north_rows_west_to_east_columns"] = (
        "south_to_north_rows_west_to_east_columns"
    )

    @model_validator(mode="after")
    def check_grid(self) -> Self:
        count = self.resolution_x * self.resolution_y
        if len(self.heights) != count or len(self.valid_mask) != count:
            raise ValueError("Terrain grid length does not match its dimensions")
        if not any(self.valid_mask):
            raise ValueError("Terrain has no valid selection samples")
        if (
            abs(min(self.heights) - self.min_height) > 0.001
            or abs(max(self.heights) - self.max_height) > 0.001
        ):
            raise ValueError("Terrain min/max mismatch")
        return self


class WorldScene(Model):
    metadata: Metadata
    origin: Origin
    bounds: Bounds
    terrain: TerrainData | None = None
    processing_audit: dict | None = None
    fusion_audit: dict | None = None
    buildings: list[Building] = Field(default_factory=list)
    roads: list[Road] = Field(default_factory=list)
    water_areas: list[Area] = Field(default_factory=list)
    green_areas: list[Area] = Field(default_factory=list)

    @model_validator(mode="after")
    def terrain_bounds(self) -> Self:
        if self.terrain is not None:
            t, b = self.terrain, self.bounds
            actual = (
                t.origin[0],
                t.origin[1],
                t.origin[0] + t.cell_size[0] * (t.resolution_x - 1),
                t.origin[1] + t.cell_size[1] * (t.resolution_y - 1),
            )
            expected = (b.min_x, b.min_y, b.max_x, b.max_y)
            if any(abs(a - e) > 0.01 for a, e in zip(actual, expected, strict=True)):
                raise ValueError("Terrain grid must match scene bounds")
        return self
