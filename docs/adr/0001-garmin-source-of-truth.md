# Garmin Connect is the source of truth; sync through an external CLI

**Status:** accepted

## Context

Strava's API terms changed and the Strava → Wanderer import stopped working.
Garmin Connect is where the user's activities are recorded, and an existing
`Dryusdan/garmin-to-fittrackee` setup already puts them into FitTrackee. Wanderer
is the place where the activities should be browsed and shared, and it has no
Garmin integration. A Wanderer provider plugin was considered, but the plugin
protocol is GPX-only, capped at 5,000 items per run, and has no reliable
cross-run cursor; FitTrackee's OAuth2/cookie flow and a self-hosted base URL do
not fit its connector model well.

## Decision

Use **Garmin Connect as the source of truth** and build an **external Python
CLI** (`garmin-to-wanderer`) that imports activities into Wanderer. Keep
FitTrackee untouched as a parallel sink fed by `garmin-to-fittrackee`.

The Garmin client sits behind a `GarminSource` adapter. The first
implementation uses the unofficial `garminconnect` library with cached tokens;
the official Garmin Personal API can be added later behind the same interface.
Wanderer import is two calls: `PUT /api/v1/trail/upload` for the FIT/GPX file,
then `POST /api/v1/trail/form/{id}` for the category, description, and date.
A local SQLite mapping keyed by Garmin activity ID is the dedupe authority, with
a 48-hour overlap cursor and a required `--since`/`SYNC_SINCE` on the first run.

Wanderer converts uploaded FIT files to GPX and discards the original FIT.
Heart rate is dropped by that conversion and Wanderer has no heart-rate field,
so client-side FIT→GPX conversion is deliberately not implemented.

## Consequences

- **Unofficial Garmin access risk.** `garminconnect` depends on Garmin's private
  SSO and is exposed to TLS-fingerprint and ToS changes. The adapter is the
  escape hatch to the official Personal API.
- **No two-way sync.** Wanderer edits and deletions never flow back to Garmin or
  FitTrackee. Deleted trails are reported, not silently re-imported.
- **FIT is not archived.** Wanderer keeps a converted GPX, not the original FIT.
- **No GPS, no import.** Activities without GPS are skipped and reported.
- **Deployment shape.** The sync runs on the homelab because Garmin tokens are
  cached on disk and Wanderer may be LAN/VPN-only. GitHub Actions is used for CI
  and an optional manual token-cache-based run, not a scheduled sync.

## Considered options

- **Wanderer plugin:** rejected for the protocol limits above (GPX-only, 5,000
  items/run, no reliable cross-run state, awkward self-hosted auth).
- **FitTrackee as source of truth:** rejected because the user keeps
  `garmin-to-fittrackee` as an independent parallel sink and wants Garmin to
  remain canonical.
- **Garmin device folder / bulk GDPR export:** rejected as the primary path
  because it is not real-time and requires manual steps.
- **Official Garmin Personal API now:** deferred, not rejected. It is newer and
  requires periodic key rotation, so the adapter boundary keeps it available.
