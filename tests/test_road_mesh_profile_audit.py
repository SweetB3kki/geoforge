import pytest

from app.validation.road_mesh_profile_audit import audit, measure


def test_affine_profile_has_same_grade_with_unequal_spacing():
    result = measure([[0, 0], [2, 0], [5, 0]], [4, 4.2, 4.5], 0.18, 0.015)
    assert result["max_abs_grade"] == pytest.approx(0.1)
    assert result["max_abs_curvature"] == pytest.approx(0)
    assert result["grade_exceeded_at_segment"] == []


def test_small_height_errors_can_violate_mesh_curvature():
    result = measure([[0, 0], [1, 0], [2, 0]], [0, 0.01, 0], 0.18, 0.015)
    assert result["grade_exceeded_at_segment"] == []
    assert result["curvature_exceeded_at_sample"] == [1]


def test_missing_hits_are_not_bridged_or_reported_as_flat():
    result = measure([[0, 0], [1, 0], [2, 0]], [0, None, 1], 0.18, 0.015)
    assert result["missing_samples"] == 1
    assert result["checked_segments"] == result["checked_triples"] == 0
    assert result["max_abs_grade"] is None
    assert result["max_abs_curvature"] is None


@pytest.mark.parametrize(
    "points,heights",
    [
        ([[0, 0], [0, 0]], [0, 1]),
        ([[0, 0], [1, 0]], [0]),
        ([[0, 0], [1, 0]], [0, float("nan")]),
    ],
)
def test_invalid_measurements_fail(points, heights):
    with pytest.raises(ValueError):
        measure(points, heights, 0.18, 0.015)


def test_stale_scene_evidence_is_rejected(tmp_path):
    scene = tmp_path / "scene.json"
    checks = tmp_path / "checks.json"
    scene.write_text("{}")
    checks.write_text('{"sceneSha256":"stale"}')
    with pytest.raises(ValueError, match="different scene"):
        audit(scene, checks)
