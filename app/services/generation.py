"""Shared orchestration for CLI and HTTP entry points."""

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from app.exporters.json_exporter import export_json
from app.gis.coordinates import LocalFrame, Selection
from app.gis.input import FeatureProvider, OSMProvider
from app.gis.processing import build_scene
from app.models.scene import WorldScene
from app.validation.scene_validator import write_report
from app.visualization.preview import render_preview


@dataclass(frozen=True)
class GenerationResult:
    scene: WorldScene
    scene_path: Path
    preview_path: Path


def generate(
    selection: Selection,
    output_dir: Path,
    provider: FeatureProvider | None = None,
    *,
    elevation: bool = False,
    terrain_resolution: int = 129,
    data_mode: str = "osm-only",
    refresh_data: bool = False,
    use_cache: bool = True,
    overture_provider=None,
    transport_settings=None,
) -> GenerationResult:
    """Run the complete GIS pipeline using an injectable input provider."""
    if data_mode not in {"osm-only", "auto"}:
        raise ValueError("Unknown data mode")
    frame = LocalFrame(selection)
    start = perf_counter()
    features = (provider or OSMProvider()).fetch(frame.bbox)
    bundle = None
    if data_mode == "auto":
        from app.providers.base import ProviderResult, ProviderStatus
        from app.providers.manager import SourceBundle
        from app.providers.overture import OvertureProvider
        from app.providers.overture_catalog import THEMES

        extra = overture_provider or OvertureProvider(
            refresh=refresh_data, use_cache=use_cache
        )
        extra_results = {}
        for kind in THEMES:
            try:
                extra_results[kind] = extra.fetch(frame.bbox, kind)
            except Exception as exc:
                extra_results[kind] = ProviderResult(
                    "overture",
                    None,
                    kind,
                    ProviderStatus.UNAVAILABLE,
                    errors=[f"{type(exc).__name__}: {exc}"],
                )
        bundle = SourceBundle(
            ProviderResult(
                "osm",
                None,
                "features",
                ProviderStatus.SUCCESS if len(features) else ProviderStatus.EMPTY,
                features=features,
                cache_hit=None,
                metadata={
                    "license": "ODbL-1.0",
                    "attribution_url": "https://www.openstreetmap.org/copyright",
                },
            ),
            extra_results,
        )
    fetched = perf_counter()
    scene = build_scene(features, frame)
    processed = perf_counter()
    if elevation or data_mode == "auto":
        from app.gis.elevation import add_elevation

        try:
            add_elevation(scene, terrain_resolution)
        except Exception as exc:
            if data_mode != "auto":
                raise
            scene.metadata.providers.append(
                {
                    "provider": "copernicus",
                    "status": "unavailable",
                    "errors": [str(exc)],
                }
            )
    if bundle is not None:
        from app.fusion.normalization import normalize
        from app.fusion.resolvers import resolve
        from app.fusion.scene_adapter import apply_fusion

        batch = normalize([bundle.osm, *bundle.overture.values()], frame)
        fused = resolve(batch, frame.boundary)
        apply_fusion(scene, batch, fused)
        from app.fusion.transportation import enrich_transport

        enrich_transport(scene, batch, frame.boundary, transport_settings)
    enriched = perf_counter()
    preview_path = render_preview(scene, output_dir / "preview.png")
    scene_path = export_json(scene, output_dir / "scene.json")
    report = write_report(scene, output_dir / "scene-quality.json")
    if not report["valid"]:
        raise ValueError("Scene quality validation failed; inspect scene-quality.json")
    report["performance"] = {
        "fetch_seconds": fetched - start,
        "processing_seconds": processed - fetched,
        "elevation_and_fusion_seconds": enriched - processed,
        "scene_json_bytes": scene_path.stat().st_size,
    }
    if scene.fusion_audit is not None:
        report["providers"] = scene.metadata.providers
        report["fusion"] = scene.fusion_audit
    (output_dir / "scene-quality.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    render_preview(scene, output_dir / "diagnostic-preview.png", "RAW_AND_PROCESSED")
    return GenerationResult(scene, scene_path, preview_path)
