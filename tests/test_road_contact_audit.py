import struct

import numpy as np
import pytest

from app.validation.road_contact_audit import measure, read_faces


def road(rid, node="shared"):
    return dict(
        id=rid,
        node_ids=[node],
        road_category="automotive",
        layer=0,
        bridge=False,
        tunnel=False,
        vertical_profile={"surface_visible": True},
    )


def triangle(points):
    return np.array([points], dtype=float)


def test_subdivided_boundary_detects_mid_edge_step_with_equal_endpoints():
    a = triangle([(0, 0, 0), (2, 0, 0), (0, 2, 0)])
    b = np.array(
        [[(0, 0, 0), (1, 0, 0.3), (1, -1, 0)], [(1, 0, 0.3), (2, 0, 0), (1, -1, 0)]]
    )
    out = measure([road("a"), road("b")], {"a": a, "b": b})
    assert out["contacts"]["edge"]["max_gap_m"] == pytest.approx(0.3)
    assert out["contacts"]["edge"]["over_2cm"] == 2
    assert out["contacts"]["overlap"]["max_gap_m"] is None


def test_overlap_measures_clipped_vertices_of_two_sloping_planes():
    a = triangle([(0, 0, 0), (4, 0, 4), (0, 4, 0)])  # z=x
    b = triangle([(1, -1, 1), (5, 3, 1), (1, 3, 1)])
    out = measure([road("a"), road("b")], {"a": a, "b": b})
    # x=3,y=1 is an edge intersection, not an input vertex of either face.
    assert out["contacts"]["overlap"]["max_gap_m"] == pytest.approx(2)
    assert out["contacts"]["overlap"]["worst"]["xy"] == pytest.approx([3, 1])


def test_separated_roads_and_disjoint_graph_nodes_are_not_contacts():
    a = triangle([(0, 0, 0), (2, 0, 0), (0, 2, 0)])
    b = triangle([(0, -0.001, 8), (2, -0.001, 8), (0, -1, 8)])
    out = measure([road("a"), road("b"), road("c", "other")], {"a": a, "b": b, "c": a})
    assert out["pairs_without_exact_contact"] == [["a", "b"]]
    assert out["connected_road_pairs"] == 1
    assert all(v["max_gap_m"] is None for v in out["contacts"].values())


def test_reader_rejects_stale_or_truncated_mesh(tmp_path):
    path = tmp_path / "faces.bin"
    path.write_bytes(b"GFM1" + bytes(32) + struct.pack("<iii", 1, 0, 20))
    with pytest.raises(ValueError, match="different source scene"):
        read_faces(path, "ff" * 32)
    with pytest.raises(ValueError, match="Truncated"):
        read_faces(path, "00" * 32)
