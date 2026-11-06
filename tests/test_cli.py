from __future__ import annotations

import json
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


def test_version_option():
    result = CliRunner().invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert "garmin-to-wanderer" in result.output


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
                description="Nice ride",
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


def test_sync_prints_live_outcome_and_minimal_summary(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setattr(cli, "WandererClient", FakeWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", FakeSource)

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01"],
    )

    assert result.exit_code == 0
    assert "Ride" in result.stdout
    assert "[imported]" in result.stdout
    assert "imported: 1" in result.stdout
    assert "Elapsed:" in result.stdout
    assert "Downloading" not in result.stdout
    assert "type=road_biking" not in result.stdout


def test_sync_quiet_suppresses_success_output(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setattr(cli, "WandererClient", FakeWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", FakeSource)

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01", "--quiet"],
    )

    assert result.exit_code == 0
    assert result.stdout == ""


class FailingWanderer(FakeWanderer):
    def update_trail(self, trail_id, **fields):
        raise RuntimeError("metadata boom")


def test_sync_quiet_prints_failures_to_stderr(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setattr(cli, "WandererClient", FailingWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", FakeSource)

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01", "--quiet"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "metadata boom" in result.stderr


def test_sync_quiet_with_final_report_prints_only_final_report(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setattr(cli, "WandererClient", FakeWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", FakeSource)

    result = CliRunner().invoke(
        cli.app,
        [
            "sync",
            "--config",
            str(path),
            "--since",
            "2024-05-01",
            "--quiet",
            "--final-report",
        ],
    )

    assert result.exit_code == 0
    assert "imported: 1" in result.stdout
    assert "[imported]" in result.stdout
    assert "Elapsed:" in result.stdout


def test_sync_rejects_quiet_and_verbose_before_loading_config(tmp_path):
    result = CliRunner().invoke(
        cli.app,
        [
            "sync",
            "--config",
            str(tmp_path / "missing.yml"),
            "--quiet",
            "--verbose",
            "--since",
            "2024-05-01",
        ],
    )

    assert result.exit_code == 2
    assert "--quiet and --verbose cannot be used together" in result.stderr
    assert "Config file not found" not in result.stderr


def test_sync_verbose_adds_details_and_phase_lines(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setattr(cli, "WandererClient", FakeWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", FakeSource)

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01", "--verbose"],
    )

    assert result.exit_code == 0
    assert "type=road_biking" in result.stdout
    assert "trail=trail-1" in result.stdout
    assert "description=yes" in result.stdout
    assert "Downloading 1" in result.stdout
    assert "Uploading Ride" in result.stdout
    assert "Updating metadata for Ride" in result.stdout


def test_sync_writes_report_file_in_default_mode(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    report_path = tmp_path / "nested" / "report.json"
    monkeypatch.setattr(cli, "WandererClient", FakeWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", FakeSource)

    result = CliRunner().invoke(
        cli.app,
        [
            "sync",
            "--config",
            str(path),
            "--since",
            "2024-05-01",
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 0
    assert f"Report written to {report_path}" in result.stdout
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["counts"] == {"imported": 1}
    assert payload["entries"][0]["status"] == "imported"
    assert "type_key" not in payload["entries"][0]


def test_sync_writes_report_file_in_quiet_mode_without_confirmation(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(cli, "WandererClient", FakeWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", FakeSource)

    result = CliRunner().invoke(
        cli.app,
        [
            "sync",
            "--config",
            str(path),
            "--since",
            "2024-05-01",
            "--quiet",
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert report_path.is_file()
