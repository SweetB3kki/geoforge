"""Headless map preview rendered directly from the exported scene contract."""

import logging
from pathlib import Path
from threading import Lock

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as PlotPath
from shapely.geometry import LineString, Polygon, shape
from shapely.geometry.polygon import orient

from app.gis.coordinates import polygon_model
from app.models.scene import PolygonModel, WorldScene

logger = logging.getLogger(__name__)
_RENDER_LOCK = Lock()


def polygon_patch(model: PolygonModel, color: str) -> PathPatch:
    """Use opposite winding for interior rings so courtyards remain transparent."""
    polygon = orient(Polygon(model.exterior, model.holes), sign=1)
    vertices, codes = [], []
    for ring in [polygon.exterior, *polygon.interiors]:
        points = [(x, y) for x, y, *_ in ring.coords]
        vertices.extend(points)
        codes.extend(
            [PlotPath.MOVETO]
            + [PlotPath.LINETO] * (len(points) - 2)
            + [PlotPath.CLOSEPOLY]
        )
    return PathPatch(
        PlotPath(vertices, codes), facecolor=color, edgecolor=color, linewidth=0.5
    )


def road_draw_order(road):
    """Match Unity's prototype vertical separation; no inferred road intersections."""
    elevation = (road.layer or 0) * 0.75 + 0.25 * road.bridge - 0.25 * road.tunnel
    return elevation, road.road_subtype == "crossing", road.id


def render_preview(scene: WorldScene, path: Path, roads_mode: str = "FULL") -> Path:
    """Render all scene categories in meters, including a useful empty map."""
    categories = {
        "FULL": None,
        "RAW_AND_PROCESSED": None,
        "AUTOMOTIVE_ONLY": {"automotive"},
        "AUTOMOTIVE_AND_PEDESTRIAN": {"automotive", "pedestrian"},
    }
    if roads_mode not in categories:
        raise ValueError(f"Unknown roads mode: {roads_mode}")
    visible = [
        r
        for r in scene.roads
        if categories[roads_mode] is None or r.road_category in categories[roads_mode]
    ]
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _RENDER_LOCK:
        fig = Figure(figsize=(9, 9), layout="constrained")
        FigureCanvasAgg(fig)
        ax = fig.subplots()
        ax.set_facecolor("#f5f4ef")
        for area in scene.green_areas:
            ax.add_patch(polygon_patch(area.polygon, "#9dc795"))
        for area in scene.water_areas:
            ax.add_patch(polygon_patch(area.polygon, "#80bbdb"))
        for road in sorted(visible, key=road_draw_order):
            buffered = LineString(road.path).buffer(road.width / 2)
            color = {
                "automotive": "#747980",
                "pedestrian": "#b4a891",
                "cycle": "#688a92",
                "steps": "#95788f",
                "track": "#968266",
                "other": "#b4b4b4",
            }[road.road_category.value]
            if road.road_subtype == "crossing":
                color = "#d7bc79"
            elif road.road_category == "automotive":
                color = {
                    "motorway": "#3a4048",
                    "trunk": "#3a4048",
                    "primary": "#505965",
                    "secondary": "#667080",
                    "tertiary": "#78828b",
                    "service": "#9ba19d",
                }.get(road.road_type, "#858d94")
                if road.road_subtype == "link":
                    color = "#9099a2"
            ax.add_patch(polygon_patch(polygon_model(buffered), color))
        for building in scene.buildings:
            color = (
                {
                    "osm_height": "#247f45",
                    "levels": "#d6b33d",
                    "fallback": "#b2629b",
                }.get(building.height_source, "#bb7955")
                if roads_mode == "RAW_AND_PROCESSED"
                else "#bb7955"
            )
            ax.add_patch(polygon_patch(building.footprint, color))
        if roads_mode == "RAW_AND_PROCESSED":
            for record in (scene.processing_audit or {}).get("records", []):
                tags = record["source_tags"]
                geometry = record.get("raw_geometry_local")
                if not geometry or not (
                    tags.get("highway")
                    or tags.get("waterway")
                    or tags.get("natural") == "coastline"
                ):
                    continue
                geom = shape(geometry)
                lines = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
                for line in lines:
                    if line.geom_type != "LineString":
                        continue
                    coastline = tags.get("natural") == "coastline"
                    waterway = bool(tags.get("waterway"))
                    color = (
                        "#005bba"
                        if coastline or waterway
                        else {
                            "lost": "red",
                            "filtered": "darkorange",
                            "merged": "#6227bb",
                        }.get(record["status"], "#101010")
                    )
                    ax.plot(
                        *line.xy,
                        color=color,
                        alpha=0.65,
                        linewidth=1 if coastline else 0.65,
                        linestyle="--" if record["status"] == "filtered" else "-",
                    )
        bounds = scene.bounds
        ax.set(
            xlim=(bounds.min_x, bounds.max_x),
            ylim=(bounds.min_y, bounds.max_y),
            xlabel="X / East (m)",
            ylabel="Y / North (m)",
            aspect="equal",
        )
        ax.set_title(
            f"GeoForge · {len(scene.buildings)} buildings · "
            f"{len(visible)} roads · {roads_mode}"
        )
        ax.legend(
            handles=[
                Patch(color="#bb7955", label="Buildings"),
                Patch(color="#747980", label="Automotive"),
                Patch(color="#b4a891", label="Pedestrian"),
                Patch(color="#688a92", label="Cycle"),
                Patch(color="#95788f", label="Steps"),
                Patch(color="#d7bc79", label="Crossing"),
                Patch(color="#80bbdb", label="Water"),
                Patch(color="#9dc795", label="Green areas"),
            ],
            loc="upper right",
        )
        ax.grid(alpha=0.15)
        if roads_mode == "RAW_AND_PROCESSED":
            ax.legend(
                handles=[
                    Line2D([], [], color=c, label=t, linestyle=s)
                    for c, t, s in [
                        ("black", "Raw highway", "-"),
                        ("#6227bb", "Merged source", "-"),
                        ("darkorange", "Filtered", "--"),
                        ("red", "Lost", "-"),
                        ("#005bba", "Coastline / waterways", "-"),
                        ("#247f45", "OSM height", "-"),
                        ("#d6b33d", "Height from levels", "-"),
                        ("#b2629b", "Fallback height", "-"),
                    ]
                ],
                loc="upper right",
                fontsize=7,
            )
        fig.supxlabel(
            "© OpenStreetMap contributors · Local coordinates in meters",
            fontsize=8,
        )
        fig.savefig(path, dpi=150)
        fig.clear()
    logger.info("Preview exported to %s", path)
    return path
