from __future__ import annotations

import pytest
import requests
import requests_mock

from garmin_to_wanderer.models import DownloadedFile
from garmin_to_wanderer.wanderer import (
    WandererAuthError,
    WandererClient,
    WandererDuplicateError,
)


def client() -> WandererClient:
    return WandererClient("https://w.test/", "wanderer_key_test")


def test_list_categories_and_subcategories():
    with requests_mock.Mocker() as mock:
        mock.get(
            "https://w.test/api/v1/category",
            json={"items": [{"id": "cat-1", "name": "Biking"}]},
        )
        mock.get(
            "https://w.test/api/v1/subcategory",
            json={"items": [{"id": "sub-1", "name": "Road", "category": "cat-1"}]},
        )

        api = client()
        assert api.list_categories() == [{"id": "cat-1", "name": "Biking"}]
        assert api.list_subcategories() == [{"id": "sub-1", "name": "Road", "category": "cat-1"}]


def test_upload_file_is_multipart_with_token():
    with requests_mock.Mocker() as mock:
        mock.put("https://w.test/api/v1/trail/upload", json={"id": "trail-1"})
        file = DownloadedFile("ride.fit", b"FITDATA", "application/octet-stream")

        result = client().upload_file(file, name="Morning ride")

        assert result == {"id": "trail-1"}
        request = mock.last_request
        assert request.headers["Authorization"] == "Bearer wanderer_key_test"
        assert "ignoreDuplicates" in request.text
        assert "Morning ride" in request.text


def test_update_trail_omits_none_fields():
    with requests_mock.Mocker() as mock:
        mock.post("https://w.test/api/v1/trail/form/trail-1", json={"id": "trail-1"})

        client().update_trail(
            "trail-1",
            name="Ride",
            description=None,
            category="cat-1",
            subcategory=None,
            date="2024-05-01",
        )

        text = mock.last_request.text
        assert "name=Ride" in text
        assert "category=cat-1" in text
        assert "description" not in text
        assert "subcategory" not in text
        assert "date=2024-05-01" in text


def test_update_trail_file_sends_gpx_part():
    with requests_mock.Mocker() as mock:
        mock.post("https://w.test/api/v1/trail/form/trail-1", json={"id": "trail-1"})
        file = DownloadedFile("ride.gpx", b"<gpx></gpx>", "application/gpx+xml")

        client().update_trail_file("trail-1", file, name="Ride")

        request = mock.last_request
        assert "name" in request.text
        assert "gpx" in request.text


def test_get_trail_returns_none_on_404():
    with requests_mock.Mocker() as mock:
        mock.get("https://w.test/api/v1/trail/missing", status_code=404, json={})

        assert client().get_trail("missing") is None


def test_validate_rejects_bad_token():
    with requests_mock.Mocker() as mock:
        mock.get("https://w.test/api/v1/api-token", status_code=401, json={})

        with pytest.raises(WandererAuthError):
            client().validate()


def test_duplicate_error_exposes_existing_trail():
    with requests_mock.Mocker() as mock:
        mock.put(
            "https://w.test/api/v1/trail/upload",
            status_code=400,
            json={"message": "Duplicate trail", "id": "trail-9", "name": "Same"},
        )

        with pytest.raises(WandererDuplicateError) as exc:
            client().upload_file(DownloadedFile("ride.fit", b"data"), name="Ride")

        assert exc.value.trail_id == "trail-9"
        assert exc.value.name == "Same"


def test_retries_get_on_server_error():
    with requests_mock.Mocker() as mock:
        mock.get(
            "https://w.test/api/v1/category",
            [
                {"status_code": 500, "json": {"message": "boom"}},
                {"status_code": 200, "json": {"items": []}},
            ],
        )
        api = WandererClient(
            "https://w.test",
            "wanderer_key_test",
            retry_attempts=2,
            retry_backoff=0,
        )

        assert api.list_categories() == []
        assert mock.call_count == 2


def test_does_not_retry_upload():
    with requests_mock.Mocker() as mock:
        mock.put(
            "https://w.test/api/v1/trail/upload",
            status_code=500,
            json={"message": "boom"},
        )
        api = WandererClient(
            "https://w.test",
            "wanderer_key_test",
            retry_attempts=3,
            retry_backoff=0,
        )

        with pytest.raises(Exception, match="HTTP 500"):
            api.upload_file(DownloadedFile("ride.fit", b"data"), name="Ride")

        assert mock.call_count == 1


def test_request_exception_becomes_wanderer_error():
    class BrokenSession(requests.Session):
        def request(self, *args, **kwargs):
            raise requests.ConnectionError("offline")

    api = WandererClient("https://w.test", "wanderer_key_test", session=BrokenSession())
    with pytest.raises(Exception, match="offline"):
        api.list_categories()
