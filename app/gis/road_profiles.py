"""Engine-independent profile prototype for phase G; not yet applied to scene export.

Planar paths and DSM are inputs only. Joint projections constrain shared automotive
node variables, so smoothing cannot reintroduce a height seam after conditioning.
Limits describe a reconstruction estimate, not surveyed road engineering geometry.
"""

import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from enum import StrEnum

import numpy as np

from app.gis.bridge_approaches import approach_constraints
from app.gis.junction_sections import merge_junction_sections


class RoadGenerationStrategy(StrEnum):
    AUTOMOTIVE_GROUND = "AUTOMOTIVE_GROUND"
    AUTOMOTIVE_BRIDGE = "AUTOMOTIVE_BRIDGE"
    AUTOMOTIVE_TUNNEL = "AUTOMOTIVE_TUNNEL"
    PEDESTRIAN = "PEDESTRIAN"
    CYCLE = "CYCLE"
    STEPS = "STEPS"
    TRACK = "TRACK"
    OTHER = "OTHER"


@dataclass(frozen=True)
class RoadProfileSettings:
    bridgeApproachContinuity: bool = False
    junctionCrossSectionRadiusFactor: float = 0.0
    roadProfileSampleSpacing: float = 5.0
    roadProfileSmoothingDistance: float = 25.0
    maxRoadGrade: float = 0.18
    maxVerticalCurvature: float = 0.015
    spikeThresholdMeters: float = 2.0
    bridgeClearanceMeters: float = 3.0
    tunnelDepthMeters: float = 3.0
    constraintToleranceMeters: float = 0.0001
    maximumConstraintIterations: int = 4000
    maximumSamplesPerRoad: int = 20000

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == "bridgeApproachContinuity":
                if not isinstance(value, bool):
                    raise ValueError("bridgeApproachContinuity must be boolean")
                continue
            if name == "junctionCrossSectionRadiusFactor" and value == 0:
                continue
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("maximumConstraintIterations", "maximumSamplesPerRoad"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if self.maximumSamplesPerRoad < 2:
            raise ValueError("maximumSamplesPerRoad must be at least 2")


@dataclass
class RoadProfile:
    road_id: str
    strategy: RoadGenerationStrategy
    distances: list[float]
    xy: list[tuple[float, float]]
    raw_heights: list[float]
    heights: list[float]
    sample_node_ids: dict[int, str]
    max_grade: float
    max_curvature: float
    surface_visible: bool = True
    bridge_height_method: str | None = None
    estimated: bool = True
    metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def road_strategy(road):
    # Nonautomotive structures retain category policy; the explicit bridge
    # method / tunnel visibility still overrides terrain draping below.
    if road.tunnel and road.road_category == "automotive":
        return RoadGenerationStrategy.AUTOMOTIVE_TUNNEL
    if road.bridge and road.road_category == "automotive":
        return RoadGenerationStrategy.AUTOMOTIVE_BRIDGE
    return {
        "automotive": RoadGenerationStrategy.AUTOMOTIVE_GROUND,
        "pedestrian": RoadGenerationStrategy.PEDESTRIAN,
        "cycle": RoadGenerationStrategy.CYCLE,
        "steps": RoadGenerationStrategy.STEPS,
        "track": RoadGenerationStrategy.TRACK,
    }.get(road.road_category, RoadGenerationStrategy.OTHER)


def policy(strategy, settings):
    smoothing, grade, curvature = {
        RoadGenerationStrategy.PEDESTRIAN: (0.4, 0.4, 0.08),
        RoadGenerationStrategy.CYCLE: (0.6, 0.25, 0.04),
        RoadGenerationStrategy.STEPS: (0.2, 1.2, 0.3),
        RoadGenerationStrategy.TRACK: (0.4, 0.5, 0.1),
        RoadGenerationStrategy.OTHER: (0.4, 0.5, 0.1),
    }.get(strategy, (1.0, settings.maxRoadGrade, settings.maxVerticalCurvature))
    return settings.roadProfileSmoothingDistance * smoothing, grade, curvature


def sample_path(road, settings):
    points = np.asarray(road.path, dtype=float)[:, :2]
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    if np.any(lengths <= 1e-8):
        raise ValueError(f"Zero-length planar edge in {road.id}")
    distances = np.r_[0.0, np.cumsum(lengths)]
    counts = np.ceil(lengths / settings.roadProfileSampleSpacing).astype(int)
    # Subdivide each original span evenly. A global regular grid plus vertices
    # creates artificial centimetre edges where the two station sets nearly meet,
    # making curvature constraints ill-conditioned for no geographic reason.
    if counts.sum() + 1 > settings.maximumSamplesPerRoad:
        raise ValueError(f"Profile sample budget exceeded for {road.id}")
    samples = np.concatenate(
        [
            *[
                np.linspace(a, b, count + 1)[:-1]
                for a, b, count in zip(
                    distances[:-1], distances[1:], counts, strict=True
                )
            ],
            [distances[-1]],
        ]
    )
    xy = np.column_stack(
        [np.interp(samples, distances, points[:, axis]) for axis in (0, 1)]
    )
    nodes = {}
    if len(road.node_ids) == len(points):
        nodes = {
            int(np.searchsorted(samples, distance)): node
            for distance, node in zip(distances, road.node_ids, strict=True)
            if node
        }
    return samples, xy, nodes


def condition_samples(distances, raw, smoothing_distance, spike_threshold):
    """Hampel rejection then local linear smoothing, preserving an affine slope."""
    clean = np.array(raw, dtype=float)
    radius = max(smoothing_distance / 2, 1e-6)
    windows = [
        (
            int(np.searchsorted(distances, d - radius)),
            int(np.searchsorted(distances, d + radius, side="right")),
        )
        for d in distances
    ]
    rejected = 0
    for i, (a, b) in enumerate(windows):
        values = raw[a:b]
        median = float(np.median(values))
        deviation = float(np.median(np.abs(values - median)))
        if b - a >= 3 and abs(raw[i] - median) > max(
            spike_threshold, 3 * 1.4826 * deviation
        ):
            clean[i] = median
            rejected += 1
    smooth = clean.copy()
    for i, (a, b) in enumerate(windows):
        if b - a < 3:
            continue
        x = distances[a:b] - distances[i]
        w = np.maximum(0.05, 1 - np.abs(x) / radius)
        # Weighted linear least squares, evaluating at x=0. At endpoints this
        # preserves the regional incline instead of flattening with padding.
        s0, s1, s2 = w.sum(), (w * x).sum(), (w * x * x).sum()
        y0, y1 = (w * clean[a:b]).sum(), (w * x * clean[a:b]).sum()
        determinant = s0 * s2 - s1 * s1
        if determinant > 1e-12:
            smooth[i] = (y0 * s2 - y1 * s1) / determinant
    return smooth, rejected


def profile_metrics(distances, heights):
    delta = np.diff(distances)
    grade = np.diff(heights) / delta
    curvature = np.diff(grade) / ((delta[:-1] + delta[1:]) / 2)
    return {
        "max_abs_grade": float(np.max(np.abs(grade), initial=0)),
        "max_abs_curvature": float(np.max(np.abs(curvature), initial=0)),
        "elevation_change": float(heights[-1] - heights[0]),
    }


def resolve_profiles(roads, sample_height, settings=None):
    """Return separate profiles/audit, without mutating Roads or a terrain grid.

    sample_height(x, y) supplies local Z in metres. Missing DEM must be handled by
    the caller and labelled explicitly; nonfinite samples are rejected here.
    This prototype does not yet tessellate or place Unity road meshes.
    """
    settings = settings or RoadProfileSettings()
    profiles, input_roads = [], {}
    for road in sorted(roads, key=lambda item: item.id):
        if road.id in input_roads:
            raise ValueError(f"Duplicate road id: {road.id}")
        input_roads[road.id] = road
        distances, xy, nodes = sample_path(road, settings)
        raw = np.array([sample_height(x, y) for x, y in xy], dtype=float)
        if not np.isfinite(raw).all():
            raise ValueError(f"Nonfinite terrain samples for {road.id}")
        strategy = road_strategy(road)
        smoothing, grade, curvature = policy(strategy, settings)
        heights, rejected = condition_samples(
            distances, raw, smoothing, settings.spikeThresholdMeters
        )
        profile = RoadProfile(
            road.id,
            strategy,
            distances.tolist(),
            [tuple(p) for p in xy],
            raw.tolist(),
            heights.tolist(),
            nodes,
            grade,
            curvature,
            metrics={
                "raw": profile_metrics(distances, raw),
                "rejected_spikes": rejected,
            },
        )
        if road.tunnel:
            profile.surface_visible = False
            profile.heights = (heights - settings.tunnelDepthMeters).tolist()
            profile.warnings.append("tunnel_surface_hidden_no_tunnel_geometry")
        elif road.bridge:
            # Provisional linear deck above sampled terrain. Raised endpoints do
            # not imply constructed approach ramps; the approximation is explicit.
            slope = np.clip((heights[-1] - heights[0]) / distances[-1], -grade, grade)
            deck = (heights[0] + heights[-1]) / 2 + slope * (
                distances - distances[-1] / 2
            )
            clearance = settings.bridgeClearanceMeters * max(1, road.layer or 1)
            deck += max(0.0, float(np.max(raw + clearance - deck)))
            profile.heights = deck.tolist()
            profile.bridge_height_method = "linear_sampled_clearance_envelope"
            profile.warnings.append("bridge_approaches_and_cross_section_unverified")
        profiles.append(profile)

    # Each shared automotive ground node has one variable. This is stronger than
    # averaging endpoints after smoothing, which can violate grade constraints.
    keys, seeds, mappings = {}, defaultdict(list), {}
    shared_owners = defaultdict(set)
    for profile in profiles:
        if not profile.surface_visible or profile.bridge_height_method:
            continue
        road = input_roads[profile.road_id]
        indices = []
        for i, (point, height) in enumerate(
            zip(profile.xy, profile.heights, strict=True)
        ):
            key = (profile.road_id, i)
            node = profile.sample_node_ids.get(i)
            if (
                profile.strategy == RoadGenerationStrategy.AUTOMOTIVE_GROUND
                and node
                and road.layer is not None
            ):
                key = (
                    "shared",
                    node,
                    road.layer,
                    round(point[0], 6),
                    round(point[1], 6),
                )
                shared_owners[key].add(profile.road_id)
            variable = keys.setdefault(key, len(keys))
            seeds[variable].append(height)
            indices.append(variable)
        mappings[profile.road_id] = indices
    junction_sections = []
    if settings.junctionCrossSectionRadiusFactor:
        mappings, seeds, junction_sections = merge_junction_sections(
            profiles,
            input_roads,
            mappings,
            seeds,
            settings.junctionCrossSectionRadiusFactor,
        )
    values = np.array([np.median(seeds[i]) for i in range(len(seeds))], dtype=float)
    pinned, bridge_connections = ({}, [])
    if settings.bridgeApproachContinuity:
        pinned, bridge_connections = approach_constraints(
            profiles, input_roads, mappings
        )
    pinned_indices = np.array(list(pinned), dtype=int)
    pinned_values = np.array(list(pinned.values()), dtype=float)
    values[pinned_indices] = pinned_values
    constraints = []

    def add_constraint(indices, coefficients, bound):
        combined = defaultdict(float)
        for index, coefficient in zip(indices, coefficients, strict=True):
            combined[index] += coefficient
        pairs = [(i, c) for i, c in combined.items() if abs(c) > 1e-12]
        if pairs:
            norm = math.sqrt(sum(c * c for _, c in pairs))
            constraints.append(([(i, c / norm) for i, c in pairs], bound / norm))

    for profile in profiles:
        indices = mappings.get(profile.road_id)
        if indices is None:
            continue
        delta = np.diff(profile.distances)
        for i, d in enumerate(delta):
            add_constraint(indices[i : i + 2], [-1, 1], profile.max_grade * d)
        for i, (a, b) in enumerate(zip(delta[:-1], delta[1:], strict=True)):
            add_constraint(
                indices[i : i + 3],
                [1 / a, -1 / a - 1 / b, 1 / b],
                profile.max_curvature * (a + b) / 2,
            )
    # Greedy colouring makes each batch independent (no repeated variable). The
    # same bounded projections then run as NumPy arrays instead of Python loops.
    groups, colours = [], defaultdict(set)
    for constraint in constraints:
        forbidden = set().union(*(colours[i] for i, _ in constraint[0]))
        colour = 0
        while colour in forbidden:
            colour += 1
        if colour == len(groups):
            groups.append([])
        groups[colour].append(constraint)
        for i, _ in constraint[0]:
            colours[i].add(colour)

    def pack(items):
        terms = [(row, i, c) for row, (ts, _) in enumerate(items) for i, c in ts]
        return (
            np.array([i for _, i, _ in terms], dtype=int),
            np.array([row for row, _, _ in terms], dtype=int),
            np.array([c for _, _, c in terms], dtype=float),
            np.array([bound for _, bound in items]),
        )

    batches = [pack(group) for group in groups]
    all_indices, all_rows, all_coefficients, all_bounds = pack(constraints)
    converged, residual, relative_residual, iterations = False, 0.0, 0.0, 0
    for _iteration in range(settings.maximumConstraintIterations):
        iterations += 1
        for indices, rows, coefficients, bounds in batches:
            projected = np.bincount(
                rows, values[indices] * coefficients, minlength=len(bounds)
            )
            correction = projected - np.clip(projected, -bounds, bounds)
            values[indices] -= correction[rows] * coefficients
            values[pinned_indices] = pinned_values
        projected = np.bincount(
            all_rows, values[all_indices] * all_coefficients, minlength=len(all_bounds)
        )
        errors = np.maximum(0.0, np.abs(projected) - all_bounds)
        residual = float(np.max(errors, initial=0))
        relative_residual = float(
            np.max(errors / np.maximum(all_bounds, 1e-12), initial=0)
        )
        # Relative tolerance prevents tiny edges from passing the metre-based
        # test while their grade/curvature still exceeds its physical limit.
        if np.all(
            errors
            <= np.minimum(settings.constraintToleranceMeters, all_bounds * 1e-4) + 1e-12
        ):
            converged = True
            break
    for profile in profiles:
        if profile.road_id in mappings:
            profile.heights = values[mappings[profile.road_id]].tolist()
            if not converged:
                profile.warnings.append("network_constraint_iteration_limit")
        profile.metrics["conditioned"] = profile_metrics(
            profile.distances, profile.heights
        )
        profile.metrics["max_abs_terrain_deviation"] = float(
            np.max(np.abs(np.array(profile.heights) - profile.raw_heights))
        )
    return profiles, {
        "scope": "phase G numerical prototype; not applied to Unity meshes",
        "settings": asdict(settings),
        "junction_sections": junction_sections,
        "bridge_approach_connections": bridge_connections,
        "strategies": dict(Counter(p.strategy.value for p in profiles)),
        "bridge_profiles": sum(bool(p.bridge_height_method) for p in profiles),
        "hidden_tunnel_profiles": sum(not p.surface_visible for p in profiles),
        "shared_automotive_nodes": sum(
            len(owners) > 1 for owners in shared_owners.values()
        ),
        "constraint_iterations": iterations,
        "constraint_converged": converged,
        "constraint_batches": len(batches),
        "max_normalized_constraint_residual_m": residual,
        "max_relative_constraint_residual": relative_residual,
        "warnings": dict(Counter(w for p in profiles for w in p.warnings)),
    }
