from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from garmin_to_wanderer.config import Config, SyncSettings
from garmin_to_wanderer.mapping import WandererTaxonomy
from garmin_to_wanderer.models import (
    ActivityStatus,
    DownloadedFile,
    GarminActivity,
)
from garmin_to_wanderer.state import StateStore
from garmin_to_wanderer.sync import SyncOptions, SyncRunner


def activity(
    garmin_id: str = "1", *, type_key: str = "road_biking", has_gps: bool = True
) -> GarminActivity:
    return GarminActivity(
        garmin_id=garmin_id,
        name="Morning ride",
        start_time=datetime(2024, 5, 1, 10, 0),
        type_key=type_key,
        parent_type_id=2,
        has_gps=has_gps,
        description="Nice ride",
    )


class FakeSource:
    def __init__(self, activities: list[GarminActivity]):
        self.activities = activities
        self.downloads: list[str] = []

    def iter_activities(self, since: date, until: date):
        return self.activities

    def download_original(self, garmin_id: str) -> DownloadedFile:
        self.downloads.append(garmin_id)
        return DownloadedFile(f"{garmin_id}.fit", b"FITDATA")


class FakeWanderer:
    def __init__(self, *, existing: set[str] | None = None, fail_metadata: bool = False):
        self.existing = set(existing or ())
        self.fail_metadata = fail_metadata
        self.uploaded: list[tuple[DownloadedFile, str]] = []
        self.updated: list[tuple[str, dict]] = []
        self.refreshed: list[tuple[str, DownloadedFile, dict]] = []
        self.get_calls: list[str] = []

    def get_trail(self, trail_id: str):
        self.get_calls.append(trail_id)
        return {"id": trail_id} if trail_id in self.existing else None

    def upload_file(self, file: DownloadedFile, *, name: str):
        self.uploaded.append((file, name))
        trail_id = f"trail-{len(self.uploaded)}"
        self.existing.add(trail_id)
        return {"id": trail_id}

    def update_trail(self, trail_id: str, **fields):
        if self.fail_metadata:
            raise RuntimeError("metadata boom")
        self.updated.append((trail_id, fields))
        return {"id": trail_id}

    def update_trail_file(self, trail_id: str, file: DownloadedFile, **fields):
        self.refreshed.append((trail_id, file, fields))
        self.existing.add(trail_id)
        return {"id": trail_id}


def taxonomy() -> WandererTaxonomy:
    return WandererTaxonomy.from_api(
        [
            {"id": "cat-biking", "name": "Biking"},
            {"id": "cat-other", "name": "Other"},
        ],
        [{"id": "sub-road", "name": "Road", "category": "cat-biking"}],
    )


def config(tmp_path: Path, **sync_overrides) -> Config:
    return Config(
        path=tmp_path / "config.yml",
        wanderer_url="https://w.test",
        wanderer_token="wanderer_key_test",
        garmin_email=None,
        state_dir=tmp_path,
        sync=SyncSettings(**sync_overrides),
        timeout=30,
    )


def runner(tmp_path: Path, source, wanderer, **sync_overrides):
    state = StateStore(tmp_path / "state.db")
    return (
        SyncRunner(
            source=source,
            wanderer=wanderer,
            state=state,
            taxonomy=taxonomy(),
            config=config(tmp_path, **sync_overrides),
        ),
        state,
    )


def options(**overrides) -> SyncOptions:
    defaults = {"since": date(2024, 5, 1), "until": date(2024, 5, 31)}
    defaults.update(overrides)
    return SyncOptions(**defaults)


def test_dry_run_does_not_write(tmp_path):
    source = FakeSource([activity()])
    wanderer = FakeWanderer()
    sync, state = runner(tmp_path, source, wanderer)

    report = sync.run(options(dry_run=True))

    assert report.counts() == {"would_import": 1}
    assert wanderer.uploaded == []
    assert state.get("1") is None
    state.close()


def test_imports_activity_and_metadata(tmp_path):
    source = FakeSource([activity()])
    wanderer = FakeWanderer()
    sync, state = runner(tmp_path, source, wanderer)

    report = sync.run(options())

    assert report.counts() == {"imported": 1}
    assert len(wanderer.uploaded) == 1
    trail_id, fields = wanderer.updated[0]
    assert trail_id == "trail-1"
    assert fields["name"] == "Morning ride"
    assert fields["description"] == "Nice ride"
    assert fields["category"] == "cat-biking"
    assert fields["subcategory"] == "sub-road"
    assert fields["date"] == "2024-05-01"
    stored = state.get("1")
    assert stored is not None
    assert stored.status == "imported"
    assert stored.wanderer_trail_id == "trail-1"
    state.close()


def test_skips_no_gps(tmp_path):
    source = FakeSource([activity(has_gps=False)])
    wanderer = FakeWanderer()
    sync, state = runner(tmp_path, source, wanderer)

    report = sync.run(options())

    assert report.counts() == {"skipped_no_gps": 1}
    assert wanderer.uploaded == []
    state.close()


def test_skips_already_imported(tmp_path):
    source = FakeSource([activity()])
    wanderer = FakeWanderer(existing={"trail-1"})
    sync, state = runner(tmp_path, source, wanderer)
    state.upsert(activity(), status=ActivityStatus.IMPORTED, wanderer_trail_id="trail-1")

    report = sync.run(options())

    assert report.counts() == {"skipped_already_imported": 1}
    assert wanderer.uploaded == []
    state.close()


def test_detects_deleted_in_wanderer(tmp_path):
    source = FakeSource([activity()])
    wanderer = FakeWanderer(existing=set())
    sync, state = runner(tmp_path, source, wanderer)
    state.upsert(activity(), status=ActivityStatus.IMPORTED, wanderer_trail_id="trail-1")

    report = sync.run(options())

    assert report.counts() == {"deleted_in_wanderer": 1}
    stored = state.get("1")
    assert stored is not None
    assert stored.status == "deleted_in_wanderer"
    assert wanderer.uploaded == []
    state.close()


def test_retries_partial_metadata_only(tmp_path):
    source = FakeSource([])
    wanderer = FakeWanderer(existing={"trail-1"})
    sync, state = runner(tmp_path, source, wanderer)
    state.upsert(activity(), status=ActivityStatus.PARTIAL, wanderer_trail_id="trail-1")

    report = sync.run(options())

    assert report.counts() == {"imported": 1}
    assert report.entries[0].message == "metadata retried"
    assert wanderer.uploaded == []
    assert wanderer.updated[0][0] == "trail-1"
    stored = state.get("1")
    assert stored is not None
    assert stored.status == "imported"
    state.close()


def test_metadata_failure_marks_partial(tmp_path):
    source = FakeSource([activity()])
    wanderer = FakeWanderer(fail_metadata=True)
    sync, state = runner(tmp_path, source, wanderer)

    report = sync.run(options())

    assert report.counts() == {"partial": 1}
    stored = state.get("1")
    assert stored is not None
    assert stored.status == "partial"
    assert stored.wanderer_trail_id == "trail-1"
    state.close()


def test_force_refreshes_existing_trail(tmp_path):
    source = FakeSource([activity()])
    wanderer = FakeWanderer(existing={"trail-1"})
    sync, state = runner(tmp_path, source, wanderer)
    state.upsert(activity(), status=ActivityStatus.IMPORTED, wanderer_trail_id="trail-1")

    report = sync.run(options(force=True))

    assert report.counts() == {"imported": 1}
    assert wanderer.uploaded == []
    assert len(wanderer.refreshed) == 1
    assert wanderer.refreshed[0][0] == "trail-1"
    state.close()


def test_excluded_type_is_reported(tmp_path):
    source = FakeSource([activity()])
    wanderer = FakeWanderer()
    sync, state = runner(tmp_path, source, wanderer, exclude=("road_biking",))

    report = sync.run(options())

    assert report.counts() == {"skipped_excluded": 1}
    assert wanderer.uploaded == []
    state.close()
