from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol

from garmin_to_wanderer.models import DownloadedFile, GarminActivity


class GarminSourceError(Exception):
    """Base error for Garmin access failures."""


class GarminAuthError(GarminSourceError):
    """Raised when Garmin credentials or cached tokens are invalid."""


class GarminDownloadError(GarminSourceError):
    """Raised when an activity file cannot be downloaded."""


class GarminSource(Protocol):
    def iter_activities(self, since: date, until: date) -> Iterable[GarminActivity]:
        """Yield completed activities in the inclusive date range, oldest first."""
        ...

    def download_original(self, garmin_id: str) -> DownloadedFile:
        """Download the activity file to upload to Wanderer."""
        ...
