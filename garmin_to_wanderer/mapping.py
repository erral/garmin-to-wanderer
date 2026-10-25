from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

# Garmin typeKey -> (Wanderer category name, Wanderer subcategory name or None)
DEFAULT_CATEGORY_MAP: dict[str, tuple[str, str | None]] = {
    "cycling": ("Biking", None),
    "road_biking": ("Biking", "Road"),
    "road_cycling": ("Biking", "Road"),
    "mountain_biking": ("Biking", "MTB"),
    "downhill_biking": ("Biking", "MTB"),
    "enduro_mtb": ("Biking", "MTB"),
    "e_enduro_mtb": ("Biking", "MTB"),
    "bmx": ("Biking", "MTB"),
    "gravel_cycling": ("Biking", "Gravel"),
    "unbound_gravel_cycling": ("Biking", "Gravel"),
    "cyclocross": ("Biking", "Gravel"),
    "e_bike_mountain": ("Biking", "E-Bike"),
    "e_bike_fitness": ("Biking", "E-Bike"),
    "indoor_cycling": ("Biking", "Road"),
    "indoor_bike": ("Biking", "Road"),
    "virtual_ride": ("Biking", "Road"),
    "track_cycling": ("Biking", None),
    "recumbent_cycling": ("Biking", None),
    "hand_cycling": ("Biking", None),
    "indoor_hand_cycling": ("Biking", None),
    "hiking": ("Hiking", None),
    "mountaineering": ("Hiking", "Alpine"),
    "rucking": ("Hiking", None),
    "snow_shoe": ("Hiking", "Snowshoeing"),
    "walking": ("Walking", None),
    "casual_walking": ("Walking", None),
    "speed_walking": ("Walking", None),
    "indoor_walking": ("Walking", None),
    "step_tracking_and_walking": ("Walking", None),
    "running": ("Running", None),
    "trail_running": ("Running", "Trail"),
    "ultra_run": ("Running", "Trail"),
    "street_running": ("Running", "Road"),
    "track_running": ("Running", "Road"),
    "treadmill_running": ("Running", "Road"),
    "indoor_running": ("Running", "Road"),
    "virtual_run": ("Running", "Road"),
    "obstacle_run": ("Running", None),
    "resort_skiing_snowboarding": ("Skiing", None),
    "resort_skiing": ("Skiing", None),
    "resort_snowboarding": ("Skiing", None),
    "snow_skiing": ("Skiing", None),
    "snowboarding": ("Skiing", None),
    "backcountry_skiing_snowboarding": ("Skiing", "Backcountry"),
    "backcountry_skiing": ("Skiing", "Backcountry"),
    "backcountry_snowboarding": ("Skiing", "Backcountry"),
    "cross_country_skiing": ("Skiing", "Cross-country"),
    "cross_country_indoor_skiing": ("Skiing", "Cross-country"),
    "skate_skiing": ("Skiing", "Skating"),
    "skating": ("Skiing", "Skating"),
    "kayaking": ("Canoeing", None),
    "paddling": ("Canoeing", None),
    "stand_up_paddleboarding": ("Canoeing", None),
    "whitewater_rafting": ("Canoeing", None),
    "whitewater_rafting_kayaking": ("Canoeing", None),
    "rowing": ("Canoeing", None),
    "indoor_rowing": ("Canoeing", None),
    "rock_climbing": ("Climbing", None),
    "indoor_climbing": ("Climbing", None),
    "bouldering": ("Climbing", None),
    "floor_climbing": ("Climbing", None),
}

PARENT_TYPE_MAP: dict[int, tuple[str, None]] = {
    1: ("Running", None),
    2: ("Biking", None),
    3: ("Hiking", None),
    9: ("Walking", None),
    26: ("Other", None),
    29: ("Other", None),
    165: ("Skiing", None),
    228: ("Canoeing", None),
}


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(ascii_only.casefold().replace("-", " ").replace("_", " ").split())


def base_type_key(type_key: str) -> str:
    key = type_key.strip().lower()
    for suffix in ("_v2", "_ws"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    return key


@dataclass(frozen=True, slots=True)
class WandererTaxonomy:
    categories: dict[str, str]
    subcategories: dict[tuple[str, str], str]

    @classmethod
    def from_api(
        cls,
        categories: list[dict[str, Any]],
        subcategories: list[dict[str, Any]],
    ) -> WandererTaxonomy:
        category_lookup: dict[str, str] = {}
        for category in categories:
            category_id = str(category.get("id", ""))
            name = category.get("name")
            if category_id and name:
                category_lookup[normalize_name(str(name))] = category_id

        subcategory_lookup: dict[tuple[str, str], str] = {}
        for subcategory in subcategories:
            subcategory_id = str(subcategory.get("id", ""))
            name = subcategory.get("name")
            parent = subcategory.get("category")
            if isinstance(parent, list):
                parent = parent[0] if parent else None
            if subcategory_id and name and parent:
                key = (str(parent), normalize_name(str(name)))
                subcategory_lookup[key] = subcategory_id

        return cls(category_lookup, subcategory_lookup)

    def category_id(self, name: str | None) -> str | None:
        if not name:
            return None
        return self.categories.get(normalize_name(name))

    def subcategory_id(self, category_id: str | None, name: str | None) -> str | None:
        if not category_id or not name:
            return None
        return self.subcategories.get((category_id, normalize_name(name)))


def resolve_category(
    *,
    type_key: str,
    parent_type_id: int | None,
    config_map: dict[str, tuple[str, str | None]],
    taxonomy: WandererTaxonomy,
    default_category: str | None = "Other",
) -> tuple[str | None, str | None]:
    mapping = _find_mapping(
        type_key=type_key,
        parent_type_id=parent_type_id,
        config_map=config_map,
    )
    if mapping is None:
        mapping = (default_category, None)

    category_name, subcategory_name = mapping
    category_id = taxonomy.category_id(category_name)

    if category_id is None and default_category:
        category_id = taxonomy.category_id(default_category)
        subcategory_name = None

    subcategory_id = taxonomy.subcategory_id(category_id, subcategory_name)
    return category_id, subcategory_id


def _find_mapping(
    *,
    type_key: str,
    parent_type_id: int | None,
    config_map: dict[str, tuple[str, str | None]],
) -> tuple[str, str | None] | None:
    key = type_key.strip().lower()
    base = base_type_key(key)

    for candidate in dict.fromkeys((key, base)):
        if candidate in config_map:
            return config_map[candidate]
        if candidate in DEFAULT_CATEGORY_MAP:
            return DEFAULT_CATEGORY_MAP[candidate]

    if parent_type_id is not None:
        try:
            parent = int(parent_type_id)
        except (TypeError, ValueError):
            parent = None
        if parent in PARENT_TYPE_MAP:
            return PARENT_TYPE_MAP[parent]

    return None
