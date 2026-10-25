from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ActivityStatus(StrEnum):
    IMPORTED = "imported"
    WOULD_IMPORT = "would_import"
    SKIPPED_NO_GPS = "skipped_no_gps"
    SKIPPED_EXCLUDED = "skipped_excluded"
    SKIPPED_ALREADY_IMPORTED = "skipped_already_imported"
    DELETED_IN_WANDERER = "deleted_in_wanderer"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class GarminActivity:
    garmin_id: str
    name: str
    start_time: datetime
    type_key: str
    parent_type_id: int | None = None
    has_gps: bool = True
    description: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadedFile:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"
