# Implement core CLI, auth, and Wanderer upload

Type: task
Status: resolved
Blocked by: 01, 02, 03, 04, 05

## Question

Implement the first working vertical slice:

- Python package and CLI skeleton with config loading.
- Garmin source adapter using the chosen auth method.
- Wanderer client: upload one activity, set metadata, handle duplicate and error
  responses.
- SQLite state store and last-sync cursor.
- Tests with mocked Garmin and Wanderer responses; no live credentials in tests.

Definition of done: `sync --since ... --until ... --dry-run` lists activities,
and a real one-activity import succeeds on the user's Wanderer instance.

Context from ticket 02: implement the two-step import (`PUT
/api/v1/trail/upload`, then `POST /api/v1/trail/form/{id}`), send
`ignoreDuplicates=true`, and resolve category/subcategory IDs from the API.

## Comments

### 2026-10-25 — Core implementation landed

- `pyproject.toml`, package `garmin_to_wanderer/`, console script
  `garmin-to-wanderer`.
- `GarminSource` protocol and `GarminConnectSource` (`garminconnect`, cached
  tokens, FIT/ZIP extraction, GPX fallback).
- `WandererClient`: API-token auth, category/subcategory listing, two-step
  upload + form update, 404/duplicate handling, and file refresh.
- SQLite `StateStore`: mapping, cursor, partial/failed retries.
- `WandererTaxonomy` and a config-overridable Garmin type mapping.
- `SyncRunner`: dry-run, import, skip no-GPS, skip already imported, deleted
  detection, partial metadata retry, and force refresh.
- Typer CLI (`setup garmin`, `setup wanderer`, `sync`, `status`) and JSON report.
- 48 unit tests passing; `ruff check` clean.

**Still pending:** the live one-activity import on the user's Wanderer instance,
because both services are LAN/VPN-only from the agent environment.

### Smoke test checklist (user)

1. `uv venv .venv && uv pip install -e '.[dev]'`
2. `mkdir -p ~/.config/garmin-to-wanderer`
   `cp config.example.yml ~/.config/garmin-to-wanderer/config.yml`
   and edit URL/email/since.
3. `export WANDERER_TOKEN=wanderer_key_...`
4. `garmin-to-wanderer setup garmin`
5. `garmin-to-wanderer setup wanderer --url https://wanderer.erral.freemyip.com`
6. `garmin-to-wanderer status`
7. `garmin-to-wanderer sync --since YYYY-MM-DD --until YYYY-MM-DD --dry-run --report /tmp/g2w-report.json`
8. Run the same command without `--dry-run`, then verify the trail in
   Wanderer. Limit the window to one known activity for the first live test.

## Answer

Implementation complete in the repository: package, CLI, Garmin adapter,
Wanderer client, SQLite state, mapping, sync runner, tests, README, example
config, and CI. All automated checks pass (54 tests, `ruff` clean).

The live one-activity import remains a deployment smoke test because the
Wanderer/FitTrackee instances are LAN/VPN-only from the agent environment. The
user asked to proceed with publishing and the next tickets, so this ticket is
closed on the implementation deliverable; the checklist above is the live
verification step.
