# Sync window scoping and failure recovery

Status: ready-for-agent

## Problem Statement

Running `garmin-to-wanderer sync --since <recent>` does not behave like a run
limited to that window. The Garmin listing respects the dates, but before it the
sync replays every previously stored `failed` and `partial` activity from the
local state, regardless of `--since`/`--until`. With an interrupted backfill on
record, a "recent" run appears to start from scratch. Separately, the incremental
cursor only considers imported/partial activities, so a run where everything
failed falls back to `sync.since` and re-scans the whole history. The operator
has no way to see how much unresolved work is sitting outside the current window.

## Solution

Make the requested window mean exactly that slice: an explicit `--since`/
`--until` scopes the entire run, including failure recovery. Default
(cursor-driven) runs become self-healing: they retry every unresolved failure
across the whole state. The cursor becomes a persisted watermark that advances
past every fetched activity, even ones that fail, so a bad run never restarts
from `sync.since`. Unresolved work outside the attempted set is reported as
deferred (report, human output, and `status`) without changing the run's exit
code. An optional recovery limit bounds how much a single run retries.

## User Stories

1. As a homelab operator running an explicit recent window, I want old failures outside that window left untouched, so a narrow run stays narrow.
2. As a homelab operator, I want failures inside the requested window retried, so backfills recover cleanly.
3. As a cron-driven sync, I want a default run to retry every unresolved failure, so the system self-heals without a manual command.
4. As an operator whose run failed entirely, I want the next default run to continue from where Garmin was last scanned, so it does not restart from `sync.since`.
5. As an operator, I want the cursor to account for activities that failed to import, so retries are not silently stranded behind the cursor.
6. As an operator, I want the cursor to account for skipped no-GPS and excluded activities, so repeated runs do not rescan the same old ranges.
7. As an operator, I want an explicit backfill never to jump the cursor over an unsynced gap, so future incremental runs do not skip activities.
8. As an operator, I want `--rebuild-state` to reset the cursor along with the mapping, so the next run behaves like a first run.
9. As a cautious operator, I want a dry run never to move the cursor or change state, so I can inspect safely.
10. As an operator, I want a configurable recovery limit, so a huge backlog does not monopolize a scheduled run.
11. As an operator, I want a recovery limit of `0` to disable the recovery sweep, so I can turn it off deliberately.
12. As an operator, I want a limited sweep to pick the oldest unresolved work first, so no status or activity starves.
13. As an operator, I want partial retries prioritized within a selected batch, so cheap metadata fixes land first.
14. As an operator, I want `--force` to fully refresh a partial trail, so I can repair deeper problems than metadata.
15. As an operator, I want `--force` not to pull deleted trails into the recovery sweep, so deletion stays a deliberate action.
16. As an operator, I want a failure whose type is now excluded to leave the failure count, so the failure signal stays trustworthy.
17. As an operator, I want a stray no-GPS failure to become a skip, so it stops being retried.
18. As an operator, I want a deferred-failure count in the JSON report, so monitoring can alert on stuck work.
19. As an operator, I want the human summary to print a deferred-failure line only when there are some, so clean runs look unchanged.
20. As a cron operator using `--quiet`, I want one stderr line when work is deferred, so logs capture it without progress noise.
21. As a verbose operator, I want a phase line before the recovery sweep, so I understand why old activities appear before the listing.
22. As a verbose operator, I want to see attempted-versus-total when a limit is active, so I know more work remains.
23. As an operator, I want `status` to show the last-seen watermark, so I can see the cursor offline.
24. As an operator, I want `status` to show unresolved failed and partial counts, so I know what is stuck.
25. As a cron operator, I want the exit code to reflect only this run's failures, so a clean window does not alarm because of old deferred state.
26. As a maintainer, I want existing state databases to upgrade without `--rebuild-state`, so upgrades remain safe.
27. As an operator, I want the window to use activity local start dates, so activities near midnight are not mis-scoped.
28. As an operator, I want a default run with no cursor and no `sync.since` to keep failing with a clear message, so first-run setup stays explicit.
29. As an operator, I want the recovery sweep deduplicated against the listing, so nothing is processed twice in one run.
30. As a maintainer, I want the new behaviour verified through the CLI, so the whole pipeline is covered rather than private helpers.

## Implementation Decisions

**Window and cursor resolution**

- An explicit `--since`/`--until` defines the entire run, including the recovery
  sweep. It overrides the incremental cursor (existing behaviour) and still
  allows rewinds and backfills.
- A default run (neither flag given) uses the persisted watermark: start =
  watermark local date minus two days (the existing 48-hour overlap), end =
  today.
- With no watermark and no explicit window, fall back to `sync.since`; if that is
  also unset, keep the existing explicit error requiring `--since` or
  `sync.since`.
- Window membership compares the activity's stored local start date, inclusive of
  both ends.

**Cursor watermark**

- State gains a `sync_state` key/value table holding `last_seen_started_at` as an
  ISO datetime.
- On opening an existing database, seed the watermark from the maximum
  `started_at` across all activity rows when the key is absent. No
  `--rebuild-state` is required to upgrade.
- The watermark advances from the maximum start time among fetched activities,
  whatever their outcome: imported, partial, failed, deleted-in-Wanderer,
  skipped no-GPS, or skipped excluded. It tracks listing progress, not import
  success.
- Only default (cursor-driven) runs advance the watermark. Explicit
  `--since`/`--until` runs never do, which removes the backfill-gap risk by
  construction.
- Persist the watermark incrementally as the listing is consumed, at least at
  each successfully completed 31-day chunk boundary (per-activity persistence is
  acceptable and safer). An empty chunk does not advance it. A crashed listing
  therefore re-scans only from the last persisted point.
- `--dry-run` never writes the watermark.
- `--rebuild-state` resets both the activity mapping and the watermark, so the
  next run behaves like a first run.
- Retire the old "last imported start" cursor in favour of the watermark; reuse
  the old calculation only as the upgrade seed.

**Failure-recovery sweep**

- The sweep retries `failed` and `partial` rows only. Imported and
  deleted-in-Wanderer rows are excluded; a deleted trail is still re-imported
  only through the listing with `--force`.
- An explicit window filters both recovery cohorts by the stored local start
  date, inclusive. A default run sweeps the whole state.
- Re-apply the configured include/exclude rules to stored rows. A row whose type
  is now excluded transitions to a persisted terminal `skipped_excluded`; a
  stray no-GPS row transitions to `skipped_no_gps`. Both leave future sweeps and
  stop counting as failures. Re-including a type later requires
  `--rebuild-state` (or a manual status reset).
- Without a limit, process all partial rows first, then all failed rows, each in
  ascending start-time order.
- With a limit, select the oldest N unresolved rows across both statuses by
  ascending start time first, then process the selected batch partial-first.
- Maintain a processed-id set so an activity retried by the sweep is not
  re-processed when it also appears in the listing.
- `--force` escalates a partial row from a metadata-only retry to a full refresh
  (download, replace trail file, then metadata). Failed rows are unchanged (they
  are already a full import). `--force` does not add deleted-in-Wanderer rows to
  the sweep.
- The sweep runs in `--dry-run` without writing state, downloading files, or
  advancing the watermark. Dry-run reporting reuses existing statuses: a
  would-retry failed row reports `would_import`; a would-retry partial row
  reports `partial` with "would retry metadata", or `would_import` under
  `--force`.

**Recovery limit**

- Add `sync.recovery_limit`, also overridable by the `RECOVERY_LIMIT` environment
  variable. It is a non-negative integer; absent or null means unlimited, and `0`
  disables the sweep entirely.
- Validate it at configuration load, like the existing retry settings.

**Visibility and exit codes**

- The report gains a top-level `deferred_failures` integer: unresolved
  failed/partial rows that this run did not attempt because they fell outside the
  window or beyond the recovery limit.
- Print a human summary line `deferred failures: N` only when N is greater than
  zero.
- In `--quiet`, emit one stderr line when N is greater than zero, and stay silent
  when zero.
- Before the sweep, emit a verbose phase line `Retrying N partial and M failed
  activities`. When a limit is active, show attempted versus total and emit a
  "limit reached, R deferred" note.
- `status` shows `Last seen: <datetime>` from the watermark (or none) and an
  explicit `Unresolved failures: failed N, partial M` line, alongside the
  existing stored-status counts.
- Exit codes keep their meaning: exit `1` only when this run's entries include
  partial/failed outcomes. Deferred old failures alone never fail a run.

**Modules affected**

- CLI: window resolution, default-start resolution, `status` output, deferred
  accounting.
- Sync runner: recovery selection and ordering, filter re-checks, force
  escalation, watermark updates, processed-id dedupe.
- State store: `sync_state` schema and migration seeding, watermark read/write,
  windowed and limited unresolved queries, reset semantics.
- Configuration: `sync.recovery_limit` and its environment override.
- Reporting: `deferred_failures`, the human/stderr lines, and the verbose phase
  text.

## Testing Decisions

Good tests assert externally observable behaviour through a public seam: which
Garmin activities were listed or downloaded, which Wanderer calls were made, the
report JSON, stdout/stderr, exit codes, and persisted state rows. They must not
assert private helper internals or exact SQL.

Three existing seams are used; no new test doubles are added below the CLI.

1. **CLI end-to-end (primary)** — `CliRunner` against `sync`/`status`, a real
   state store in a temporary directory, and the existing fake Garmin source and
   fake Wanderer client patched at the CLI module boundary. Prior art:
   `tests/test_cli.py`.
2. **State store unit** — `tests/test_state.py` for the `sync_state` schema,
   watermark read/write, upgrade seeding, and `reset()` clearing both tables.
3. **Configuration unit** — `tests/test_config.py` for `sync.recovery_limit`
   parsing, the environment override, `0` versus absent, and validation.

Coverage expected:

- An explicit window retries failures inside it and leaves failures outside it
  untouched; a default run retries all unresolved failures.
- After a run where everything fails, the next default run calls Garmin with the
  watermark minus two days, not `sync.since`.
- Explicit-window runs and dry runs do not move the watermark.
- An existing database without `sync_state` is seeded from the maximum stored
  start time.
- `--rebuild-state` clears the watermark.
- Include/exclude re-checks transition rows to terminal skip statuses.
- `--force` escalates a partial row to a full refresh but does not sweep deleted
  rows.
- A recovery limit selects the oldest N across both statuses and reports the
  remainder as deferred.
- `deferred_failures` appears in JSON, the human line appears only when non-zero,
  quiet writes one stderr line, and verbose shows the sweep phases.
- `status` prints the watermark and unresolved counts.
- A clean explicit-window run with deferred old failures exits `0`; a run that
  produces failures exits `1`.
- Window membership uses local start dates at the boundaries.

## Out of Scope

- Actually implementing the change (this spec is the handoff for `/implement`).
- Garmin listing pagination and 31-day chunk sizing.
- The deleted-in-Wanderer re-import policy and any two-way sync.
- Changes to the `--quiet` / `--verbose` / `--final-report` modes beyond the
  lines described above.
- A dedicated `--retry-failed` flag or `retry` command; a default `sync` is the
  backlog-draining path.
- A strict "fail if any unresolved failure exists" exit mode.
- Capping the Garmin listing or the number of new activities imported per run.
- Wanderer category/subcategory mapping changes.

## Further Notes

- Aligns with `docs/adr/0001-garmin-source-of-truth.md`: Garmin is the source of
  truth, the local SQLite mapping is the dedupe authority, and the cursor keeps a
  48-hour overlap.
- Decisions were reached through the wayfinder map at
  `.scratch/sync-window-scoping/map.md`; the four decision tickets hold the
  detailed rationale.
- There is no `GLOSSARY.md` in this repo; terms follow the existing code and
  README (activity, trail, window, cursor/watermark, recovery sweep, partial,
  failed, state store).
- Consider adding a short ADR for the cursor/recovery semantics once implemented:
  the watermark and the "explicit windows never move the cursor" rule are hard to
  reverse and surprising without context.
- Existing suites pass at 67 tests; the implementation should extend them without
  changing the external CLI contract beyond the additions above.
