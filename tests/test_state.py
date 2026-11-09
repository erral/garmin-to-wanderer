from __future__ import annotations

from datetime import date, datetime

from garmin_to_wanderer.models import ActivityStatus, GarminActivity
from garmin_to_wanderer.state import StateStore


def activity(garmin_id: str = "1", *, has_gps: bool = True) -> GarminActivity:
    return GarminActivity(
        garmin_id=garmin_id,
        name=f"Activity {garmin_id}",
        start_time=datetime(2024, 5, 1, 10, 0),
        type_key="hiking",
        parent_type_id=3,
        has_gps=has_gps,
        description="A description",
    )


def test_upsert_and_get(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        record = activity()
        state.upsert(record, status=ActivityStatus.IMPORTED, wanderer_trail_id="trail-1")

        stored = state.get("1")

    assert stored is not None
    assert stored.wanderer_trail_id == "trail-1"
    assert stored.status == "imported"
    assert stored.has_gps is True
    assert stored.description == "A description"
    assert stored.parent_type_id == 3
    assert stored.imported_at is not None


def test_list_by_status_and_counts(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        state.upsert(activity("1"), status=ActivityStatus.FAILED, error="boom")
        state.upsert(activity("2"), status=ActivityStatus.IMPORTED, wanderer_trail_id="t2")
        state.upsert(activity("3"), status=ActivityStatus.FAILED, error="boom")

        failed = state.list_by_status(ActivityStatus.FAILED)
        counts = state.counts()

    assert [record.garmin_id for record in failed] == ["1", "3"]
    assert counts == {"failed": 2, "imported": 1}


def test_set_status_and_reset(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        record = activity()
        state.upsert(record, status=ActivityStatus.FAILED, error="boom")
        state.set_status("1", ActivityStatus.IMPORTED, wanderer_trail_id="trail-1", error=None)
        stored = state.get("1")
        assert stored is not None
        assert stored.status == "imported"
        assert stored.wanderer_trail_id == "trail-1"
        assert stored.error is None

        state.reset()
        assert state.get("1") is None


def activity_at(garmin_id: str, started_at: datetime) -> GarminActivity:
    return GarminActivity(
        garmin_id=garmin_id,
        name=f"Activity {garmin_id}",
        start_time=started_at,
        type_key="hiking",
    )


def test_watermark_starts_empty_and_advances_only_forward(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        assert state.last_seen_started_at() is None

        state.advance_watermark(datetime(2024, 5, 1, 10, 0))
        assert state.last_seen_started_at() == datetime(2024, 5, 1, 10, 0)

        state.advance_watermark(datetime(2024, 4, 1, 10, 0))
        assert state.last_seen_started_at() == datetime(2024, 5, 1, 10, 0)

        state.advance_watermark(datetime(2024, 6, 1, 10, 0))
        assert state.last_seen_started_at() == datetime(2024, 6, 1, 10, 0)


def test_watermark_seeds_from_existing_activities_on_upgrade(tmp_path):
    import sqlite3

    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE activities (
            garmin_id TEXT PRIMARY KEY,
            wanderer_trail_id TEXT,
            started_at TEXT NOT NULL,
            name TEXT NOT NULL,
            type_key TEXT NOT NULL DEFAULT '',
            parent_type_id INTEGER,
            has_gps INTEGER NOT NULL DEFAULT 1,
            description TEXT,
            status TEXT NOT NULL,
            imported_at TEXT,
            error TEXT
        );
        INSERT INTO activities (garmin_id, started_at, name, status)
        VALUES ('old', '2023-01-05T08:00:00', 'Old', 'failed');
        """
    )
    conn.commit()
    conn.close()

    with StateStore(db) as state:
        assert state.last_seen_started_at() == datetime(2023, 1, 5, 8, 0)


def test_reset_clears_the_watermark(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        state.advance_watermark(datetime(2024, 5, 1, 10, 0))

        state.reset()

        assert state.last_seen_started_at() is None


def test_list_recoverable_orders_partial_then_failed_without_limit(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        state.upsert(
            activity_at("P1", datetime(2024, 5, 1)),
            status=ActivityStatus.PARTIAL,
            wanderer_trail_id="t1",
        )
        state.upsert(activity_at("F1", datetime(2024, 4, 1)), status=ActivityStatus.FAILED)
        state.upsert(activity_at("F2", datetime(2024, 6, 1)), status=ActivityStatus.FAILED)
        state.upsert(
            activity_at("P2", datetime(2024, 3, 1)),
            status=ActivityStatus.PARTIAL,
            wanderer_trail_id="t2",
        )

        ids = [record.garmin_id for record in state.list_recoverable()]

        assert ids == ["P2", "P1", "F1", "F2"]


def test_list_recoverable_window_filters_by_local_start_date(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        state.upsert(
            activity_at("P1", datetime(2024, 5, 1)),
            status=ActivityStatus.PARTIAL,
            wanderer_trail_id="t1",
        )
        state.upsert(activity_at("F1", datetime(2024, 4, 1)), status=ActivityStatus.FAILED)
        state.upsert(activity_at("F2", datetime(2024, 6, 1)), status=ActivityStatus.FAILED)

        ids = [
            record.garmin_id
            for record in state.list_recoverable(since=date(2024, 5, 1), until=date(2024, 5, 31))
        ]

        assert ids == ["P1"]


def test_list_recoverable_limit_picks_oldest_across_statuses(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        state.upsert(
            activity_at("P1", datetime(2024, 5, 1)),
            status=ActivityStatus.PARTIAL,
            wanderer_trail_id="t1",
        )
        state.upsert(activity_at("F1", datetime(2024, 4, 1)), status=ActivityStatus.FAILED)
        state.upsert(activity_at("F2", datetime(2024, 6, 1)), status=ActivityStatus.FAILED)
        state.upsert(
            activity_at("P2", datetime(2024, 3, 1)),
            status=ActivityStatus.PARTIAL,
            wanderer_trail_id="t2",
        )

        ids = [record.garmin_id for record in state.list_recoverable(limit=3)]

        assert ids == ["P2", "P1", "F1"]


def test_count_unresolved_counts_failed_and_partial(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        state.upsert(activity_at("F1", datetime(2024, 4, 1)), status=ActivityStatus.FAILED)
        state.upsert(
            activity_at("P1", datetime(2024, 5, 1)),
            status=ActivityStatus.PARTIAL,
            wanderer_trail_id="t1",
        )
        state.upsert(
            activity_at("I1", datetime(2024, 3, 1)),
            status=ActivityStatus.IMPORTED,
            wanderer_trail_id="t2",
        )

        assert state.count_unresolved() == 2


def test_watermark_seeds_when_the_key_is_missing(tmp_path):
    import sqlite3

    db = tmp_path / "state.db"
    with StateStore(db) as state:
        state.upsert(activity_at("x", datetime(2024, 5, 5, 9, 0)), status=ActivityStatus.FAILED)

    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM sync_state")
    conn.commit()
    conn.close()

    with StateStore(db) as state:
        assert state.last_seen_started_at() == datetime(2024, 5, 5, 9, 0)
