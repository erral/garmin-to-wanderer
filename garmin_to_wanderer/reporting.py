from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from garmin_to_wanderer.models import ActivityStatus, GarminActivity


@dataclass(frozen=True, slots=True)
class ReportEntry:
    garmin_id: str
    name: str
    started_at: str | None
    status: ActivityStatus
    wanderer_id: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "garmin_id": self.garmin_id,
            "name": self.name,
            "started_at": self.started_at,
            "status": str(self.status),
            "wanderer_id": self.wanderer_id,
            "message": self.message,
        }


class Report:
    def __init__(self, *, since: date, until: date, dry_run: bool):
        self.since = since
        self.until = until
        self.dry_run = dry_run
        self.entries: list[ReportEntry] = []

    def add(
        self,
        activity: GarminActivity,
        status: ActivityStatus,
        *,
        wanderer_id: str | None = None,
        message: str | None = None,
    ) -> None:
        self.entries.append(
            ReportEntry(
                garmin_id=activity.garmin_id,
                name=activity.name,
                started_at=activity.start_time.isoformat(),
                status=status,
                wanderer_id=wanderer_id,
                message=message,
            )
        )

    def counts(self) -> dict[str, int]:
        return dict(Counter(str(entry.status) for entry in self.entries))

    def has_failures(self) -> bool:
        return any(
            entry.status in (ActivityStatus.PARTIAL, ActivityStatus.FAILED)
            for entry in self.entries
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "dry_run": self.dry_run,
            "counts": self.counts(),
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def print_human(self, *, verbose: bool = False) -> None:
        mode = " (dry run)" if self.dry_run else ""
        print(f"Garmin -> Wanderer: {self.since} to {self.until}{mode}")
        counts = self.counts()
        if not counts:
            print("  no activities in range")
            return
        for status in ActivityStatus:
            count = counts.get(str(status))
            if count:
                print(f"  {status}: {count}")

        interesting = [
            entry
            for entry in self.entries
            if verbose
            or entry.status
            not in (ActivityStatus.IMPORTED, ActivityStatus.SKIPPED_ALREADY_IMPORTED)
        ]
        if not interesting:
            return
        print("")
        for entry in interesting:
            line = f"  {entry.started_at or '?'}  {entry.name}  [{entry.status}]"
            if entry.wanderer_id:
                line += f" trail={entry.wanderer_id}"
            if entry.message:
                line += f" - {entry.message}"
            print(line)
