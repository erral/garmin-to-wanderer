from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from garmin_to_wanderer.models import ActivityStatus, GarminActivity


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    garmin_id: str
    wanderer_trail_id: str | None
    started_at: str
    name: str
    type_key: str
    parent_type_id: int | None
    has_gps: bool
    description: str | None
    status: str
    imported_at: str | None = None
    error: str | None = None


class StateStore:
    """SQLite mapping between Garmin activities and Wanderer trails."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS activities (
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
            CREATE INDEX IF NOT EXISTS idx_activities_status
                ON activities(status);
            """
        )
        self._conn.commit()

    def get(self, garmin_id: str) -> ActivityRecord | None:
        row = self._conn.execute(
            "SELECT * FROM activities WHERE garmin_id = ?", (str(garmin_id),)
        ).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_by_status(self, status: ActivityStatus | str) -> list[ActivityRecord]:
        rows = self._conn.execute(
            "SELECT * FROM activities WHERE status = ? ORDER BY started_at ASC",
            (str(status),),
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def upsert(
        self,
        activity: GarminActivity,
        *,
        status: ActivityStatus | str,
        wanderer_trail_id: str | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO activities (
                garmin_id, wanderer_trail_id, started_at, name, type_key,
                parent_type_id, has_gps, description, status, imported_at, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(garmin_id) DO UPDATE SET
                wanderer_trail_id = excluded.wanderer_trail_id,
                started_at = excluded.started_at,
                name = excluded.name,
                type_key = excluded.type_key,
                parent_type_id = excluded.parent_type_id,
                has_gps = excluded.has_gps,
                description = excluded.description,
                status = excluded.status,
                imported_at = excluded.imported_at,
                error = excluded.error
            """,
            (
                str(activity.garmin_id),
                wanderer_trail_id,
                activity.start_time.isoformat(),
                activity.name,
                activity.type_key,
                activity.parent_type_id,
                int(activity.has_gps),
                activity.description,
                str(status),
                now if status in (ActivityStatus.IMPORTED, ActivityStatus.PARTIAL) else None,
                error,
            ),
        )
        self._conn.commit()

    def set_status(
        self,
        garmin_id: str,
        status: ActivityStatus | str,
        *,
        wanderer_trail_id: str | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            UPDATE activities
            SET status = ?, wanderer_trail_id = COALESCE(?, wanderer_trail_id),
                imported_at = COALESCE(?, imported_at), error = ?
            WHERE garmin_id = ?
            """,
            (
                str(status),
                wanderer_trail_id,
                now if status in (ActivityStatus.IMPORTED, ActivityStatus.PARTIAL) else None,
                error,
                str(garmin_id),
            ),
        )
        self._conn.commit()

    def last_imported_start(self) -> datetime | None:
        row = self._conn.execute(
            """
            SELECT started_at FROM activities
            WHERE status IN (?, ?)
            ORDER BY started_at DESC LIMIT 1
            """,
            (str(ActivityStatus.IMPORTED), str(ActivityStatus.PARTIAL)),
        ).fetchone()
        return datetime.fromisoformat(row["started_at"]) if row is not None else None

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS count FROM activities GROUP BY status"
        ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    def reset(self) -> None:
        self._conn.executescript("DELETE FROM activities;")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _row_to_record(row: sqlite3.Row) -> ActivityRecord:
    return ActivityRecord(
        garmin_id=row["garmin_id"],
        wanderer_trail_id=row["wanderer_trail_id"],
        started_at=row["started_at"],
        name=row["name"],
        type_key=row["type_key"],
        parent_type_id=row["parent_type_id"],
        has_gps=bool(row["has_gps"]),
        description=row["description"],
        status=row["status"],
        imported_at=row["imported_at"],
        error=row["error"],
    )
