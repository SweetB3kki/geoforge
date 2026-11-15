"""Content-checked, atomic cache entries keyed by the entire acquisition request."""

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def canonical(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            name = Path(stream.name)
            stream.write(data)
        os.replace(name, path)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


class CacheError(ValueError):
    """Corrupt or incompatible cache; never interpret this as empty coverage."""


class ProviderCache:
    def __init__(self, root: Path):
        self.root = root

    def paths(self, identity: dict) -> tuple[Path, Path]:
        key = hashlib.sha256(canonical(identity)).hexdigest()
        return self.root / f"{key}.bin", self.root / f"{key}.json"

    def read(self, identity: dict) -> tuple[bytes, dict] | None:
        payload, manifest = self.paths(identity)
        if not payload.exists() and not manifest.exists():
            return None
        try:
            info = json.loads(manifest.read_text(encoding="utf-8"))
            data = payload.read_bytes()
            if canonical(info["identity"]) != canonical(identity):
                raise ValueError("request identity mismatch")
            if hashlib.sha256(data).hexdigest() != info["sha256"]:
                raise ValueError("payload checksum mismatch")
            return data, info
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CacheError(f"Invalid provider cache {manifest.name}: {exc}") from exc

    def write(self, identity: dict, data: bytes, metadata: dict) -> dict:
        payload, manifest = self.paths(identity)
        info = {
            "identity": identity,
            "created_at": datetime.now(UTC).isoformat(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "payload_bytes": len(data),
            "metadata": metadata,
        }
        atomic_write(payload, data)
        atomic_write(manifest, canonical(info))
        return info
