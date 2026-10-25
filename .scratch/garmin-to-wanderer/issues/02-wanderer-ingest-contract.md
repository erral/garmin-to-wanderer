# Confirm Wanderer ingest contract

Type: research
Status: resolved
Blocked by: none

## Question

Determine exactly how Wanderer ingests an activity through its HTTP API, so the
tool knows what to send and what metadata it can preserve:

- Does `PUT /api/v1/trail/upload` accept FIT, GPX, TCX, and KML? Does it keep the
  original file, or convert everything to GPX?
- Which metadata does Wanderer derive from the file (name, date, distance,
  duration, elevation, start point), and which fields can be supplied
  explicitly?
- How do we set `category`/`subcategory`, `difficulty`, `description`, and
  visibility after the upload?
- What is the duplicate-detection behaviour and response? When is
  `ignoreDuplicates=true` needed?
- Confirm API-token auth (`Authorization: Bearer wanderer_key_...`), the maximum
  file size, and error response shapes.
- If FIT is not accepted, which FIT→GPX conversion path preserves timestamps,
  track points, and elevation?

Leaning: send the original Garmin FIT if Wanderer preserves it; otherwise
convert to GPX with a tested library.

## Answer

Researched against Wanderer v0.21.2 (tag `a241d1b`). No live instance was
tested.

### Upload endpoint

- `PUT /api/v1/trail/upload` is **multipart/form-data**. Parts: required `file`;
  optional `name` (fallback only); optional `ignoreDuplicates` with literal
  string `"true"`. No other fields are read.
- Auth: session cookie **or** `Authorization: Bearer wanderer_key_...`. The
  upload endpoint accepts the API token directly. Token scope is the whole
  account; there are no endpoint scopes.
- Accepted formats: **GPX, FIT, KML, KMZ, TCX**.
- **FIT is converted to GPX server-side and the original FIT is discarded.**
  Plain track GPX is stored byte-for-byte; route-only GPX is reserialized.
  Stored file is the `trails.gpx` field, max **5 MiB** (HTTP body limit is 2 GiB
  by default but the file field is 5 MiB).
- Success status is `200` (OpenAPI's `201` is wrong).
- Source: [upload route](https://github.com/open-wanderer/wanderer/blob/a241d1b391e2ea388762e3bf617244afb7b892c3/web/src/routes/api/v1/trail/upload/%2Bserver.ts#L47-L117),
  [format detection](https://github.com/open-wanderer/wanderer/blob/a241d1b391e2ea388762e3bf617244afb7b892c3/web/src/lib/util/gpx_util.ts#L190-L233).

### Metadata

- Derived: `name` from GPX metadata → first track/route name → request `name` →
  `trail-<ISO>`; `date` from the first trackpoint time truncated to UTC
  `YYYY-MM-DD`; `distance` by Haversine; `duration` from segment timestamps;
  `elevation_gain/loss`; start `lat`/`lon`; location by reverse geocoding.
- FIT has no embedded name, so the request `name` becomes the name only if
  nothing else supplies one. The upload `name` is **not an override** when the
  GPX has a name.
- **Start time-of-day is not stored**; only the date. The timestamp remains
  inside the stored GPX.
- `category`, `subcategory`, and `difficulty` are **not derived**; difficulty
  defaults to `"easy"`. `public` comes from the user's privacy setting, not the
  request.
- Only `name` and `ignoreDuplicates` can be supplied at upload. Everything else
  needs a second call.
- Source: [gpx2trail](https://github.com/open-wanderer/wanderer/blob/a241d1b391e2ea388762e3bf617244afb7b892c3/web/src/lib/util/gpx_util.ts#L44-L81).

### Setting metadata after upload

- **`POST /api/v1/trail/form/{id}`** (multipart update) accepts `description`,
  `difficulty`, `category`, `subcategory`, `public`, `date`, etc. No required
  metadata fields; `author` is stripped.
- **`POST /api/v1/trail/{id}`** (JSON update) works too, but
  `TrailUpdateSchema` still requires `name` even for a partial patch.
- `category`/`subcategory` are **15-character relation IDs**, not names. Fetch
  them with `GET /api/v1/category?perPage=-1` and
  `GET /api/v1/subcategory?perPage=-1`.
- `difficulty` is `easy | moderate | difficult`; `public` is the visibility
  control; `description` is free text.
- `author` is an **ActivityPub actor ID**, not a user ID. Upload sets it
  automatically; do not try to set it.
- Source: [form update](https://github.com/open-wanderer/wanderer/blob/a241d1b391e2ea388762e3bf617244afb7b892c3/web/src/routes/api/v1/trail/form/%5Bid%5D/%2Bserver.ts#L45-L55),
  [update schema](https://github.com/open-wanderer/wanderer/blob/a241d1b391e2ea388762e3bf617244afb7b892c3/web/src/lib/models/api/trail_schema.ts#L32-L56).

### Duplicate detection

- Unless `ignoreDuplicates === "true"`, Wanderer searches Meilisearch for any
  trail within **100 m of the start point**, with distance within **±50 m** and
  elevation gain/loss within **±50 m**.
- It **does not compare name, date, author, or duration**. The same route on a
  different day can therefore be rejected as a duplicate.
- Duplicate response: HTTP `400`
  `{"message":"Duplicate trail","id":"...","name":"...","domain":"..."}`; no
  trail is created.
- `ignoreDuplicates=true` skips the search and creates the trail.
- Source: [duplicate check](https://github.com/open-wanderer/wanderer/blob/a241d1b391e2ea388762e3bf617244afb7b892c3/web/src/routes/api/v1/trail/upload/%2Bserver.ts#L124-L140).

### FIT→GPX fidelity

- Server-side FIT conversion preserves timestamps, lat/lon, and altitude, but
  **drops heart rate** and drops points whose `position_lat` or `position_long`
  is exactly `0`.
- If heart-rate fidelity matters, convert client-side. Permissive stack:
  `fitdecode` + `gpxpy` (MIT/Apache-2.0). Turnkey but AGPL: `fit2gpx`.
  Vendor-backed but non-OSI license: `garmin-fit-sdk`.
- Wanderer has no HR field; HR would survive only inside the stored GPX as a
  Garmin TrackPointExtension.

### Consequence for this map

- The tool needs a **two-step import**: `PUT /api/v1/trail/upload` (send FIT or
  GPX) then `POST /api/v1/trail/form/{id}` to set category, difficulty,
  description, and visibility.
- Since FIT is not preserved and same-route activities are date-blind, the
  tool's own mapping state is the reliable dedupe guard; use
  `ignoreDuplicates=true` and never rely on Wanderer's geometric check.
- Decide in ticket 04 whether HR must survive; if not, sending FIT directly is
  simplest.
