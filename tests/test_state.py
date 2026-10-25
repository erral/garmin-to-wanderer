from __future__ import annotations

from datetime import datetime

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


def test_last_imported_start_uses_latest(tmp_path):
    with StateStore(tmp_path / "state.db") as state:
        older = activity("1")
        newer = GarminActivity(
            garmin_id="2",
            name="Newer",
            start_time=datetime(2024, 6, 1, 10, 0),
            type_key="hiking",
        )
        state.upsert(older, status=ActivityStatus.IMPORTED, wanderer_trail_id="t1")
        state.upsert(newer, status=ActivityStatus.PARTIAL, wanderer_trail_id="t2")

        assert state.last_imported_start() == datetime(2024, 6, 1, 10, 0)


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
