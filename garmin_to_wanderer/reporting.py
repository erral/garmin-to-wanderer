from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from garmin_to_wanderer.models import ActivityStatus, GarminActivity

EntryCallback = Callable[["ReportEntry"], None]

_FAILURE_STATUSES = (ActivityStatus.PARTIAL, ActivityStatus.FAILED)


@dataclass(frozen=True, slots=True)
class ReportEntry:
    garmin_id: str
    name: str
    started_at: str | None
    status: ActivityStatus
    wanderer_id: str | None = None
    message: str | None = None
    type_key: str = ""
    has_description: bool = False

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "garmin_id": self.garmin_id,
            "name": self.name,
            "started_at": self.started_at,
            "status": str(self.status),
            "wanderer_id": self.wanderer_id,
            "message": self.message,
            "type_key": self.type_key,
            "has_description": self.has_description,
        }


class Report:
    def __init__(
        self,
        *,
        since: date,
        until: date,
        dry_run: bool,
        on_entry: EntryCallback | None = None,
    ):
        self.since = since
        self.until = until
        self.dry_run = dry_run
        self.entries: list[ReportEntry] = []
        self._on_entry = on_entry

    def add(
        self,
        activity: GarminActivity,
        status: ActivityStatus,
        *,
        wanderer_id: str | None = None,
        message: str | None = None,
    ) -> None:
        entry = ReportEntry(
            garmin_id=activity.garmin_id,
            name=activity.name,
            started_at=activity.start_time.isoformat(),
            status=status,
            wanderer_id=wanderer_id,
            message=message,
            type_key=activity.type_key,
            has_description=bool(activity.description),
        )
        self.entries.append(entry)
        if self._on_entry is not None:
            self._on_entry(entry)

    def counts(self) -> dict[str, int]:
        return dict(Counter(str(entry.status) for entry in self.entries))

    def has_failures(self) -> bool:
        return any(_is_failure(entry) for entry in self.entries)

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

    def print_summary(self, *, elapsed: float, report_path: Path | None = None) -> None:
        self._print_report(elapsed=elapsed, report_path=report_path)

    def print_human(
        self,
        *,
        verbose: bool = False,
        elapsed: float | None = None,
        report_path: Path | None = None,
    ) -> None:
        self._print_report(
            elapsed=elapsed,
            report_path=report_path,
            include_entries=True,
            verbose=verbose,
        )

    def _print_report(
        self,
        *,
        elapsed: float | None,
        report_path: Path | None,
        include_entries: bool = False,
        verbose: bool = False,
    ) -> None:
        self._print_header()
        self._print_counts()

        if include_entries and self.entries:
            print("")
            for entry in self.entries:
                print(format_entry(entry, verbose=verbose))

        if elapsed is not None:
            print(f"Elapsed: {elapsed:.1f}s")
        self._print_report_path(report_path)

    def _print_header(self) -> None:
        mode = " (dry run)" if self.dry_run else ""
        print(f"Garmin -> Wanderer: {self.since} to {self.until}{mode}")

    def _print_counts(self) -> None:
        counts = self.counts()
        if not counts:
            print("  no activities in range")
            return
        for status in ActivityStatus:
            count = counts.get(str(status))
            if count:
                print(f"  {status}: {count}")

    def _print_report_path(self, report_path: Path | None) -> None:
        if report_path is not None:
            print(f"Report written to {report_path}.")


def format_entry(entry: ReportEntry, *, verbose: bool = False) -> str:
    line = f"  {_short_time(entry.started_at)}  {entry.name}  [{entry.status}]"
    if verbose:
        if entry.type_key:
            line += f" type={entry.type_key}"
        if entry.wanderer_id:
            line += f" trail={entry.wanderer_id}"
        if entry.has_description:
            line += " description=yes"
    if entry.message and (verbose or _is_failure(entry)):
        line += f" - {entry.message}"
    return line


class ConsoleReporter:
    """Streams activity outcomes as they happen."""

    def __init__(self, *, verbose: bool = False, quiet: bool = False):
        self.verbose = verbose
        self.quiet = quiet

    def phase(self, message: str) -> None:
        if self.verbose and not self.quiet:
            print(f"  ... {message}", flush=True)

    def entry(self, entry: ReportEntry) -> None:
        if self.quiet:
            if _is_failure(entry):
                print(format_entry(entry), file=sys.stderr, flush=True)
            return
        print(format_entry(entry, verbose=self.verbose), flush=True)


def _is_failure(entry: ReportEntry) -> bool:
    return entry.status in _FAILURE_STATUSES


def _short_time(value: str | None) -> str:
    if not value:
        return "?"
    return value.replace("T", " ")[:16]
