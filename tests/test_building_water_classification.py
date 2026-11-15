from shapely.geometry import box

from app.validation.building_water_classification import classify_overlap


def test_source_disagreement_is_explained_without_claiming_legitimate_pier():
    b, w = box(0, 0, 5, 5), box(4, 0, 8, 8)
    before = (b.wkb, w.wkb)
    result = classify_overlap(b, w, b, w)
    assert result["classification"] == "source_geometry_disagreement"
    assert result["explained"]
    assert result["physicalLegitimacy"] == "not established"
    assert result["intersectionAreaM2"] == 5
    assert (b.wkb, w.wkb) == before


def test_boundary_band_cannot_hide_half_metre_overlap():
    water = box(0, 0, 10, 10)
    thin = box(-2, 2, 0.01, 5)
    deep = box(-2, 2, 0.6, 5)
    assert (
        classify_overlap(thin, water, thin, water)["classification"]
        == "boundary_precision"
    )
    assert (
        classify_overlap(deep, water, deep, water)["classification"]
        == "source_geometry_disagreement"
    )


def test_missing_evidence_and_introduced_overlap_are_not_allowed():
    b, w = box(0, 0, 5, 5), box(4, 0, 8, 8)
    assert not classify_overlap(None, w, b, w)["explained"]
    result = classify_overlap(box(-6, 0, -1, 5), w, b, w)
    assert result["classification"] == "fusion_error"
    assert result["requiresCorrection"]
