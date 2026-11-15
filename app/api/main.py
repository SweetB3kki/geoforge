"""Local HTTP API using the same generation service as the CLI."""

import logging
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException

from app.core.config import OUTPUT_DIR, configure_logging
from app.gis.coordinates import CenterSelection
from app.gis.input import DownloadError, OSMProvider
from app.models.scene import Model
from app.services.generation import generate

configure_logging()
logger = logging.getLogger(__name__)
app = FastAPI(title="GeoForge", version="0.1.0")


class GenerateResponse(Model):
    status: Literal["ok"] = "ok"
    buildings: int
    roads: int
    water_areas: int
    green_areas: int
    scene_path: str
    preview_path: str


def get_provider() -> OSMProvider:
    """Dependency seam for tests and future alternative sources."""
    return OSMProvider()


@app.get("/health")
def health() -> dict[str, str]:
    """Check application liveness without making external requests."""
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
def generate_scene(
    request: CenterSelection,
    provider: Annotated[OSMProvider, Depends(get_provider)],
) -> GenerateResponse:
    """Generate in a worker thread with separate output for each request."""
    try:
        result = generate(request, OUTPUT_DIR / uuid4().hex, provider)
    except DownloadError as exc:
        logger.exception("OSM provider failed")
        raise HTTPException(
            502, "OpenStreetMap download failed; try again later"
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("Scene generation failed")
        raise HTTPException(500, "Scene generation failed; see server logs") from exc
    return GenerateResponse(
        buildings=len(result.scene.buildings),
        roads=len(result.scene.roads),
        water_areas=len(result.scene.water_areas),
        green_areas=len(result.scene.green_areas),
        scene_path=str(result.scene_path),
        preview_path=str(result.preview_path),
    )
