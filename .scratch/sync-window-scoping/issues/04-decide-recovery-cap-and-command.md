# Decide the recovery sweep cap and dedicated retry command

Type: grilling
Status: resolved
Blocked by: none

## Question

Once a default run sweeps every unresolved `failed`/`partial` row, a large
backlog can make one scheduled run hammer Wanderer (and Garmin downloads) for a
long time. Decide the run shape the sweep needs:

- Is there a per-run cap on recovery rows (for example N per run)? What is N, and
  is it configurable?
- When capped, which rows go first (`started_at ASC`?), and how does the run
  report the remainder as deferred?
- Is a dedicated recovery command/flag (`--retry-failed` or a `retry` command)
  still needed, or is the automatic default-run sweep enough?
- How should a capped or partially completed sweep affect the summary and exit
  code?

## Answer

Resolved with the user on 2026-11-09.

- **Cap default and config**: unlimited by default. Add an optional
  `sync.recovery_limit` (env `RECOVERY_LIMIT`), a non-negative integer where
  absent/`null` = unlimited and `0` disables the sweep. Validate it at config
  load like the retry settings.
- **Selection under a cap**: take the oldest `recovery_limit` unresolved rows
  across **both** `partial` and `failed` by `started_at ASC`, then process the
  selected batch partial-first (ticket 02's execution order). The cap applies
  after the explicit-window filter and in `--dry-run` too.
- **No dedicated command/flag**: a default `sync` with no explicit window already
  sweeps the whole state. Document that as the backlog-draining path; do not add
  `--retry-failed` or a `retry` command.
- **Reporting and exit**: unselected rows count in `deferred_failures`; verbose
  prints `Retrying N of M unresolved failures` and, when the limit truncates, a
  `limit reached, R deferred` note. The exit code stays scoped to this run's
  actual failures.
