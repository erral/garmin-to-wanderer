# Garmin → Wanderer sync

## Destination

A working Python CLI, `garmin-to-wanderer`, that treats **Garmin Connect as the
source of truth** and imports completed activities into Wanderer. It syncs
incrementally from the last imported activity by default, supports explicit
date-range backfills, offers a dry-run report, and runs unattended on the
homelab. A short ADR records the source-of-truth and integration-shape
decisions.

## Notes

- **Domain:** Garmin Connect → Wanderer. FitTrackee stays a parallel sink fed by
  `Dryusdan/garmin-to-fittrackee`; the new tool does not touch FitTrackee.
- **Instances:** `https://track.erral.freemyip.com` (FitTrackee),
  `https://wanderer.erral.freemyip.com` (Wanderer). Both are LAN/VPN-only from
  the agent environment; the user runs live smoke tests.
- **Standing decisions from charting:**
  - Source of truth = Garmin Connect.
  - Integration shape = external Python CLI, **not** a Wanderer plugin. The
    plugin protocol is GPX-only, capped at 5,000 items/run, and has no reliable
    cross-run cursor.
  - One-way only: Garmin → Wanderer. No write-back, no FitTrackee involvement.
  - Default sync starts after the last imported activity; `--since`/`--until`
    cover backfills; `--dry-run` produces a report without writing.
  - Keep `garmin-to-fittrackee` as-is; do not merge or modify it.
  - The user runs live smoke tests. Never ask for credentials in chat.
- **Conventions:** Python 3.12; mirror `garmin-to-fittrackee` where it makes
  sense (`config.yml`, SQLite state, CLI); no secrets committed.
- **Garmin access:** `garminconnect` behind a `GarminSource` adapter. The sync
  pipeline must never depend on the Garmin client directly; the official
  Personal API is a future adapter.
- **Wanderer auth:** `Authorization: Bearer wanderer_key_...`; an API token has
  full account access, so treat it as a secret.
- **Skills:** grilling, domain-modeling, research.
- **Map complete:** all tickets resolved on 2026-10-25. The remaining work is
  deployment smoke testing and optional future adapters, not unresolved scope.

## Decisions so far

- [Confirm Wanderer ingest contract](issues/02-wanderer-ingest-contract.md):
  FIT is accepted but converted to GPX (original discarded); upload takes only a
  name fallback, so category/difficulty/description need a second form update;
  duplicate detection is geometry-only and date-blind, so bypass it with our own
  mapping.
- [Choose Garmin access method](issues/01-garmin-access-method.md): hybrid — a
  `GarminSource` adapter, implemented first with `garminconnect` (email/password
  + MFA, cached tokens); the official Personal API is a future adapter, not
  built now.
- [Define incremental state and dedupe](issues/03-sync-state-and-dedupe.md):
  SQLite mapping keyed by Garmin id plus a 48-hour-overlap cursor; first run
  requires `--since`/`SYNC_SINCE`; trails deleted in Wanderer are reported but
  not re-imported; partial imports retry metadata only.
- [Define activity selection and sport mapping](issues/04-activity-selection-and-mapping.md):
  import all GPS-bearing activities (config include/exclude), skip no-GPS with a
  report line, send FIT without client-side HR preservation, use Garmin
  name/description, and a config-overridable `typeKey` → category mapping
  resolved by name at runtime.
- [Define CLI, config, and report](issues/05-cli-config-and-report.md):
  `setup garmin`, `setup wanderer`, `sync`, and `status`; YAML config with env
  overrides for secrets; human summary plus optional JSON report; exit codes
  0/1/2/3 for cron.
- [Implement core CLI, auth, and Wanderer upload](issues/06-implement-core-cli.md):
  Python package + Typer CLI, Garmin adapter, two-step Wanderer upload, SQLite
  state; 54 tests pass. Live smoke test is a deployment step.
- [Implement incremental sync, backfill, and reporting](issues/07-implement-incremental-and-backfill.md):
  48-hour cursor overlap, 31-day backfill chunks, retries/backoff for GET/POST
  but not upload, partial/failed recovery, and dry-run/JSON reports.
- [Package, schedule, and document](issues/08-package-and-schedule.md):
  README with disclaimer, CI and manual-sync GitHub Actions, systemd/cron
  examples, and an example config.
- [Write the SOT / integration ADR](issues/09-write-adr.md):
  `docs/adr/0001-garmin-source-of-truth.md` records the source-of-truth,
  integration-shape, adapter, and ingest trade-offs.

## Not yet specified

<!-- All tickets resolved on 2026-10-25. The destination is implemented. -->


## Out of scope

- Building a Wanderer plugin.
- Two-way sync, or writing back to Garmin or FitTrackee.
- Replacing, merging, or modifying `garmin-to-fittrackee`.
- Reconciling or merging trails already imported into Wanderer from Strava.
- Multi-user support; this is a single-user homelab.
