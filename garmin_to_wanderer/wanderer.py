from __future__ import annotations

import contextlib
import time
from typing import Any

import requests

from garmin_to_wanderer.models import DownloadedFile

_RETRY_STATUSES = {429, 500, 502, 503, 504}


class WandererError(Exception):
    """Base error for Wanderer API failures."""


class WandererAuthError(WandererError):
    """Raised when the Wanderer token is missing, invalid, or rejected."""


class WandererNotFound(WandererError):
    """Raised when a Wanderer record does not exist."""


class WandererDuplicateError(WandererError):
    """Raised when Wanderer refuses an upload as a duplicate."""

    def __init__(self, message: str, *, trail_id: str | None = None, name: str | None = None):
        super().__init__(message)
        self.trail_id = trail_id
        self.name = name


class WandererClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        retry_attempts: int = 3,
        retry_backoff: float = 1.0,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_backoff = retry_backoff
        self.session = session or requests.Session()

    def validate(self) -> None:
        # The category list is public, so it cannot prove that a token works.
        # Listing API tokens requires an authenticated user.
        self._request("GET", "/api/v1/api-token", params={"perPage": 1})

    def list_categories(self) -> list[dict[str, Any]]:
        return _items(self._request("GET", "/api/v1/category", params={"perPage": -1}).json())

    def list_subcategories(self) -> list[dict[str, Any]]:
        return _items(self._request("GET", "/api/v1/subcategory", params={"perPage": -1}).json())

    def get_trail(self, trail_id: str) -> dict[str, Any] | None:
        try:
            return self._request("GET", f"/api/v1/trail/{trail_id}").json()
        except WandererNotFound:
            return None

    def upload_file(self, file: DownloadedFile, *, name: str) -> dict[str, Any]:
        response = self._request(
            "PUT",
            "/api/v1/trail/upload",
            files={"file": (file.filename, file.content, file.content_type)},
            data={"name": name, "ignoreDuplicates": "true"},
        )
        return response.json()

    def update_trail(self, trail_id: str, **fields: Any) -> dict[str, Any]:
        data = {key: str(value) for key, value in fields.items() if value is not None}
        response = self._request("POST", f"/api/v1/trail/form/{trail_id}", data=data)
        return response.json()

    def update_trail_file(
        self, trail_id: str, file: DownloadedFile, **fields: Any
    ) -> dict[str, Any]:
        data = {key: str(value) for key, value in fields.items() if value is not None}
        response = self._request(
            "POST",
            f"/api/v1/trail/form/{trail_id}",
            files={"gpx": (file.filename, file.content, file.content_type)},
            data=data,
        )
        return response.json()

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"}

        # GETs and the metadata form update are idempotent. The upload is not,
        # so it is deliberately attempted only once.
        retryable = method in ("GET", "POST")
        attempts = self.retry_attempts if retryable else 1
        response: requests.Response | None = None

        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method, url, headers=headers, timeout=self.timeout, **kwargs
                )
            except requests.RequestException as exc:
                if attempt == attempts - 1:
                    raise WandererError(f"Wanderer request failed: {exc}") from exc
                self._sleep(attempt, None)
                continue

            if response.status_code in _RETRY_STATUSES and attempt < attempts - 1:
                self._sleep(attempt, response)
                continue
            break

        if response is None:
            raise WandererError("Wanderer request failed without a response")

        if response.status_code in (401, 403):
            raise WandererAuthError(
                f"Wanderer rejected the API token (HTTP {response.status_code})"
            )
        if response.status_code == 404:
            raise WandererNotFound(f"Wanderer record not found: {path}")
        if response.status_code >= 400:
            body = response.text.strip()
            if "Duplicate trail" in body:
                payload = _safe_json(response)
                raise WandererDuplicateError(
                    "Wanderer reported a duplicate trail",
                    trail_id=str(payload.get("id", "")) or None,
                    name=payload.get("name"),
                )
            raise WandererError(f"Wanderer returned HTTP {response.status_code}: {body}")
        return response

    def _sleep(self, attempt: int, response: requests.Response | None) -> None:
        if self.retry_backoff <= 0:
            return
        delay = self.retry_backoff * (2**attempt)
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                with contextlib.suppress(ValueError):
                    delay = max(delay, float(retry_after))
        time.sleep(delay)


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return items
    raise WandererError("Unexpected Wanderer list response")


def _safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
