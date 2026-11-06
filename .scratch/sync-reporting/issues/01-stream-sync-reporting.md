# Stream sync reporting and add output modes

Type: task
Status: resolved
Blocked by: none
GitHub: erral/garmin-to-wanderer#1

## Question

The sync currently prints only after every activity has been processed
(`SyncRunner.run` collects entries and the CLI calls `Report.print_human` once),
and it hides `imported`/`skipped_already_imported` lines unless `--verbose` is
set. Rework reporting so long runs show progress while they happen and so the
user can choose how much output to receive.

Resolved with the user during grilling on 2026-11-06.

## Decisions

- **Default output:** print one line per activity immediately after its outcome
  is decided (`imported`, `skipped_no_gps`, `skipped_already_imported`,
  `skipped_excluded`, `would_import`, `deleted_in_wanderer`, `partial`,
  `failed`), then a minimal summary at the end.
- **Minimal summary:** range header, per-status counts, elapsed time, and the
  report path when `--report PATH` was used.
- **Live line:** local start time (`YYYY-MM-DD HH:MM`), activity name, status;
  `partial`/`failed` lines always include the error message.
- **`--verbose`:** adds Wanderer trail id, Garmin type key, description
  presence, success messages, and pre-action phase lines (download, upload,
  refresh, metadata update). It never hides lines.
- **`-q/--quiet`:** suppresses live lines and the minimal summary. Failures and
  partials still print to stderr. `--report` still writes the file, but its
  confirmation line is suppressed. `--final-report` is the only output that
  still prints in quiet mode.
- **`--final-report`:** prints the expanded end-of-run report (range, counts,
  every entry, trail id/message when verbose, elapsed, report path). It replaces
  the minimal summary. Live lines still stream unless `--quiet` is also set.
  Under `--quiet`, the report-path confirmation is omitted even in the final
  report.
- **`--report PATH`:** keeps the existing JSON schema and works in default,
  quiet, and final-report modes.
- **Contradiction handling:** `--quiet` together with `--verbose` is invalid.
  Print `Error: --quiet and --verbose cannot be used together.` to stderr, exit
  `2`, and do not load config or contact either service.
- **Unchanged:** JSON report shape, exit codes `0/1/2/3`, `--dry-run` semantics.

## Plan

1. Add an `on_entry` callback to `Report` and a `ConsoleReporter` that streams
   formatted entries and verbose phase lines.
2. Add `on_progress`/`on_entry` hooks to `SyncRunner` and emit phase messages
   around download, upload/refresh, and metadata update.
3. Add `--quiet` and `--final-report` to `sync`; validate the contradiction
   before any I/O; measure elapsed time in the CLI.
4. Replace `Report.print_human` with `print_summary` (minimal) and
   `print_human` (expanded final report), both accepting elapsed and report path.
5. Update CLI tests for live output, quiet, final report, verbose, report file,
   and contradiction; update README flags/output docs.
6. Run `pytest` and `ruff check`.

## Definition of done

- A live run prints each activity as it completes, then a minimal summary.
- `--quiet` prints nothing on stdout; failures go to stderr.
- `--quiet --final-report` prints only the expanded final report.
- `--quiet --verbose` exits `2` before config or network access.
- `--report PATH` writes the unchanged JSON schema in every mode.
- Tests and `ruff` pass; README documents the new modes.

## Answer

Implemented on branch `1-stream-sync-reporting` in commit
`Stream sync reporting and add output modes`.

- `Report` now fires an `on_entry` callback when each outcome is recorded;
  `ConsoleReporter` streams the live line and verbose phase lines.
- `SyncRunner` accepts `on_entry`/`on_phase` hooks and emits phases around
  download, refresh, upload, and metadata update.
- `sync` gained `-q/--quiet` and `--final-report`; `--quiet` + `--verbose` exits
  `2` before config or network access.
- `print_summary` is the minimal report; `print_human` is the expanded final
  report and no longer hides imported activities.
- Verbose imported lines show `type=`, `trail=`, `description=yes`, and the
  success message (`uploaded` or `refreshed`).
- Quiet runs suppress the report-path confirmation; the JSON file is still
  written.
- README documents the output modes; 66 tests and `ruff` pass.

Review follow-ups handled: extracted the shared failure-status predicate and
report-path printer, removed the unused `activity` argument from the entry
callback, renamed the progress hook to `on_phase`, and added verbose success
messages.
