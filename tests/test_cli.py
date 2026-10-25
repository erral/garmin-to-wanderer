from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import garmin_to_wanderer.cli as cli
from garmin_to_wanderer.models import DownloadedFile, GarminActivity
from garmin_to_wanderer.state import StateStore


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("CONFIG_PATH", "STATE_DIR", "WANDERER_URL", "WANDERER_TOKEN", "SYNC_SINCE"):
        monkeypatch.delenv(name, raising=False)


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(
        f"""
wanderer:
  url: https://w.test
  token: wanderer_key_test
state_dir: {tmp_path / "state"}
sync:
  since: 2024-05-01
""",
        encoding="utf-8",
    )
    (tmp_path / "state" / "garmintoken").mkdir(parents=True)
    return path


def test_status_without_config(tmp_path):
    result = CliRunner().invoke(cli.app, ["status", "--config", str(tmp_path / "missing.yml")])

    assert result.exit_code == 0
    assert "Config:" in result.output
    assert "missing" in result.output


def test_sync_requires_config(tmp_path):
    result = CliRunner().invoke(cli.app, ["sync", "--config", str(tmp_path / "missing.yml")])

    assert result.exit_code == 2
    assert "Config file not found" in result.output


def test_sync_requires_since_when_state_is_empty(tmp_path):
    path = write_config(tmp_path)
    data = path.read_text(encoding="utf-8").replace("  since: 2024-05-01\n", "")
    path.write_text(data, encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["sync", "--config", str(path)])

    assert result.exit_code == 2
    assert "No --since" in result.output


def test_status_reports_state(tmp_path):
    path = write_config(tmp_path)
    with StateStore(tmp_path / "state" / "state.db") as state:
        state.upsert(
            GarminActivity(
                garmin_id="1",
                name="Ride",
                start_time=datetime(2024, 5, 1, 10, 0),
                type_key="road_biking",
            ),
            status="imported",
            wanderer_trail_id="trail-1",
        )

    result = CliRunner().invoke(cli.app, ["status", "--config", str(path)])

    assert result.exit_code == 0
    assert "imported: 1" in result.output
    assert "Last imported: 2024-05-01T10:00:00" in result.output


class FakeWanderer:
    def __init__(self, *args, **kwargs):
        pass

    def list_categories(self):
        return [{"id": "cat-biking", "name": "Biking"}, {"id": "cat-other", "name": "Other"}]

    def list_subcategories(self):
        return [{"id": "sub-road", "name": "Road", "category": "cat-biking"}]

    def get_trail(self, trail_id):
        return {"id": trail_id}

    def upload_file(self, file, *, name):
        return {"id": "trail-1"}

    def update_trail(self, trail_id, **fields):
        return {"id": trail_id}


class FakeSource:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def iter_activities(self, since, until):
        self.calls.append((since, until))
        return [
            GarminActivity(
                garmin_id="1",
                name="Ride",
                start_time=datetime(2024, 5, 1, 10, 0),
                type_key="road_biking",
                parent_type_id=2,
                has_gps=True,
            )
        ]

    def download_original(self, garmin_id):
        return DownloadedFile(f"{garmin_id}.fit", b"FITDATA")


def test_sync_dry_run_end_to_end(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setattr(cli, "WandererClient", FakeWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", FakeSource)

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--dry-run", "--since", "2024-05-01"],
    )

    assert result.exit_code == 0
    assert "would_import: 1" in result.output


def test_incremental_sync_starts_two_days_before_cursor(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    data = path.read_text(encoding="utf-8").replace("  since: 2024-05-01\n", "")
    path.write_text(data, encoding="utf-8")

    with StateStore(tmp_path / "state" / "state.db") as state:
        state.upsert(
            GarminActivity(
                garmin_id="old",
                name="Old ride",
                start_time=datetime(2024, 5, 10, 10, 0),
                type_key="road_biking",
            ),
            status="imported",
            wanderer_trail_id="trail-old",
        )

    sources: list[FakeSource] = []

    def make_source(*args, **kwargs):
        source = FakeSource(*args, **kwargs)
        sources.append(source)
        return source

    monkeypatch.setattr(cli, "WandererClient", FakeWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", make_source)

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--until", "2024-05-31", "--dry-run"],
    )

    assert result.exit_code == 0
    assert sources[0].calls == [(date(2024, 5, 8), date(2024, 5, 31))]
