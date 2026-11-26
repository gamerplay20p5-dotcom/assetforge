import hashlib

import numpy as np
import pytest
from assetforge_contract import BuildingParams, QualityProfile, triangle_budget
from assetforge_optimization import clean_mesh
from assetforge_procedural import MeshBuilder, generate_building
from assetforge_procedural.building import PRESETS
from assetforge_validation import check_mesh_spec


def _hash(spec) -> str:
    h = hashlib.sha256()
    for name in sorted(spec.parts):
        p = spec.parts[name]
        h.update(name.encode())
        h.update(np.round(p.vertices, 4).tobytes())
        h.update(p.faces.tobytes())
    return h.hexdigest()


def test_box_faces_point_outward():
    mb = MeshBuilder()
    mb.box("m", (-1, 0, -2), (1, 3, 2))
    spec = mb.build()
    part = spec.parts["m"]
    centre = np.array([0, 1.5, 0])
    tri = part.vertices[part.faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    out = ((tri.mean(axis=1) - centre) * n).sum(axis=1)
    assert len(part.faces) == 12 and (out > 0).all()
    assert np.allclose(np.linalg.norm(part.normals, axis=1), 1, atol=1e-5)


def test_yaw_transform_rotates_front_to_plus_x():
    mb = MeshBuilder()
    with mb.transform(90, (5, 0, 0)):
        mb.quad("m", (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))  # faces +Z locally
    n = mb.build().parts["m"].normals[0]
    assert np.allclose(n, [1, 0, 0], atol=1e-5)


def test_weld_removes_duplicate_vertices():
    mb = MeshBuilder()
    mb.quad("m", (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))
    spec = mb.build()
    assert spec.parts["m"].vertices.shape[0] == 4 and spec.triangle_count == 2


@pytest.mark.parametrize("category", sorted(PRESETS))
def test_every_category_generates_valid_geometry(category):
    gen = generate_building(BuildingParams(category=category, style="classic", seed=7))
    spec, _ = clean_mesh(gen.mesh)
    report = check_mesh_spec(spec, category, QualityProfile.stylized_standard)
    assert report.passed, [c for c in report.checks if c.status == "fail"]
    lo, hi = spec.bounds()
    assert abs(lo[1]) < 1e-3 and abs((lo[0] + hi[0]) / 2) < 1e-3  # pivot bottom-center
    assert {"entrance", "roof_access"} & {c["name"] for c in gen.connection_points}


def test_generation_is_deterministic_and_seed_sensitive():
    p = BuildingParams(category="house", seed=42)
    assert _hash(generate_building(p).mesh) == _hash(generate_building(p).mesh)
    assert _hash(generate_building(p).mesh) != _hash(generate_building(p.model_copy(update={"seed": 43})).mesh)


def test_explicit_dimensions_are_respected():
    gen = generate_building(BuildingParams(category="commercial", width=20, depth=14, floors=4, seed=1))
    lo, hi = gen.mesh.bounds()
    assert gen.summary["floors"] == 4
    assert 20 <= (hi - lo)[0] <= 24  # awnings/cornices may extend the bounding box slightly
    assert (hi - lo)[1] > 4 * 3.0


def test_house_triangles_within_budget_for_default_profile():
    for seed in range(1, 7):
        n = generate_building(BuildingParams(category="house", seed=seed, detail=2)).mesh.triangle_count
        assert n <= triangle_budget("house", QualityProfile.stylized_standard)[1]


def test_validation_flags_broken_meshes():
    gen = generate_building(BuildingParams(category="house", seed=1))
    spec, _ = clean_mesh(gen.mesh)
    part = next(iter(spec.parts.values()))
    part.vertices[0, 0] = np.nan
    report = check_mesh_spec(spec, "house", QualityProfile.stylized_standard)
    assert not report.passed and any(c.name == "finite_vertices" for c in report.errors)


def test_validation_warns_over_budget():
    gen = generate_building(BuildingParams(category="apartment", seed=1))
    spec, _ = clean_mesh(gen.mesh)
    report = check_mesh_spec(spec, "apartment", QualityProfile.stylized_standard, triangle_limit=500)
    assert report.passed and any(c.name == "triangle_budget" and c.status == "warn" for c in report.checks)


def test_clean_mesh_moves_pivot_and_drops_degenerates():
    mb = MeshBuilder()
    mb.box("m", (10, 5, 10), (12, 8, 14))
    spec = mb.build()
    part = spec.parts["m"]
    part.faces = np.vstack([part.faces, [[0, 0, 0]]]).astype(np.int32)  # degenerate triangle
    cleaned, stats = clean_mesh(spec)
    lo, hi = cleaned.bounds()
    assert stats.degenerate_removed == 1 and abs(lo[1]) < 1e-6 and abs(lo[0] + hi[0]) < 1e-5
