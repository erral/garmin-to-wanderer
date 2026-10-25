# garmin-to-wanderer

Import Garmin Connect activities into [Wanderer](https://wanderer.to), treating
Garmin Connect as the source of truth.

This is a small, single-user CLI for a homelab: it polls Garmin Connect, filters
to GPS activities, uploads the original FIT file (or a GPX fallback), and fills
in Wanderer metadata.

## Background

The creator needed a way to automatically import Garmin Connect activities into
Wanderer. With the previous Strava-based import no longer available, there was
no practical alternative but to write this tool.

## How it works

```text
Garmin Connect
      |
      |  garminconnect (cached session)
      v
garmin-to-wanderer
      |  filter GPS activities
      |  download FIT / GPX
      |  PUT /api/v1/trail/upload
      |  POST /api/v1/trail/form/{id}
      v
Wanderer
```

- The Garmin client sits behind a `GarminSource` adapter. Today it uses
  `garminconnect`; an official Garmin Personal API adapter can be added later
  without changing the sync pipeline.
- Wanderer accepts FIT but converts it to GPX server-side and discards the
  original FIT. The tool therefore sends FIT for convenience, not for archival.
- Wanderer stores only a date, not a start time-of-day. The date comes from the
  Garmin activity, and the timestamp remains inside the GPX.
- Metadata is applied in a second call because the upload endpoint only accepts
  a name fallback.
- A local SQLite database maps Garmin activity IDs to Wanderer trail IDs and
  stores the sync cursor.

## Features

- Incremental sync from the last imported activity by default.
- Explicit date-range backfills with `--since` / `--until`.
- Dry-run report with per-activity outcomes.
- JSON report for cron jobs and troubleshooting.
- Skips activities without GPS and reports them.
- Configurable Garmin activity type → Wanderer category mapping.
- Detects trails deleted in Wanderer without silently re-importing them.
- Retries transient GET/form-update failures with exponential backoff.
- 56 unit tests with mocked Garmin and Wanderer responses.

## Requirements

- Python 3.12 or newer.
- A Garmin Connect account.
- A running Wanderer instance and an API token (`wanderer_key_...`).
- Network access from the machine running the tool to both Garmin Connect and
  Wanderer.

Targeted at Wanderer v0.21.2 and `garminconnect` 0.3.20.

## Installation

From PyPI:

```bash
pip install garmin-to-wanderer
```

Or install it as an isolated tool:

```bash
uv tool install garmin-to-wanderer
```

From source, for development:

```bash
git clone https://github.com/erral/garmin-to-wanderer.git
cd garmin-to-wanderer
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

The console script is `garmin-to-wanderer` (or
`.venv/bin/garmin-to-wanderer`).

## Configuration

Create the config directory:

```bash
mkdir -p ~/.config/garmin-to-wanderer
chmod 700 ~/.config/garmin-to-wanderer
```

If you have a source checkout, start from `config.example.yml`:

```bash
cp config.example.yml ~/.config/garmin-to-wanderer/config.yml
chmod 600 ~/.config/garmin-to-wanderer/config.yml
```

Otherwise create the file manually with this minimal `config.yml`:

```yaml
wanderer:
  url: https://wanderer.example.com

garmin:
  email: you@example.com

state_dir: ~/.local/share/garmin-to-wanderer

sync:
  since: 2024-01-01
  default_category: Other
  category_map:
    road_biking: Biking/Road
    mountain_biking: Biking/MTB
    gravel_cycling: Biking/Gravel
    hiking: Hiking
    trail_running: Running/Trail
```

`sync.since` is required on the first run. Later runs use the local cursor.

### Secrets

Prefer environment variables over storing secrets in the YAML:

| Variable | Purpose |
|---|---|
| `WANDERER_TOKEN` | Wanderer API token (`wanderer_key_...`). Required for sync. |
| `WANDERER_URL` | Overrides `wanderer.url`. |
| `GARMIN_EMAIL` | Overrides `garmin.email` for `setup garmin`. |
| `GARMIN_PASSWORD` | Garmin password for `setup garmin` only; never stored. |
| `WANDERER_TIMEOUT` | HTTP timeout in seconds (default `30`). |
| `RETRY_ATTEMPTS` | Attempts for retryable requests (default `3`). |
| `RETRY_BACKOFF` | Base backoff seconds (default `1.0`, exponential). |
| `CONFIG_PATH` | Overrides the config file path. |
| `STATE_DIR` | Overrides `state_dir`. |
| `SYNC_SINCE` | Overrides `sync.since`. |

The tool does not store your Garmin password. It caches Garmin session tokens
under `state_dir/garmintoken/`.

## Setup

### 1. Log in to Garmin

```bash
garmin-to-wanderer setup garmin
```

This prompts for your Garmin email and password, handles MFA if enabled, and
caches the tokens. If Garmin later asks for MFA again, run the command again.

### 2. Validate the Wanderer connection

Create an API token in Wanderer under **Settings → Authentication** (or the API
token settings for your account), then:

```bash
export WANDERER_TOKEN=wanderer_key_...
garmin-to-wanderer setup wanderer --url https://wanderer.example.com
```

Use `--store-token` if you want the token written to `config.yml` (the file is
created with mode `0600`) instead of keeping it in the environment.

### 3. Check the state

```bash
garmin-to-wanderer status
```

This prints the config path, Wanderer URL, token presence, Garmin token store,
state database, cursor, and stored activity counts. It does not contact either
service.

The installed version is available with:

```bash
garmin-to-wanderer --version
```

## Usage

### Dry run

Always start with a dry run:

```bash
garmin-to-wanderer sync \
  --since 2024-01-01 \
  --until 2024-01-31 \
  --dry-run \
  --report /tmp/garmin-to-wanderer.json
```

The report lists what would be imported, skipped (no GPS, excluded type,
already imported), deleted in Wanderer, partial, or failed.

### Import

```bash
garmin-to-wanderer sync --since 2024-01-01 --until 2024-01-31
```

Without `--since`, the tool starts 48 hours before the last imported activity.
On the first run it falls back to `sync.since`; if neither exists, it stops with
an error.

### Backfill

Use an explicit window:

```bash
garmin-to-wanderer sync --since 2022-01-01 --until 2023-12-31
```

The range is split into 31-day chunks before querying Garmin, so long backfills
do not rely on one huge response.

### Re-import or refresh

```bash
garmin-to-wanderer sync --since 2024-01-01 --force
```

`--force` refreshes an existing trail's GPX and metadata instead of creating a
duplicate. If the trail was deleted in Wanderer, it uploads a new one.

### Rebuild local state

```bash
garmin-to-wanderer sync --rebuild-state --since 2024-01-01
```

This clears the local mapping before syncing. It is explicit because it can
re-import activities that are already in Wanderer.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Everything succeeded (or was skipped as expected). |
| `1` | At least one activity is `partial` or `failed`. |
| `2` | Configuration or authentication error. |
| `3` | Unexpected error (network, server, bug). |

This lets cron or systemd alert on partial failures.

## Scheduling on the homelab

Example cron entry (every 30 minutes):

```cron
*/30 * * * * cd /opt/garmin-to-wanderer && WANDERER_TOKEN=... .venv/bin/garmin-to-wanderer sync >> /var/log/garmin-to-wanderer.log 2>&1
```

Example systemd timer:

```ini
# /etc/systemd/system/garmin-to-wanderer.service
[Unit]
Description=Sync Garmin Connect to Wanderer

[Service]
Type=oneshot
WorkingDirectory=/opt/garmin-to-wanderer
Environment=WANDERER_TOKEN=wanderer_key_...
ExecStart=/opt/garmin-to-wanderer/.venv/bin/garmin-to-wanderer sync
```

```ini
# /etc/systemd/system/garmin-to-wanderer.timer
[Unit]
Description=Run garmin-to-wanderer every 30 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-to-wanderer.timer
```

## Duplicate handling

Wanderer's own duplicate check compares the start point (100 m), distance
(±50 m), and elevation (±50 m). It ignores the date, so the same route on another
day can be falsely rejected. This tool therefore:

- keeps its own SQLite mapping keyed by Garmin activity ID,
- always sends `ignoreDuplicates=true`, and
- relies on the mapping, not Wanderer's geometry check.

If the local state is lost, the tool does not silently import everything again.
Pass `--since` or `--rebuild-state` explicitly.

## Limitations

- No two-way sync. Wanderer changes do not flow back to Garmin.
- Wanderer converts FIT to GPX and discards the original FIT. Heart rate is
  dropped by that conversion, and Wanderer has no heart-rate field anyway.
- Activities without GPS are skipped. `--include-no-gps` is not implemented.
- There is no Wanderer plugin. The plugin protocol is GPX-only, capped at 5,000
  items per run, and has no reliable cross-run cursor.
- No reconciliation with trails already imported into Wanderer from Strava.
- Single user only.
- Garmin access uses the unofficial `garminconnect` library, so it is exposed to
  Garmin SSO/TLS changes. The adapter is the escape hatch to the official Garmin
  Personal API.

## GitHub Actions

Four workflows are included:

- `.github/workflows/ci.yml` runs `ruff` and `pytest` on push and pull requests,
  and validates the built distributions.
- `.github/workflows/sync.yml` is a **manual** (`workflow_dispatch`) sync. It is
  dry-run by default and runs from the GitHub-hosted runner.
- `.github/workflows/publish.yml` publishes a GitHub release to PyPI through
  Trusted Publishing. See [Releasing to PyPI](#releasing-to-pypi).
- `.github/workflows/publish-testpypi.yml` is a **manual** pre-release upload to
  TestPyPI.

The manual sync avoids storing a Garmin password. Instead it restores a Garmin
token cache from a repository secret. Create the cache locally and encode it:

```bash
garmin-to-wanderer setup garmin
cd ~/.local/share/garmin-to-wanderer
tar -czf - garmintoken | base64 -w0
```

Add these repository secrets:

| Secret | Value |
|---|---|
| `WANDERER_URL` | `https://wanderer.example.com` |
| `WANDERER_TOKEN` | `wanderer_key_...` |
| `GARMIN_TOKENSTORE_B64` | the base64 output above |

Then run **Actions → Sync (manual) → Run workflow**. Provide `since`; leave
`until` empty for today, and keep `dry_run` on for the first run.

Caveats:

- GitHub-hosted runners must be able to reach your Wanderer URL. If it is
  LAN/VPN-only, use the homelab scheduler instead.
- The Garmin token cache eventually expires or requires MFA again. Re-run
  `setup garmin` locally, re-encode the directory, and update the secret.
- The manual workflow starts with a fresh local state database each run, so it
  always needs an explicit `since`. It is useful for smoke tests and backfills,
  not as a replacement for the homelab cursor.
- A scheduled sync is deliberately not included: cached Garmin tokens, MFA, and
  LAN-only Wanderer instances make a cron job on a public runner fragile.

## Releasing to PyPI

This project uses **PyPI Trusted Publishing (OIDC)**, so no PyPI API token or
password is stored in GitHub. The publisher is
`.github/workflows/publish.yml`, the GitHub environment is `pypi`, and the
version is derived from **git tags** by `setuptools-scm`. There is no version
string to bump by hand.

Publishing is tied to a **published GitHub release**, which is created from a
tag. A raw tag push does not publish the package. This is deliberate: the
release is a manual checkpoint, carries release notes, and gives one obvious
workflow run to re-run if the upload fails.

Use tags in the form `vMAJOR.MINOR.PATCH` (for example `v0.1.0`). Builds
between tags get a development version such as `0.1.1.dev3`, which is what you
would publish to TestPyPI.

### One-time PyPI setup

1. Create a GitHub environment named `pypi` in **Settings → Environments**. Add
   required reviewers if you want a manual approval gate.
2. On PyPI, create a **pending trusted publisher** at
   <https://pypi.org/manage/account/publishing/> with:
   - **PyPI project name:** `garmin-to-wanderer`
   - **Owner:** your GitHub user or organisation (for example `erral`)
   - **Repository name:** `garmin-to-wanderer`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`
3. If the project name is already taken, change `project.name` in
   `pyproject.toml` and use the same name in the pending publisher.

The pending publisher becomes a normal publisher after the first successful
release. No `PYPI_API_TOKEN` secret is needed.

### Release checklist

1. Make sure the release commit is on `main` and the working tree is clean.
2. Create an annotated tag and push it:

   ```bash
   git tag -a v0.1.0 -m "v0.1.0"
   git push origin v0.1.0
   ```

   `setuptools-scm` derives the version `0.1.0` from this tag.

3. Create the GitHub release from that tag:

   ```bash
   gh release create v0.1.0 --generate-notes
   ```

   Publishing the release triggers the `Publish` workflow.

4. The workflow runs lint and tests, builds the sdist and wheel, runs
   `twine check`, then uploads through OIDC. PEP 740 attestations are generated
   by the PyPA publish action by default.
5. Verify the release:

   ```bash
   pip install garmin-to-wanderer==0.1.0
   garmin-to-wanderer --version
   ```

To retry a failed publish, re-run the failed `Publish` workflow from the
Actions tab. PyPI rejects an already-published version, so create a new tag
(for example `v0.1.1`) before retrying.

### Local packaging check

```bash
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m build
.venv/bin/twine check dist/*
```

### TestPyPI (optional)

TestPyPI is a separate index for pre-release checks. The manual
`.github/workflows/publish-testpypi.yml` workflow uploads the build there.

One-time setup:

1. Create a GitHub environment named `testpypi`.
2. Add a pending publisher at
   <https://test.pypi.org/manage/account/publishing/> with the same owner and
   repository, workflow name `publish-testpypi.yml`, and environment name
   `testpypi`.

Then run **Actions → Publish (TestPyPI) → Run workflow**. The version comes from
`setuptools-scm`, so a run between tags gets a development version such as
`0.1.1.dev3`; TestPyPI still rejects duplicate versions, so use a fresh commit
(or a new tag) for each test upload. The PyPI workflow itself only publishes
from a GitHub release.

## Development

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

Project layout:

```text
garmin_to_wanderer/
  cli.py              Typer commands
  config.py           YAML + environment configuration
  mapping.py          Garmin type -> Wanderer category
  models.py           Activity/file value objects
  reporting.py        Human and JSON reports
  state.py            SQLite cursor and activity mapping
  sync.py             Sync orchestration
  wanderer.py         Wanderer HTTP client
  sources/            Garmin adapters
tests/                Unit tests with fakes and HTTP mocks
```

## Troubleshooting

- **`Garmin token store not found`** — run `garmin-to-wanderer setup garmin`.
- **Garmin asks for MFA during cron** — run `setup garmin` interactively again;
  the cached session expired.
- **`Wanderer rejected the API token`** — regenerate the token in Wanderer and
  update `WANDERER_TOKEN`. Tokens have full account access.
- **No activities in the dry run** — check the date window, `sync.since`, and
  whether the activities have GPS. No-GPS activities are reported as
  `skipped_no_gps`.
- **A route was rejected as a duplicate** — this tool always sends
  `ignoreDuplicates=true`; if you see a duplicate, check your local state and the
  Garmin activity ID.
- **Partial records** — the next run retries metadata only. Use `--force` if you
  want to refresh the GPX too.

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgements

- [Wanderer](https://github.com/open-wanderer/wanderer) for the trail database
  and API.
- [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) for the
  unofficial Garmin client.

## AI Usage

This project was written with [OpenCode](https://opencode.ai),
[DeepSeek Flash](https://www.deepseek.com/), and
[Matt Pocock's skills](https://github.com/mattpocock/skills).

It is provided as-is, without any warranty. Review the code before trusting it
with your Garmin session or your Wanderer API token. The Wanderer API token
grants full access to your Wanderer account.
