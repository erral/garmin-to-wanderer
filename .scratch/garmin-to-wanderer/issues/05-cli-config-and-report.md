# Define CLI, config, and report

Type: grilling
Status: resolved
Blocked by: none

## Question

Define the user-facing contract of `garmin-to-wanderer`:

- Commands and flags: `setup garmin`, `setup wanderer`, `sync`,
  `--since YYYY-MM-DD`, `--until YYYY-MM-DD`, `--dry-run`, `--report PATH`,
  `--verbose`.
- Config: `config.yml`, environment variables, or both? Where do secrets live
  (file permissions, env, Docker/systemd secret)?
- Output: human-readable summary, JSON/CSV report, or both? What exactly does a
  dry-run report contain?
- Exit codes for cron (success, partial failure, auth failure).
- Logging destination and verbosity.

Leaning: mirror `garmin-to-fittrackee`'s config and CLI conventions. `sync`
prints a summary and optionally writes a JSON report; dry-run prints the same
report without writing to Wanderer.

Context from ticket 02: import is two HTTP calls (upload, then a form update),
and upload accepts only a `name` fallback. The CLI should hide that two-step
detail from the user and report one outcome per activity.

Context from ticket 03: the CLI must expose `SYNC_SINCE`/`--since`,
`--rebuild-state`, and `--force`, and must document the first-run requirement.

Context from ticket 04: the mapping is config-overridable by Garmin `typeKey`,
with category names resolved to IDs at runtime and `Other` as the fallback.

## Answer

Resolved with the user: **A / A / A**.

- **Commands:** `setup garmin`, `setup wanderer`, `sync`, `status`.
- **Flags:** `--since YYYY-MM-DD`, `--until YYYY-MM-DD`, `--dry-run`,
  `--report PATH`, `--force`, `--rebuild-state`, `--verbose`, `--config PATH`.
- **Config:** YAML at `~/.config/garmin-to-wanderer/config.yml`, overridable
  with `CONFIG_PATH` or `--config`. Non-secret settings live in YAML. Secrets
  come from the environment: `WANDERER_TOKEN`, and `GARMIN_PASSWORD` for the
  initial `setup garmin` only. State lives in
  `~/.local/share/garmin-to-wanderer/` (`state.db`, `garmintoken/`). Create the
  config directory/file with mode `0700`/`0600`. Never commit secrets.
- **Output:** a human-readable summary on stdout; `--report PATH` writes a JSON
  report with one entry per activity plus totals. `--dry-run` produces the same
  report but performs no writes.
- **Exit codes:** `0` all succeeded, `1` at least one partial/failed activity,
  `2` configuration or authentication error, `3` unexpected error. This lets
  cron alert on partial failures.
- **Logging:** human summary on stdout, diagnostics on stderr; `--verbose`
  raises the log level. No log file by default; cron can redirect.
- **Two-step import is hidden:** the CLI reports one outcome per activity even
  though the upload and metadata update are separate HTTP calls.
