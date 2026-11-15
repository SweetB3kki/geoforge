"""Human-readable UTF-8 JSON export with atomic file replacement."""

import logging
import os
import tempfile
from pathlib import Path

from app.models.scene import WorldScene

logger = logging.getLogger(__name__)


def export_json(scene: WorldScene, path: Path) -> Path:
    """Write a complete document; interrupted writes never truncate the target."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(scene.model_dump_json(indent=2))
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    logger.info("Scene exported to %s", path)
    return path
