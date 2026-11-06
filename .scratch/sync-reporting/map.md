# Streaming sync reporting

## Destination

`garmin-to-wanderer sync` reports each activity outcome as it happens instead of
dumping everything at the end, with explicit output modes for unattended runs
(silent), end-only reports, and machine-readable report files.

## Notes

- Source feature: the original map at `.scratch/garmin-to-wanderer/map.md`.
- Decisions came from grilling with the user on 2026-11-06.
- Unchanged contracts: JSON report schema, exit codes `0/1/2/3`, dry-run
  semantics, and the existing `--report PATH` flag.

## Tickets

- [Stream sync reporting and add output modes](issues/01-stream-sync-reporting.md)
  — in progress; default live output, `--quiet`, `--final-report`, `--verbose`
  detail, contradiction validation, tests, and README.

## Out of scope

- Changing the JSON report structure or the sync/dedupe behaviour.
- Concurrent activity processing.
- Human-readable (non-JSON) report files.
