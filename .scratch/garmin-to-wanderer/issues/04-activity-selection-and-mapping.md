# Define activity selection and sport mapping

Type: grilling
Status: resolved
Blocked by: none

## Question

Which Garmin activities should be imported, and how should they map to
Wanderer?

- Import every activity type, or a configured allow/deny list?
- Garmin type/subtype → Wanderer category/subcategory mapping (cycling, hiking,
  running, walking, skiing, …).
- How should activities without GPS be handled (indoor cycling, strength,
  treadmill): skip, import without a track, or import a summary only?
- How should title, description, date, and difficulty be set? Use the Garmin
  activity name or a template?
- Import only completed activities, never planned courses?

Leaning: import all GPS-bearing activities by default, skip no-GPS activities
with a line in the report, drive the sport mapping from config, and use the
Garmin title as the Wanderer name.

Context from ticket 02: server-side FIT→GPX conversion drops heart rate. If HR
fidelity matters, convert client-side with `fitdecode` + `gpxpy`. Wanderer
categories and subcategories are 15-character IDs fetched from the API, so the
mapping must resolve names to IDs at runtime.

## Research context

Wanderer v0.21.2 seeds eight global categories and sixteen subcategories. `id`
is a 15-character instance-specific PocketBase id; `name` is the canonical key
(no slug). Resolve normalized names to IDs at runtime with
`GET /api/v1/category?perPage=-1` and `GET /api/v1/subcategory?perPage=-1`.
Subcategories belong to a parent category. A trail may have no category; if a
mapped name is missing, fall back to `Other`, and if `Other` is missing, send no
category.

Default categories and relevant subcategories:

| Category | Subcategories |
|---|---|
| Hiking | Winter, Alpine, Long-distance, Snowshoeing, Family, Pilgrimage |
| Walking | — |
| Running | Trail, Road |
| Climbing | — |
| Skiing | Cross-country, Skating, Backcountry |
| Canoeing | — |
| Biking | MTB, Gravel, Touring, Road, E-Bike |
| Other | — |

Proposed default mapping (Garmin `typeKey` → Wanderer category/subcategory):

| Garmin `typeKey` | Wanderer |
|---|---|
| `cycling` | Biking |
| `road_biking`, `road_cycling` | Biking / Road |
| `mountain_biking`, `downhill_biking`, `enduro_mtb`, `bmx` | Biking / MTB |
| `gravel_cycling`, `unbound_gravel_cycling`, `cyclocross` | Biking / Gravel |
| `e_bike_mountain`, `e_bike_fitness` | Biking / E-Bike |
| `indoor_cycling`, `indoor_bike`, `virtual_ride` | Biking / Road |
| `hiking` | Hiking |
| `mountaineering` | Hiking / Alpine |
| `snow_shoe`, `snow_shoe_ws` | Hiking / Snowshoeing |
| `walking`, `casual_walking`, `speed_walking`, `indoor_walking` | Walking |
| `running` | Running |
| `trail_running`, `ultra_run` | Running / Trail |
| `street_running`, `track_running`, `treadmill_running`, `virtual_run` | Running / Road |
| `resort_skiing`, `resort_skiing_snowboarding`, `snow_skiing`, `snowboarding` | Skiing |
| `backcountry_skiing`, `backcountry_skiing_snowboarding` | Skiing / Backcountry |
| `cross_country_skiing`, `cross_country_indoor_skiing` | Skiing / Cross-country |
| `skate_skiing`, `skating` | Skiing / Skating |
| `kayaking`, `paddling`, `stand_up_paddleboarding`, `whitewater_rafting` | Canoeing |
| `rowing`, `indoor_rowing` | Canoeing |
| `rock_climbing`, `indoor_climbing`, `bouldering` | Climbing |
| everything else, including swimming and strength | Other |

Garmin returns a specific `activityType.typeKey` plus a broad `parentTypeId`.
Handle `_v2`/`_ws` aliases. The mapping must be config-overridable because
Wanderer categories can be renamed or customised per instance.

## Answer

Resolved with the user: **A / A / A / A**.

- **Scope:** import every Garmin activity that has GPS, with optional config
  `include`/`exclude` filters on Garmin `typeKey`/`parentTypeId`. Default: all
  GPS-bearing activities.
- **No GPS:** skip and report (`skipped_no_gps`); do not create trackless
  trails. A future `--include-no-gps` can add them.
- **HR/cadence/power:** do not preserve client-side. Send the original FIT and
  accept that Wanderer's server-side FIT→GPX conversion drops HR. Wanderer has
  no HR field, so this is acceptable for now.
- **Metadata:** `name` = Garmin activity name (fallback `"<type> <date>"` if
  empty); `description` = Garmin description if present; `difficulty` left at
  Wanderer's default (`easy`) or omitted.
- **Mapping:** use the proposed default table in this ticket, config-overridable
  by Garmin `typeKey`; resolve Wanderer category/subcategory names to IDs at
  runtime; fall back to `Other`; if `Other` is missing, send no category.
  Swimming maps to `Other` and snowboarding to `Skiing` because Wanderer's
  defaults have no dedicated category.
- **Completed only:** Garmin's activity list already returns completed
  activities; no planned courses.
