from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from garmin_to_wanderer.sources.base import GarminDownloadError
from garmin_to_wanderer.sources.garmin_connect import (
    GarminConnectSource,
    _extract_file,
    _to_activity,
)


class FakeClient:
    def __init__(self, *, activities=None, original=None, gpx=None):
        self.activities = activities or []
        self.original = original
        self.gpx = gpx
        self.calls = []

    def get_activities_by_date(self, startdate, enddate, sortorder=None):
        self.calls.append((startdate, enddate, sortorder))
        return self.activities

    def download_activity(self, activity_id, dl_fmt):
        self.calls.append((activity_id, dl_fmt))
        if dl_fmt.name == "ORIGINAL":
            if self.original is None:
                raise RuntimeError("no original")
            return self.original
        return self.gpx


def raw_activity(**overrides):
    raw = {
        "activityId": 123,
        "activityName": "Morning ride",
        "startTimeLocal": "2024-05-01 10:00:00",
        "activityType": {"typeKey": "road_biking", "parentTypeId": 2},
        "startLatitude": 43.0,
        "startLongitude": -2.0,
    }
    raw.update(overrides)
    return raw


def test_to_activity_parses_fields():
    activity = _to_activity(raw_activity())

    assert activity.garmin_id == "123"
    assert activity.name == "Morning ride"
    assert activity.type_key == "road_biking"
    assert activity.parent_type_id == 2
    assert activity.has_gps is True
    assert activity.start_time.year == 2024


def test_to_activity_without_gps():
    activity = _to_activity(raw_activity(startLatitude=0.0, startLongitude=0.0, hasPolyline=False))
    assert activity.has_gps is False


def test_to_activity_name_fallback():
    activity = _to_activity(raw_activity(activityName=None))
    assert activity.name == "road_biking 2024-05-01"


def test_iter_activities_uses_date_range():
    fake = FakeClient(activities=[raw_activity()])
    source = GarminConnectSource(tokenstore=None, client=fake)  # type: ignore[arg-type]

    activities = source.iter_activities(date(2024, 5, 1), date(2024, 5, 31))

    assert [item.garmin_id for item in activities] == ["123"]
    assert fake.calls == [("2024-05-01", "2024-05-31", "asc")]


def test_listing_retries_transient_error():
    class FlakyClient(FakeClient):
        def __init__(self):
            super().__init__(activities=[raw_activity()])
            self.failures = 1

        def get_activities_by_date(self, startdate, enddate, sortorder=None):
            if self.failures:
                self.failures -= 1
                raise RuntimeError("transient")
            return super().get_activities_by_date(startdate, enddate, sortorder)

    fake = FlakyClient()
    source = GarminConnectSource(
        tokenstore=None,  # type: ignore[arg-type]
        client=fake,
        retry_attempts=2,
        retry_backoff=0,
    )

    activities = source.iter_activities(date(2024, 5, 1), date(2024, 5, 31))

    assert [item.garmin_id for item in activities] == ["123"]
    assert fake.failures == 0


def test_listing_chunks_long_ranges():
    fake = FakeClient(activities=[])
    source = GarminConnectSource(
        tokenstore=None,  # type: ignore[arg-type]
        client=fake,
        chunk_days=31,
    )

    source.iter_activities(date(2024, 1, 1), date(2024, 3, 15))

    assert fake.calls == [
        ("2024-01-01", "2024-01-31", "asc"),
        ("2024-02-01", "2024-03-02", "asc"),
        ("2024-03-03", "2024-03-15", "asc"),
    ]


def test_auth_errors_are_not_retried():
    from garminconnect.exceptions import GarminConnectAuthenticationError

    class AuthFailClient(FakeClient):
        def get_activities_by_date(self, startdate, enddate, sortorder=None):
            raise GarminConnectAuthenticationError("bad token")

    fake = AuthFailClient()
    source = GarminConnectSource(
        tokenstore=None,  # type: ignore[arg-type]
        client=fake,
        retry_attempts=3,
        retry_backoff=0,
    )

    with pytest.raises(Exception, match="bad token"):
        source.iter_activities(date(2024, 5, 1), date(2024, 5, 31))


def test_extract_fit_header():
    data = b"\x0c\x10\x00\x00\x00\x00\x00\x00.FIT" + b"payload"
    extracted = _extract_file(data, "42")
    assert extracted is not None
    assert extracted.filename == "42.fit"


def test_extract_gpx():
    extracted = _extract_file(b'<?xml version="1.0"?><gpx></gpx>', "42")
    assert extracted is not None
    assert extracted.filename == "42.gpx"


def test_extract_fit_from_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "ignore me")
        archive.writestr("activity.fit", b"FITDATA")
    extracted = _extract_file(buffer.getvalue(), "42")
    assert extracted is not None
    assert extracted.filename == "42.fit"
    assert extracted.content == b"FITDATA"


def test_download_original_extracts_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("activity.fit", b"FITDATA")
    fake = FakeClient(original=buffer.getvalue())
    source = GarminConnectSource(tokenstore=None, client=fake)  # type: ignore[arg-type]

    downloaded = source.download_original("42")

    assert downloaded.filename == "42.fit"
    assert downloaded.content == b"FITDATA"


def test_download_original_falls_back_to_gpx():
    fake = FakeClient(original=b"not a zip", gpx=b'<?xml version="1.0"?><gpx></gpx>')
    source = GarminConnectSource(tokenstore=None, client=fake)  # type: ignore[arg-type]

    downloaded = source.download_original("42")

    assert downloaded.filename == "42.gpx"


def test_download_original_raises_when_gpx_missing():
    fake = FakeClient(original=b"not a zip", gpx=None)
    source = GarminConnectSource(tokenstore=None, client=fake)  # type: ignore[arg-type]

    with pytest.raises(GarminDownloadError):
        source.download_original("42")
