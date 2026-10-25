# Write the SOT / integration ADR

Type: task
Status: resolved
Blocked by: 01, 02, 03, 04, 05

## Question

Write a short ADR recording:

- Why Garmin Connect is the source of truth, with FitTrackee as a parallel sink.
- Why an external Python CLI instead of a Wanderer plugin.
- The chosen Garmin access method, its risks, and its credential rotation.
- The ingest format (FIT vs GPX) and what metadata is preserved.
- The incremental and dedupe model.

Location: `docs/adr/0001-garmin-source-of-truth.md`.

Definition of done: a future reader understands the trade-offs without reading
this map.

## Answer

Wrote `docs/adr/0001-garmin-source-of-truth.md`. It records Garmin Connect as
the source of truth, FitTrackee as a parallel sink, the external CLI over a
Wanderer plugin, the `garminconnect`-behind-`GarminSource` choice, the two-step
Wanderer import, FIT→GPX limitations, and the SQLite/48-hour cursor model. It
also records the rejected alternatives and the deferred official Personal API.
