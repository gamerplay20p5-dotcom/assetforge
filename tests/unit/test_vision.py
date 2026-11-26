"""Vision front-end: strict description schema, JSON extraction from model answers, scoring and the description -> kit mapping."""

import pytest
from assetforge_procedural.house import generate_house
from assetforge_vision import TRUTH
from assetforge_vision.evaluate import compare, score
from assetforge_vision.mapper import description_to_spec
from assetforge_vision.schema import DescriptionError, extract_json, parse_description

OK = dict(floors=2, roof_type="Hip", roof_color="dark gray", wall_material="siding", wall_color="blue", trim_color="cream", door_color="orange",
          door_position="center", windows_front_per_floor=[1, 2], porch="portico", garage=False, chimney=False, volumes="single", bay_window=False)


def _first(v):
    return v[0] if isinstance(v, list) and v and not isinstance(v[0], int) else v


def test_extract_json_handles_fences_prose_and_nested_braces():
    text = 'Here you go:\n```json\n{"a": {"b": "}"}, "c": [1, 2]}\n```\nthanks'
    assert extract_json(text) == {"a": {"b": "}"}, "c": [1, 2]}
    with pytest.raises(Exception, match="no JSON"):
        extract_json("nothing here")
    with pytest.raises(Exception, match="unterminated"):
        extract_json('{"a": 1')


def test_parse_normalises_case_and_spaces_but_rejects_unknown_values():
    d = parse_description(OK)
    assert d.roof_type == "hip" and d.roof_color == "dark_gray"
    for bad in ({"floors": 9}, {"roof_type": "dome"}, {"wall_color": "magenta"}, {"windows_front_per_floor": [99]}, {"garage": "yes"}):
        with pytest.raises(DescriptionError):
            parse_description({**OK, **bad})
    with pytest.raises(DescriptionError, match="missing"):
        parse_description({"floors": 1})


def test_scoring_does_not_reward_missing_fields_filled_by_defaults():
    t = TRUTH["02_sobrado_azul"]
    partial = {k: v for k, v in OK.items() if k in ("floors", "roof_type", "wall_material", "wall_color", "roof_color")}
    d = parse_description(partial)
    hit_lenient, tot = score(compare(d, t))
    hit_strict, _ = score(compare(d, t, present=set(partial)))
    assert hit_strict < hit_lenient and hit_strict <= 5 and tot > 10


def test_colour_families_are_coarse_not_exact():
    t = TRUTH["02_sobrado_azul"]  # blue
    res = compare(parse_description({**OK, "wall_color": "gray blue"}), t)
    assert res["wall_color"]["ok"]
    assert not compare(parse_description({**OK, "wall_color": "red"}), t)["wall_color"]["ok"]


@pytest.mark.parametrize("name", sorted(TRUTH))
def test_ground_truth_maps_to_a_buildable_kit_house_at_every_stage(name):
    t = TRUTH[name]
    d = parse_description({**{k: _first(v) for k, v in t.items()}})
    spec = description_to_spec(d)
    for st in (1, 3, 6):
        assert generate_house(spec, st).mesh.triangle_count > 0
    assert generate_house(spec, 6).summary["archetype"].startswith("vision:")


def test_garage_and_porch_edits_follow_the_description():
    base = {k: _first(v) for k, v in TRUTH["06_sobrado_verde_garagem"].items()}
    with_g = description_to_spec(parse_description(base))
    no_g = description_to_spec(parse_description({**base, "garage": False, "garage_side": "none", "volumes": "single", "porch": "none"}))
    assert any(w.garage for w in with_g.wings) and not any(w.garage for w in no_g.wings)
    assert not any(f.type == "porch" for f in no_g.features)


def test_split_wall_only_counts_brick_under_a_different_wall():
    from assetforge_vision.mapper import has_split_wall

    base = {k: _first(v) for k, v in TRUTH["03_casa_amarela_meios_niveis"].items()}
    assert has_split_wall(parse_description(base))
    assert not has_split_wall(parse_description({**base, "lower_wall_material": "siding", "lower_wall_color": "blue"}))  # invented by the model
    assert not has_split_wall(parse_description({**base, "wall_material": "brick"}))


def test_analysis_accepts_any_category_and_routes_honestly():
    from assetforge_vision.kits import route
    from assetforge_vision.schema import parse_analysis

    car = parse_analysis('{"category": "Car", "subject": "red sports car", "isolated_object": true, "house": null}')
    assert car.category == "vehicle" and car.house is None
    r = route(car)
    assert r["mode"] == "fallback" and r["fallback"] == "triposr" and "kit" in r["message"].lower()
    scene = parse_analysis('{"category": "other", "subject": "a map", "isolated_object": false, "house": null}')
    assert route(scene)["mode"] == "none"
    house = parse_analysis({"category": "house", "subject": "blue house", "isolated_object": False, "house": {k: _first(v) for k, v in TRUTH["02_sobrado_azul"].items()}})
    assert route(house)["mode"] == "kit" and house.house is not None
    legacy = parse_analysis({k: _first(v) for k, v in TRUTH["02_sobrado_azul"].items()})  # old house-only answers still work
    assert legacy.category == "house"
    with pytest.raises(DescriptionError):
        parse_analysis('{"category": "house", "subject": "x", "isolated_object": false, "house": null}')
    with pytest.raises(DescriptionError):
        parse_analysis('{"category": "spaceship", "subject": "x", "isolated_object": false}')


def test_ground_like_subjects_never_go_to_the_mesh_provider():
    """Regression for a measured failure: the model called flat ground 'baseball field' and an isolated object."""
    from assetforge_vision.kits import looks_flat, route
    from assetforge_vision.schema import parse_analysis

    ground = parse_analysis('{"category": "prop", "subject": "baseball field", "isolated_object": true, "house": null}')
    assert looks_flat("baseball field") and route(ground)["mode"] == "none"
    chair = parse_analysis('{"category": "prop", "subject": "wooden chair", "isolated_object": true, "house": null}')
    assert route(chair)["mode"] == "fallback"
    assert "256" in route(chair, (172, 96))["message"] and "256" not in route(chair, (800, 600))["message"]
