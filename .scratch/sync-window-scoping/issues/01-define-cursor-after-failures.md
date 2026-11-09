# Define the sync cursor after failed fetches

Type: grilling
Status: resolved
Blocked by: none

## Question

The cursor must stop restarting from `sync.since` when a run fails everything.
Today `state.last_imported_start()` only looks at `imported`/`partial`
(`state.py:140`), so a fully-failed run returns `None` and the next default run
falls back to `config.sync.since`.

Decide the new cursor/watermark:

- Storage: derive it as `MAX(started_at)` over all stored statuses, or add the
  `sync_state` key/value table the original design mentions?
- Which outcomes advance it: `imported`, `partial`, `failed`,
  `deleted_in_wanderer`? What about activities fetched but not stored (skipped
  no-GPS or excluded by config)?
- Does an activity that is fetched but fails to download still move the cursor?
- Migration: how do existing state DBs adopt the new watermark without a
  `--rebuild-state`?
- Interaction with `--rebuild-state`: does it reset the watermark too?

## Answer

Resolved with the user on 2026-11-09.

- **Storage**: add a `sync_state` key/value table to the SQLite state DB (as the
  original design in ticket 03 intended), holding `last_seen_started_at` as an
  ISO datetime. On opening an existing DB, seed it from `MAX(started_at)` over
  all `activities` rows when the key is absent, so upgrades need no
  `--rebuild-state`.
- **What advances it**: every activity returned by the Garmin listing, whatever
  its outcome — `imported`, `partial`, `failed`, `deleted_in_wanderer`, skipped
  no-GPS, skipped excluded. The watermark tracks listing progress, not import
  success.
- **Value and timing**: the maximum `started_at` among the fetched activities in
  the chunk; an empty chunk does not advance it. Persist after each successfully
  completed 31-day chunk, so a crash re-scans only the unfinished chunk. The
  existing 2-day overlap still catches late-arriving activities.
- **Explicit windows do not move it**: only default (cursor-driven) runs advance
  the watermark. `--since`/`--until` runs are ad-hoc windows and never advance
  it, so a recent backfill cannot jump the cursor over an unsynced gap. This
  retires the "explicit backfill gap" fog item.
- **`--rebuild-state` resets it**: `StateStore.reset()` clears both `activities`
  and `sync_state`, so the next run behaves like a first run.
- **`--dry-run` never writes** the watermark.
- The default start becomes `last_seen_started_at.date() - 2 days`;
  `last_imported_start()` is retired (or kept only to seed an old DB).
