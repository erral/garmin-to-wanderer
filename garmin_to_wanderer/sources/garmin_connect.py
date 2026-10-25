from __future__ import annotations

import io
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from garmin_to_wanderer.models import DownloadedFile, GarminActivity
from garmin_to_wanderer.sources.base import (
    GarminAuthError,
    GarminDownloadError,
    GarminSourceError,
)


class GarminConnectSource:
    """GarminSource backed by the unofficial garminconnect client."""

    def __init__(
        self,
        tokenstore: Path,
        *,
        client: Any | None = None,
        retry_attempts: int = 3,
        retry_backoff: float = 1.0,
        chunk_days: int = 31,
    ):
        self.tokenstore = tokenstore
        self._client = client
        self.retry_attempts = retry_attempts
        self.retry_backoff = retry_backoff
        self.chunk_days = chunk_days

    def _get_client(self) -> Any:
        if self._client is None:
            from garminconnect import Garmin

            try:
                client = Garmin()
                client.login(str(self.tokenstore))
            except Exception as exc:
                raise GarminAuthError(
                    f"Garmin login failed. Run `setup garmin` again. ({exc})"
                ) from exc
            self._client = client
        return self._client

    def iter_activities(self, since: date, until: date) -> list[GarminActivity]:
        client = self._get_client()
        activities: list[GarminActivity] = []
        seen: set[str] = set()

        for chunk_start, chunk_end in _date_chunks(since, until, self.chunk_days):
            try:
                raw_activities = self._retry(
                    client.get_activities_by_date,
                    chunk_start.isoformat(),
                    chunk_end.isoformat(),
                    sortorder="asc",
                )
            except Exception as exc:
                if _is_auth_error(exc):
                    raise GarminAuthError(f"Garmin rejected the cached session: {exc}") from exc
                raise GarminSourceError(f"Could not list Garmin activities: {exc}") from exc

            for raw in raw_activities or []:
                activity = _to_activity(raw)
                if activity.garmin_id in seen:
                    continue
                seen.add(activity.garmin_id)
                activities.append(activity)

        return activities

    def _retry(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(self.retry_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                if _is_auth_error(exc) or attempt == self.retry_attempts - 1:
                    raise
                if self.retry_backoff > 0:
                    time.sleep(self.retry_backoff * (2**attempt))
        raise GarminSourceError("Garmin retry loop exhausted")

    def download_original(self, garmin_id: str) -> DownloadedFile:
        from garminconnect import Garmin

        client = self._get_client()
        original: bytes | None = None
        try:
            original = self._retry(
                client.download_activity,
                garmin_id,
                Garmin.ActivityDownloadFormat.ORIGINAL,
            )
        except Exception as exc:
            if _is_auth_error(exc):
                raise GarminAuthError(f"Garmin rejected the cached session: {exc}") from exc
            original = None

        if original:
            extracted = _extract_file(original, garmin_id)
            if extracted is not None:
                return extracted

        try:
            gpx = self._retry(
                client.download_activity,
                garmin_id,
                Garmin.ActivityDownloadFormat.GPX,
            )
        except Exception as exc:
            if _is_auth_error(exc):
                raise GarminAuthError(f"Garmin rejected the cached session: {exc}") from exc
            raise GarminDownloadError(
                f"Could not download activity {garmin_id} as FIT or GPX: {exc}"
            ) from exc

        if not gpx:
            raise GarminDownloadError(f"Garmin returned an empty file for {garmin_id}")
        return DownloadedFile(f"{garmin_id}.gpx", gpx, "application/gpx+xml")


def _date_chunks(start: date, end: date, days: int) -> list[tuple[date, date]]:
    if days < 1:
        raise ValueError("chunk_days must be at least 1")
    chunks: list[tuple[date, date]] = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days - 1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def _is_auth_error(exc: Exception) -> bool:
    try:
        from garminconnect.exceptions import GarminConnectAuthenticationError
    except ImportError:
        return "auth" in type(exc).__name__.lower()
    return isinstance(exc, GarminConnectAuthenticationError)


def _to_activity(raw: dict[str, Any]) -> GarminActivity:
    garmin_id = str(raw.get("activityId", ""))
    if not garmin_id:
        raise GarminSourceError("Garmin activity is missing activityId")

    activity_type = raw.get("activityType") or {}
    type_key = str(activity_type.get("typeKey") or "")
    parent_type_id = _as_int(activity_type.get("parentTypeId"))

    start_raw = raw.get("startTimeLocal") or raw.get("startTimeGMT") or raw.get("startTime")
    if not start_raw:
        raise GarminSourceError(f"Garmin activity {garmin_id} has no start time")
    start_time = _parse_datetime(str(start_raw))

    has_gps = bool(raw.get("hasPolyline"))
    if not has_gps:
        latitude = raw.get("startLatitude")
        longitude = raw.get("startLongitude")
        try:
            has_gps = (
                latitude is not None
                and longitude is not None
                and float(latitude) != 0.0
                and float(longitude) != 0.0
            )
        except (TypeError, ValueError):
            has_gps = False

    name = raw.get("activityName") or f"{type_key or 'activity'} {start_time.date()}"
    description = raw.get("description") or None

    return GarminActivity(
        garmin_id=garmin_id,
        name=str(name),
        start_time=start_time,
        type_key=type_key,
        parent_type_id=parent_type_id,
        has_gps=has_gps,
        description=str(description) if description else None,
    )


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_file(data: bytes, garmin_id: str) -> DownloadedFile | None:
    if data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                candidates = [
                    (".fit", "application/octet-stream"),
                    (".gpx", "application/gpx+xml"),
                    (".tcx", "application/vnd.garmin.tcx+xml"),
                    (".kml", "application/vnd.google-earth.kml+xml"),
                ]
                for suffix, content_type in candidates:
                    matches = [name for name in archive.namelist() if name.lower().endswith(suffix)]
                    if matches:
                        match = max(matches, key=lambda name: archive.getinfo(name).file_size)
                        return DownloadedFile(
                            f"{garmin_id}{suffix}",
                            archive.read(match),
                            content_type,
                        )
        except zipfile.BadZipFile:
            return None

    if len(data) >= 12 and data[8:12] == b".FIT":
        return DownloadedFile(f"{garmin_id}.fit", data, "application/octet-stream")

    head = data[:4000]
    if b"<gpx" in head:
        return DownloadedFile(f"{garmin_id}.gpx", data, "application/gpx+xml")
    if b"TrainingCenterDatabase" in head:
        return DownloadedFile(f"{garmin_id}.tcx", data, "application/vnd.garmin.tcx+xml")
    return None
