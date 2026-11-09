# Decide how deferred and unresolved failures reach the operator

Type: grilling
Status: resolved
Blocked by: 02 (Define the failure-recovery sweep membership and filtering)

## Question

With explicit windows confined, failures outside the window are deferred, and a
default run may carry a large unresolved backlog. Decide how the operator sees
this so failures do not rot silently:

- A summary/report field for "unresolved failures deferred outside the window"?
- A phase/verbose line when the sweep retries N rows?
- The `status` command: show the new watermark and unresolved-failure counts?
- Exit-code impact: currently `has_failures()` makes a run exit `1`; should a
  successful listing with deferred old failures still exit `0`?

## Answer

Resolved with the user on 2026-11-09.

- **JSON + human report**: add a top-level integer `deferred_failures` to the
  report — unresolved `failed`/`partial` rows outside this run's window. Print
  `  deferred failures: N` in the human summary only when `N > 0`, so clean runs
  look unchanged.
- **Quiet mode**: when `deferred_failures > 0`, emit one line to stderr; stay
  silent when zero.
- **Verbose**: before the recovery sweep, print the phase line
  `Retrying N partial and M failed activities` through `on_phase` (verbose only).
- **`status`**: show `Last seen: <datetime>` from `sync_state` and an explicit
  `Unresolved failures: failed N, partial M` line, in addition to the stored
  status counts.
- **Exit code**: unchanged semantics — exit `1` only for failures produced by
  this run (`has_failures()` over this run's entries). Deferred old failures on
  their own leave a successful run at exit `0`; the `deferred_failures` count is
  the signal. A strict "fail if anything is unresolved" mode is out of scope for
  this effort.
