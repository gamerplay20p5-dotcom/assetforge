"""Premium Stylized house kit: archetypes, JSON spec round-trip/validation, components and the export pipeline."""

import copy
import json

import numpy as np
import pytest
from assetforge_contract import BuildingParams
from assetforge_procedural import generate_building
from assetforge_procedural.components import Opening, bbox, wall_with_openings
from assetforge_procedural.house import ARCHETYPES, HouseSpec, generate_house
from assetforge_procedural.mesh import MeshBuilder


@pytest.mark.parametrize("name", sorted(ARCHETYPES))
def test_every_archetype_builds_a_closed_textured_house(name):
    gen = generate_house(ARCHETYPES[name](1))
    assert 1_000 < gen.mesh.triangle_count < 9_000  # low/mid poly
    lo, hi = gen.mesh.bounds()
    assert abs(lo[1]) < 1e-4 and abs((lo[0] + hi[0]) / 2) < 1e-3 and abs((lo[2] + hi[2]) / 2) < 1e-3  # pivot bottom-center
    assert {"wall", "roof", "glass", "trim"} <= set(gen.mesh.parts)
    for part in gen.mesh.parts.values():
        assert np.isfinite(part.vertices).all() and np.isfinite(part.uvs).all()
        assert part.faces.max() < len(part.vertices)
    assert gen.summary["archetype"] == name and gen.summary["spec"]["wings"]


def test_spec_json_roundtrip_regenerates_the_same_house():
    spec = ARCHETYPES["tudor_cottage"](3)
    again = HouseSpec.from_dict(json.loads(json.dumps(spec.to_dict())))
    a, b = generate_house(spec), generate_house(again)
    assert a.mesh.triangle_count == b.mesh.triangle_count and a.dimensions == pytest.approx(b.dimensions)


def test_individual_component_edits_change_only_that_component():
    base = ARCHETYPES["nordic_cabin"](1).to_dict()
    no_chimney = copy.deepcopy(base)
    no_chimney["features"] = [f for f in base["features"] if f["type"] != "chimney"]
    a, b = generate_house(base), generate_house(no_chimney)
    assert b.mesh.triangle_count < a.mesh.triangle_count
    assert b.mesh.parts["wall"].faces.shape == a.mesh.parts["wall"].faces.shape  # walls untouched
    taller = copy.deepcopy(base)
    taller["wings"][0]["floors"] = 3
    assert generate_house(taller).dimensions[1] > a.dimensions[1] + 2


@pytest.mark.parametrize("patch,msg", [
    ({"wings": []}, "at least one wing"),
    ({"wall_kind": "lava"}, "wall_kind"),
    ({"features": [{"type": "porch", "wing": "nope"}]}, "unknown wing"),
    ({"features": [{"type": "spaceship"}]}, "unknown feature"),
    ({"bogus": 1}, "unknown field"),
])
def test_invalid_specs_are_rejected(patch, msg):
    d = ARCHETYPES["modern"](1).to_dict()
    d.update(patch)
    with pytest.raises(ValueError, match=msg):
        HouseSpec.from_dict(d)


def test_wing_dimension_limits_are_enforced():
    d = ARCHETYPES["modern"](1).to_dict()
    d["wings"][0]["w"] = 900
    with pytest.raises(ValueError, match="width/depth"):
        HouseSpec.from_dict(d)


def test_wall_with_openings_leaves_a_real_hole():
    mb = MeshBuilder()
    wall_with_openings(mb, "wall", -2, 2, 0, 3, [Opening(0, 1, 0.8, 2.2)], 0.15, "wall")
    spec = mb.build()
    front = spec.parts["wall"]
    z0 = front.vertices[:, 2] > -1e-6
    assert z0.any()
    tri_area = 0.0
    for f in front.faces:
        v = front.vertices[f]
        if np.allclose(v[:, 2], 0):
            tri_area += 0.5 * np.linalg.norm(np.cross(v[1] - v[0], v[2] - v[0]))
    assert tri_area == pytest.approx(4 * 3 - 1 * 1.4, abs=1e-3)  # wall area minus the opening


def test_bevel_box_keeps_outward_normals():
    mb = MeshBuilder()
    bbox(mb, "m", (0, 0, 0), (1, 1, 1), bevel=0.1)
    part = mb.build().parts["m"]
    centre = np.array([0.5, 0.5, 0.5])
    for f, n in zip(part.faces, part.normals[part.faces[:, 0]], strict=True):
        c = part.vertices[f].mean(axis=0)
        assert np.dot(n, c - centre) > 0


def test_contract_dispatch_uses_the_house_kit_only_when_asked():
    classic = generate_building(BuildingParams(category="house", seed=2))
    kit = generate_building(BuildingParams(category="house", archetype="colonial", seed=2))
    assert classic.summary.get("archetype") is None and kit.summary["archetype"] == "colonial"
    custom = generate_building(BuildingParams(category="house", house_spec=ARCHETYPES["modern"](1).to_dict()))
    assert custom.summary["archetype"] == "modern"
