from __future__ import annotations

from garmin_to_wanderer.mapping import (
    WandererTaxonomy,
    base_type_key,
    resolve_category,
)


def taxonomy() -> WandererTaxonomy:
    categories = [
        {"id": "cat-biking", "name": "Biking"},
        {"id": "cat-hiking", "name": "Hiking"},
        {"id": "cat-running", "name": "Running"},
        {"id": "cat-other", "name": "Other"},
    ]
    subcategories = [
        {"id": "sub-road", "name": "Road", "category": "cat-biking"},
        {"id": "sub-mtb", "name": "MTB", "category": "cat-biking"},
        {"id": "sub-trail", "name": "Trail", "category": "cat-running"},
    ]
    return WandererTaxonomy.from_api(categories, subcategories)


def test_base_type_key_strips_aliases():
    assert base_type_key("road_biking_v2") == "road_biking"
    assert base_type_key("snow_shoe_ws") == "snow_shoe"
    assert base_type_key("hiking") == "hiking"


def test_default_mapping():
    assert resolve_category(
        type_key="road_biking",
        parent_type_id=2,
        config_map={},
        taxonomy=taxonomy(),
    ) == ("cat-biking", "sub-road")


def test_aliases_are_resolved():
    assert resolve_category(
        type_key="road_biking_v2",
        parent_type_id=2,
        config_map={},
        taxonomy=taxonomy(),
    ) == ("cat-biking", "sub-road")


def test_parent_fallback():
    assert resolve_category(
        type_key="unknown_bike_type",
        parent_type_id=2,
        config_map={},
        taxonomy=taxonomy(),
    ) == ("cat-biking", None)


def test_unknown_falls_back_to_other():
    assert resolve_category(
        type_key="strength_training",
        parent_type_id=None,
        config_map={},
        taxonomy=taxonomy(),
    ) == ("cat-other", None)


def test_config_overrides_default():
    assert resolve_category(
        type_key="road_biking",
        parent_type_id=2,
        config_map={"road_biking": ("Hiking", None)},
        taxonomy=taxonomy(),
    ) == ("cat-hiking", None)


def test_missing_category_falls_back_to_other():
    taxonomy_without_other = WandererTaxonomy.from_api([{"id": "cat-biking", "name": "Biking"}], [])
    assert resolve_category(
        type_key="swimming",
        parent_type_id=None,
        config_map={},
        taxonomy=taxonomy_without_other,
    ) == (None, None)
