"""Selection validation, metric CRS selection, and local coordinate conversion."""

import logging
import math
from typing import Self

from pydantic import Field, FiniteFloat, model_validator
from pyproj import CRS, Transformer
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from app.models.scene import Bounds, Model, Origin, PolygonModel

logger = logging.getLogger(__name__)


class CenterSelection(Model):
    latitude: FiniteFloat = Field(ge=-80, le=84)
    longitude: FiniteFloat = Field(ge=-180, le=180)
    radius_m: FiniteFloat = Field(gt=0, le=10_000)


class BBoxSelection(Model):
    west: FiniteFloat = Field(ge=-180, le=180)
    south: FiniteFloat = Field(ge=-80, le=84)
    east: FiniteFloat = Field(ge=-180, le=180)
    north: FiniteFloat = Field(ge=-80, le=84)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("Expected west < east and south < north; no dateline wrap")
        if self.east - self.west > 2 or self.north - self.south > 1:
            raise ValueError("Bounding box is too large for a local scene")
        return self


Selection = CenterSelection | BBoxSelection


def polygon_model(polygon: Polygon) -> PolygonModel:
    """Preserve polygon holes and discard source altitude (flat prototype)."""
    return PolygonModel(
        exterior=[(x, y, 0.0) for x, y, *_ in polygon.exterior.coords],
        holes=[[(x, y, 0.0) for x, y, *_ in r.coords] for r in polygon.interiors],
    )


class LocalFrame:
    """Project WGS84 to UTM, then subtract the selected center in meters."""

    def __init__(self, selection: Selection) -> None:
        self.selection = selection
        if isinstance(selection, CenterSelection):
            self.latitude, self.longitude = selection.latitude, selection.longitude
        else:
            self.latitude = (selection.south + selection.north) / 2
            self.longitude = (selection.west + selection.east) / 2
        # Select a WGS84 UTM CRS whose EPSG area of use contains the center.
        from pyproj.aoi import AreaOfInterest
        from pyproj.database import query_utm_crs_info

        candidates = query_utm_crs_info(
            datum_name="WGS 84",
            area_of_interest=AreaOfInterest(
                self.longitude, self.latitude, self.longitude, self.latitude
            ),
        )
        zone = min(60, max(1, math.floor((self.longitude + 180) / 6) + 1))
        fallback = (32600 if self.latitude >= 0 else 32700) + zone
        self.crs = CRS.from_epsg(candidates[0].code if candidates else fallback)
        self.forward = Transformer.from_crs(4326, self.crs, always_xy=True)
        self.inverse = Transformer.from_crs(self.crs, 4326, always_xy=True)
        self.easting, self.northing = self.forward.transform(
            self.longitude, self.latitude, errcheck=True
        )
        if isinstance(selection, CenterSelection):
            self.boundary = Point(0, 0).buffer(selection.radius_m, quad_segs=64)
            projected = affinity.translate(self.boundary, self.easting, self.northing)
            self.bbox = self.inverse.transform_bounds(*projected.bounds, densify_pts=21)
        else:
            self.bbox = (
                selection.west,
                selection.south,
                selection.east,
                selection.north,
            )
            # Densify geographic edges before projection so clipping follows the bbox.
            geographic = box(*self.bbox).segmentize(0.001)
            self.boundary = self.to_local(geographic)
            xmin, ymin, xmax, ymax = self.boundary.bounds
            if xmax - xmin > 20_000 or ymax - ymin > 20_000:
                raise ValueError("Bounding box sides must not exceed 20 km")
        west, south, east, north = self.bbox
        if west >= east or south < -80 or north > 84:
            raise ValueError("Selection crosses the dateline or supported UTM latitude")
        logger.info(
            "Selected CRS: %s; origin %.3f, %.3f", self.crs, self.easting, self.northing
        )

    def to_local(self, geometry: BaseGeometry) -> BaseGeometry:
        """Transform longitude/latitude geometry to scene meters."""
        projected = transform(self.forward.transform, geometry)
        return affinity.translate(projected, -self.easting, -self.northing)

    @property
    def origin(self) -> Origin:
        return Origin(easting=self.easting, northing=self.northing)

    @property
    def bounds(self) -> Bounds:
        xmin, ymin, xmax, ymax = self.boundary.bounds
        return Bounds(min_x=xmin, min_y=ymin, max_x=xmax, max_y=ymax)
