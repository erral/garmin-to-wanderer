# Sync window scoping

## Destination

A settled spec: an explicit `--since`/`--until` window scopes the **entire** sync
run (listing plus `FAILED`/`PARTIAL` recovery), a default incremental run
self-heals every unresolved failure, `--since` overrides the cursor, and the
cursor no longer restarts from `sync.since` after an all-failed run.

## Notes

- Domain: the `garmin-to-wanderer` sync pipeline — `cli.py` (window/cursor
  resolution), `sync.py` (recovery + import), `state.py` (SQLite mapping).
- Skills every session should consult: grilling, domain-modeling.
- Read the current behaviour in those files before resolving a ticket.
- Settled at charting (2026-11-09):
  - The destination is a decision/spec, handed off to `/to-spec` + `/implement`;
    this map does not implement the change.
  - An explicit `--since`/`--until` scopes everything, including recovery.
  - `--since` overrides the cursor (exact window; rewinds/backfills allowed).
  - A default run (no explicit window) sweeps all unresolved `FAILED`/`PARTIAL`
    records across the whole state.
  - Window filters use the stored local start date, inclusive of both ends.
  - The cursor advances past fetched activities even when they fail; recovery is
    responsible for retrying them.
- Verified current behaviour (2026-11-09):
  - `--since` is honored for the Garmin listing (`cli.py:325`,
    `garmin_connect.py:55`).
  - `sync.run()` replays every `FAILED`/`PARTIAL` row before the listing,
    ignoring the window (`sync.py:57-64`, `state.py:64` has no date bound).
  - `state.last_imported_start()` ignores `FAILED` (`state.py:140`), so an
    all-failed run falls back to `sync.since` and re-scans history.
- See also the original map at `.scratch/garmin-to-wanderer/map.md` and
  `docs/adr/0001-garmin-source-of-truth.md`.
- **Map complete (2026-11-09):** all four tickets resolved and the frontier is
  empty. Next step is the handoff — `/to-spec` then `/implement` (implementation
  is out of scope for this map).

## Decisions so far

- [Define the sync cursor after failed fetches](issues/01-define-cursor-after-failures.md):
  a `sync_state` watermark (`last_seen_started_at`) advanced by every fetched
  activity and only on default runs; armed from existing rows on upgrade and
  cleared by `--rebuild-state`.
- [Define the failure-recovery sweep membership and filtering](issues/02-define-recovery-sweep-membership.md):
  sweep `failed` + `partial` only (explicit window scoped, default all-state),
  re-check `include`/`exclude` into terminal `skipped_*`, partial→failed order,
  and `--force` escalates partial to a full refresh.
- [Decide how deferred and unresolved failures reach the operator](issues/03-decide-deferred-failure-visibility.md):
  top-level `deferred_failures` in the report plus a non-zero human/stderr line,
  a verbose sweep phase line, watermark + unresolved counts in `status`, and
  exit codes scoped to this run only.
- [Decide the recovery sweep cap and dedicated retry command](issues/04-decide-recovery-cap-and-command.md):
  unlimited by default with optional `sync.recovery_limit` (`0` disables); capped
  selection is oldest-across-both then partial-first; no dedicated retry command;
  remainder counts as `deferred_failures`.

## Not yet specified

<!-- No fog left. Map complete on 2026-11-09; hand off to /to-spec + /implement. -->

## Out of scope

- Implementing the change (hand off to `/to-spec` + `/implement`).
- Garmin listing pagination and 31-day date chunking.
- `deleted_in_wanderer` re-import policy and two-way sync.
- `--quiet` / `--verbose` / `--final-report` output modes.
- A strict "fail if any unresolved failure exists" exit mode (add later if cron
  wants it).
