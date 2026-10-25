# Choose Garmin access method

Type: grilling
Status: resolved
Blocked by: none

## Question

How should `garmin-to-wanderer` authenticate to Garmin Connect?

Options:

1. **Official Garmin Personal API** (released October 2026). Create a personal
   API key in Garmin Connect, exchange it for a 24-hour bearer token, then pull
   activities as JSON plus the original FIT file. The key expires after
   30/90/180/365 days and must be rotated manually. Official and sanctioned, but
   new and more setup.
2. **Unofficial `garminconnect` library** (what `garmin-to-fittrackee` uses).
   Email/password plus MFA, cached tokens, automatic refresh. Relies on Garmin's
   private mobile SSO, is exposed to TLS-fingerprint blocking and rate limits,
   and carries ToS/account risk.
3. **Hybrid.** Start with `garminconnect` for parity with the existing tool, but
   put Garmin behind a thin `GarminSource` adapter so the official Personal API
   can replace it later.

Consider: consistency with `garmin-to-fittrackee`, maintenance burden, legal
risk, key rotation, MFA, and whether a Personal API key can be created for this
account.

Leaning: official Personal API behind a `GarminSource` adapter, falling back to
`garminconnect` only if the key cannot be created.

## Answer

Resolved with the user: **Option C, hybrid.**

- Define a `GarminSource` protocol in the tool — at least
  `iter_activities(since, until)` and `download_original(activity_id)` — so the
  sync pipeline never depends on a specific Garmin client.
- Implement `GarminConnectSource` first, using the unofficial `garminconnect`
  library (same family as `garmin-to-fittrackee`; version `>=0.3.11`, current
  `0.3.20`). It handles email/password + MFA, caches tokens, and refreshes them
  while the refresh token is valid.
- `setup garmin` performs the interactive login and MFA prompt. The token cache
  lives under the configured state directory (for example
  `~/.local/share/garmin-to-wanderer/garmintoken/`).
- Do **not** store the Garmin password by default. Accept it via prompt or a
  `GARMIN_PASSWORD` environment variable for the initial setup only.
- A scheduled `sync` uses only the cached token. If Garmin demands a fresh MFA
  login, the run fails with a clear "run `setup garmin`" error; it must not retry
  the password endlessly.
- Keep `PersonalApiSource` (official Garmin Personal API) as a future adapter
  behind the same protocol. It is not implemented now.
- Risks accepted: the unofficial client is exposed to Garmin's SSO/TLS
  fingerprinting changes and ToS risk. The adapter is the escape hatch: if
  `garminconnect` breaks, swap to the official API without touching the sync
  pipeline.
