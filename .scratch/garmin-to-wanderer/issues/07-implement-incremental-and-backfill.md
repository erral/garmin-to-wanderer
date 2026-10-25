# Implement incremental sync, backfill, and reporting

Type: task
Status: resolved
Blocked by: 06

## Question

Finish the sync behaviour:

- Default incremental run from the last imported activity.
- Explicit date-range backfill, chunked when Garmin paginates.
- Idempotent re-runs and interrupted-run recovery.
- Retries/backoff for transient Garmin and Wanderer failures.
- Dry-run report: would import / skipped (no GPS, duplicate) / failed, each with
  a reason.
- Logging suitable for cron.

Definition of done: two consecutive runs import nothing on the second run, and a
forced date range re-imports only the missing activities.

## Answer

Implemented and verified with mocks:

- **Incremental cursor:** the CLI starts 48 hours before the last imported
  activity; a CLI test asserts the exact cursor date passed to the Garmin source.
- **Backfill:** explicit `--since`/`--until`; the Garmin source splits long ranges
  into 31-day chunks and de-duplicates IDs across chunks.
- **Idempotent re-runs:** the SQLite mapping skips imported activities, retries
  metadata only for `partial` records, and retries the full import for `failed`
  records.
- **Retries/backoff:** Wanderer GET/POST retry `429`/`5xx` and network errors;
  the upload PUT is not retried to avoid duplicate trails. Garmin listing and
  downloads retry transient failures and stop immediately on auth errors.
- **Reporting:** dry-run and live runs share one report; JSON output includes
  per-activity status and reason.
- 54 tests pass; `ruff check` clean.

Definition of done covered: a second run skips everything via the state mapping,
and a forced window refreshes only imported/missing activities.
