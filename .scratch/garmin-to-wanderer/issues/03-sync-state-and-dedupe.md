# Define incremental state and dedupe

Type: grilling
Status: resolved
Blocked by: none

## Question

Design the sync state that makes repeated runs safe:

- Cursor: last successfully imported Garmin activity by id, start time, or both?
- State store: SQLite table mapping Garmin activity id ↔ Wanderer trail id, plus
  a last-sync marker? Or a JSON file?
- What happens when the state is lost or a run is interrupted mid-import?
- Should the tool rely on Wanderer's geometric duplicate detection, bypass it
  with `ignoreDuplicates=true`, or do both?
- How should an activity deleted in Wanderer be handled on the next run?
- What must the dry-run report show (would import, skipped duplicate, skipped
  no-GPS, failed)?

Leaning: a small SQLite mapping table plus a last-sync marker; always send
`ignoreDuplicates=true` and rely on our own mapping; dry-run never writes.

Context from ticket 02: Wanderer's own duplicate check is geometry-only and
date-blind, so it cannot guard against the same route on another day. Our
mapping plus `ignoreDuplicates=true` is the reliable guard.

## Answer

Resolved with the user: **A / B / A**.

- **State store:** SQLite with an `activities` table (`garmin_id` primary key,
  `wanderer_trail_id`, `started_at`, `status`, `imported_at`, `error`) and a
  `sync_state` key/value table.
- **Cursor:** the `started_at` plus `garmin_id` of the last successfully
  imported activity. Each incremental query starts **48 hours before** that
  cursor to catch late-arriving activities; the `garmin_id` mapping prevents
  re-imports.
- **First run / lost state:** `--since` or `SYNC_SINCE` is **required**. Without
  it the run fails with an explicit message. A lost database never silently
  re-imports history; use `--since` or an explicit `--rebuild-state`.
- **Deleted in Wanderer:** when a mapped trail returns `404`, mark it
  `deleted_in_wanderer` in the report and do **not** re-import. `--since` or
  `--force` can re-import deliberately.
- **Partial failure:** if the upload succeeds but the metadata update fails,
  record the activity as `partial` with the Wanderer trail id and retry only the
  metadata on the next run.
- **Dry-run:** never writes. The report contains `would_import`,
  `skipped_no_gps`, `skipped_already_imported`, `deleted_in_wanderer`,
  `partial`, and `failed`, each with `garmin_id`, name, start time, and reason.
  Output is JSON plus a human-readable summary.
