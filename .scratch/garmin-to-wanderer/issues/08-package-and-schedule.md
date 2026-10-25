# Package, schedule, and document

Type: task
Status: resolved
Blocked by: none

## Question

Make the tool runnable unattended on the homelab:

- `pyproject.toml` with pinned dependencies and a console script.
- Dockerfile, or a documented systemd timer/cron entry (user's choice).
- Example config with no secrets; instructions for creating the Wanderer API
  token and the Garmin credentials/key.
- Smoke-test checklist the user can run against
  `https://wanderer.erral.freemyip.com`.
- `README` covering install, setup, sync, backfill, dry-run, and
  troubleshooting.

Definition of done: the user can deploy and schedule it without reading the
source.

## Comments

### 2026-10-25 — README and GitHub Actions landed

- `README.md`: disclaimer (OpenCode + DeepSeek Flash), install, config, setup,
  usage, backfill, scheduling, duplicate handling, limitations, troubleshooting.
- `.github/workflows/ci.yml`: `ruff` + `pytest` on Python 3.12 and 3.13 for
  pushes, pull requests, and manual runs.
- `.github/workflows/sync.yml`: manual, dry-run-first sync using a
  `GARMIN_TOKENSTORE_B64` secret instead of a Garmin password.
- `config.example.yml`: includes retry settings.
- Scheduling is documented as systemd/cron; no Dockerfile is planned unless the
  user asks for one.

Remaining: final review and close.

## Answer

Delivered:

- `README.md` with the OpenCode/DeepSeek Flash disclaimer, install, config,
  setup, usage, backfill, scheduling, duplicate handling, limitations, and
  troubleshooting.
- `.github/workflows/ci.yml` for lint and tests on Python 3.12/3.13.
- `.github/workflows/sync.yml`, a manual dry-run-first sync that restores a
  Garmin token cache from a secret instead of storing a password.
- Documented systemd timer and cron entries; no Dockerfile because the
  systemd/cron option was chosen.
- `config.example.yml` with retry settings.

Definition of done met: install, configure, schedule, and troubleshoot without
reading the source.
