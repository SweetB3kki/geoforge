"""Apply the experimental profile contract explicitly; default pipeline stays F."""

from app.fusion.crossings import deduplicate_crossings
from app.fusion.scene_adapter import terrain_height
from app.gis.road_profiles import resolve_profiles
from app.models.scene import RoadVerticalProfile


def apply_road_profiles(scene, settings=None):
    if scene.terrain is None:
        return {"status": "unavailable", "reason": "no_dem", "applied": False}
    scene.roads = deduplicate_crossings(scene.roads)
    profiles, report = resolve_profiles(
        scene.roads, lambda x, y: terrain_height(scene.terrain, x, y), settings
    )
    if not report["constraint_converged"]:
        return {
            **report,
            "status": "unavailable",
            "reason": "nonconvergence",
            "applied": False,
        }
    by_id = {p.road_id: p for p in profiles}
    for road in scene.roads:
        profile = by_id[road.id]
        road.strategy_used = profile.strategy.value
        road.vertical_profile = RoadVerticalProfile(
            points=[
                (x, y, z) for (x, y), z in zip(profile.xy, profile.heights, strict=True)
            ],
            raw_heights=profile.raw_heights,
            strategy=profile.strategy.value,
            surface_visible=profile.surface_visible,
            bridge_height_method=profile.bridge_height_method,
            metrics=profile.metrics,
            warnings=profile.warnings,
        )
        road.field_provenance["vertical_profile"] = {
            "source": "derived_from_dsm",
            "method": "conditioned_profile_shared_nodes",
            "estimated": True,
        }
    report.update(
        status="experimental",
        applied=True,
        scope="experimental scene profile contract; renderer acceptance pending",
    )
    if scene.fusion_audit is not None:
        scene.fusion_audit["road_profiles"] = report
    return report
