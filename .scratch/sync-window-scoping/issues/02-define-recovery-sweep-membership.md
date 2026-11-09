# Define the failure-recovery sweep membership and filtering

Type: grilling
Status: resolved
Blocked by: none

## Question

Define exactly what the recovery sweep replays and how it is scoped, given:

- An explicit `--since`/`--until` confines the whole run, sweep included.
- A default run (no explicit window) sweeps every unresolved failure.
- Window membership uses the stored local start date, inclusive.

Decide:

- Statuses retried: `failed` + `partial` only, or anything else? Confirm
  `deleted_in_wanderer` stays excluded (existing decision).
- Should the sweep re-apply `include`/`exclude` and the no-GPS filter to rows
  whose stored type/GPS no longer qualifies, and what status do those end as?
- Ordering and dedupe against the date-range listing: sweep first, then skip ids
  already processed?
- Interaction with `--force`: does it change sweep behaviour?
- Does the sweep run in `--dry-run`, and what does the report call a
  would-retry row?

## Answer

Resolved with the user on 2026-11-09.

- **Membership**: the sweep retries `failed` and `partial` only. `imported` and
  `deleted_in_wanderer` stay out; a deleted trail is re-imported only through the
  listing with `--force`.
- **Filter re-check**: the sweep re-applies `include`/`exclude` to stored rows. A
  now-excluded row transitions to a persisted terminal `skipped_excluded`; a
  stray `has_gps=false` row transitions to `skipped_no_gps`. Both leave the sweep
  and no longer count as failures. Re-including a type later requires
  `--rebuild-state` (or a manual status reset).
- **Scope**: an explicit `--since`/`--until` filters both recovery loops by the
  stored local start date, inclusive. A default run sweeps the whole state.
- **Order and dedupe**: `partial` first, then `failed`, each ordered by
  `started_at ASC`; the listing then skips any id already processed.
- **`--force`**: escalates a `partial` row to a full refresh (re-download,
  `update_trail_file`, then metadata) instead of a metadata-only retry. `failed`
  is unchanged. `--force` does not pull `deleted_in_wanderer` into the sweep.
- **Dry run**: the sweep runs, writes nothing, downloads nothing, and does not
  advance the watermark. Report statuses are unchanged: a would-retry `failed`
  reports `would_import`; a would-retry `partial` reports `partial` with "would
  retry metadata", or `would_import` under `--force`.
