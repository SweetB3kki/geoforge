"""Explain overlaps without deleting geography or asserting ground truth."""


def classify_overlap(source_building, source_water, building, water, epsilon=0.02):
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    overlap = building.intersection(water)
    result = dict(
        intersectionAreaM2=overlap.area,
        intersectionPercentage=100 * overlap.area / building.area,
        epsilonMeters=epsilon,
        geometryModified=False,
    )
    if overlap.is_empty or overlap.area <= 1e-10:
        return {**result, "classification": "other", "reason": "no_positive_overlap"}
    if building.intersection(water.buffer(-epsilon)).area <= 1e-10:
        return {
            **result,
            "classification": "boundary_precision",
            "reason": "overlap lies entirely in the declared boundary band",
        }
    if source_building is None or source_water is None:
        return {
            **result,
            "classification": "other",
            "explained": False,
            "reason": "missing source geometry evidence",
        }
    original = source_building.intersection(source_water)
    if original.area > 1e-10:
        return {
            **result,
            "classification": "source_geometry_disagreement",
            "explained": True,
            "sourceIntersectionAreaM2": original.area,
            "reason": "independent provider footprints already overlap before fusion",
            "physicalLegitimacy": "not established",
            "erroneousProvider": "not established",
        }
    return {
        **result,
        "classification": "fusion_error",
        "explained": True,
        "reason": "overlap introduced after source geometry stage",
        "requiresCorrection": True,
    }
