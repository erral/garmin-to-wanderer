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
    for name in (
        "CONFIG_PATH",
        "STATE_DIR",
        "WANDERER_URL",
        "WANDERER_TOKEN",
        "SYNC_SINCE",
        "RECOVERY_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)


def write_config(tmp_path: Path, *, recovery_limit: int | None = None) -> Path:
    path = tmp_path / "config.yml"
    limit_line = "" if recovery_limit is None else f"  recovery_limit: {recovery_limit}\n"
    path.write_text(
        f"""
wanderer:
  url: https://w.test
  token: wanderer_key_test
state_dir: {tmp_path / "state"}
sync:
  since: 2024-05-01
{limit_line}""",
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
        state.advance_watermark(datetime(2024, 5, 1, 10, 0))

    result = CliRunner().invoke(cli.app, ["status", "--config", str(path)])

    assert result.exit_code == 0
    assert "imported: 1" in result.output
    assert "Last seen: 2024-05-01T10:00:00" in result.output
    assert "Unresolved failures: failed 0, partial 0" in result.output


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
        state.advance_watermark(datetime(2024, 5, 10, 10, 0))

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
    assert "- uploaded" in result.stdout
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
    assert payload["entries"][0]["type_key"] == "road_biking"
    assert payload["entries"][0]["has_description"] is True


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


def test_quiet_final_report_suppresses_report_path_confirmation(tmp_path, monkeypatch):
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
            "--final-report",
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 0
    assert "imported: 1" in result.stdout
    assert str(report_path) not in result.stdout
    assert report_path.is_file()


def test_sync_final_report_without_quiet_keeps_live_lines(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setattr(cli, "WandererClient", FakeWanderer)
    monkeypatch.setattr(cli, "GarminConnectSource", FakeSource)

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01", "--final-report"],
    )

    assert result.exit_code == 0
    assert "[imported]" in result.stdout
    assert "Garmin -> Wanderer" in result.stdout
    assert "imported: 1" in result.stdout


def state_activity(garmin_id: str, started_at: datetime, *, type_key: str = "hiking"):
    return GarminActivity(
        garmin_id=garmin_id,
        name=f"Activity {garmin_id}",
        start_time=started_at,
        type_key=type_key,
    )


def seed_state(tmp_path: Path, rows) -> None:
    with StateStore(tmp_path / "state" / "state.db") as state:
        for activity, status, trail_id in rows:
            state.upsert(activity, status=status, wanderer_trail_id=trail_id)


class ScriptedSource:
    def __init__(self, activities=None):
        self.activities = list(activities or [])
        self.calls = []
        self.downloads = []

    def iter_activities(self, since, until):
        self.calls.append((since, until))
        return list(self.activities)

    def download_original(self, garmin_id):
        self.downloads.append(garmin_id)
        return DownloadedFile(f"{garmin_id}.fit", b"FITDATA")


class RecordingWanderer(FakeWanderer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uploaded = []
        self.updated = []
        self.refreshed = []
        self.get_calls = []

    def get_trail(self, trail_id):
        self.get_calls.append(trail_id)
        return {"id": trail_id}

    def upload_file(self, file, *, name):
        trail_id = f"trail-{len(self.uploaded) + 1}"
        self.uploaded.append((file, name))
        return {"id": trail_id}

    def update_trail(self, trail_id, **fields):
        self.updated.append((trail_id, fields))
        return {"id": trail_id}

    def update_trail_file(self, trail_id, file, **fields):
        self.refreshed.append((trail_id, file, fields))
        return {"id": trail_id}


class FailingUploadWanderer(RecordingWanderer):
    def upload_file(self, file, *, name):
        raise RuntimeError("upload boom")


def patch_source(monkeypatch, source):
    monkeypatch.setattr(cli, "GarminConnectSource", lambda *args, **kwargs: source)


def patch_wanderer(monkeypatch, wanderer):
    monkeypatch.setattr(cli, "WandererClient", lambda *args, **kwargs: wanderer)


def test_explicit_window_scopes_recovery_and_reports_deferred(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    seed_state(
        tmp_path,
        [
            (state_activity("old", datetime(2024, 1, 1, 9, 0)), "failed", None),
            (state_activity("recent", datetime(2024, 5, 10, 9, 0)), "failed", None),
        ],
    )
    source = ScriptedSource([])
    patch_source(monkeypatch, source)
    patch_wanderer(monkeypatch, RecordingWanderer())
    report_path = tmp_path / "report.json"

    result = CliRunner().invoke(
        cli.app,
        [
            "sync",
            "--config",
            str(path),
            "--since",
            "2024-05-01",
            "--until",
            "2024-05-31",
            "--verbose",
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 0
    assert source.downloads == ["recent"]
    assert "Retrying 0 partial and 1 failed activities" in result.output
    assert "deferred failures: 1" in result.output
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["deferred_failures"] == 1
    with StateStore(tmp_path / "state" / "state.db") as state:
        assert state.get("old").status == "failed"


def test_quiet_reports_deferred_failures_on_stderr(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    seed_state(
        tmp_path,
        [(state_activity("old", datetime(2024, 1, 1, 9, 0)), "failed", None)],
    )
    patch_source(monkeypatch, ScriptedSource([]))
    patch_wanderer(monkeypatch, RecordingWanderer())

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01", "--quiet"],
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert "deferred failures: 1" in result.stderr


def test_default_run_continues_from_watermark_after_total_failure(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    sources: list[ScriptedSource] = []
    activity_sets = [[state_activity("a", datetime(2024, 5, 10, 9, 0))], []]

    def make_source(*args, **kwargs):
        source = ScriptedSource(activity_sets.pop(0)) if activity_sets else ScriptedSource([])
        sources.append(source)
        return source

    monkeypatch.setattr(cli, "GarminConnectSource", make_source)
    monkeypatch.setattr(cli, "WandererClient", FailingUploadWanderer)

    first = CliRunner().invoke(cli.app, ["sync", "--config", str(path)])
    assert first.exit_code == 1

    patch_wanderer(monkeypatch, RecordingWanderer())
    second = CliRunner().invoke(cli.app, ["sync", "--config", str(path)])

    assert second.exit_code == 0
    assert sources[1].calls == [(date(2024, 5, 8), date.today())]


def test_explicit_window_does_not_advance_watermark(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    patch_source(monkeypatch, ScriptedSource([state_activity("a", datetime(2024, 5, 10, 9, 0))]))
    patch_wanderer(monkeypatch, RecordingWanderer())

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01", "--until", "2024-05-31"],
    )

    assert result.exit_code == 0
    with StateStore(tmp_path / "state" / "state.db") as state:
        assert state.last_seen_started_at() is None


def test_dry_run_does_not_advance_watermark(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    patch_source(monkeypatch, ScriptedSource([state_activity("a", datetime(2024, 5, 10, 9, 0))]))
    patch_wanderer(monkeypatch, RecordingWanderer())

    result = CliRunner().invoke(cli.app, ["sync", "--config", str(path), "--dry-run"])

    assert result.exit_code == 0
    with StateStore(tmp_path / "state" / "state.db") as state:
        assert state.last_seen_started_at() is None


def test_recovery_limit_caps_oldest_and_reports_deferred(tmp_path, monkeypatch):
    path = write_config(tmp_path, recovery_limit=2)
    seed_state(
        tmp_path,
        [
            (state_activity("f1", datetime(2024, 1, 1, 9, 0)), "failed", None),
            (state_activity("f2", datetime(2024, 2, 1, 9, 0)), "failed", None),
            (state_activity("f3", datetime(2024, 3, 1, 9, 0)), "failed", None),
        ],
    )
    source = ScriptedSource([])
    patch_source(monkeypatch, source)
    patch_wanderer(monkeypatch, RecordingWanderer())
    report_path = tmp_path / "report.json"

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--verbose", "--report", str(report_path)],
    )

    assert result.exit_code == 0
    assert source.downloads == ["f1", "f2"]
    assert "Retrying 2 of 3 unresolved failures" in result.output
    assert "limit reached, 1 deferred" in result.output
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["deferred_failures"] == 1


def test_force_escalates_partial_to_full_refresh(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    seed_state(
        tmp_path,
        [(state_activity("p1", datetime(2024, 5, 10, 9, 0)), "partial", "trail-9")],
    )
    source = ScriptedSource([])
    wanderer = RecordingWanderer()
    patch_source(monkeypatch, source)
    patch_wanderer(monkeypatch, wanderer)

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01", "--force"],
    )

    assert result.exit_code == 0
    assert source.downloads == ["p1"]
    assert wanderer.refreshed[0][0] == "trail-9"


def test_recovery_rechecks_exclude_and_retires_the_row(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    data = path.read_text(encoding="utf-8").replace(
        "  since: 2024-05-01\n",
        "  since: 2024-05-01\n  exclude: [strength_training]\n",
    )
    path.write_text(data, encoding="utf-8")
    seed_state(
        tmp_path,
        [
            (
                state_activity("s1", datetime(2024, 5, 10, 9, 0), type_key="strength_training"),
                "failed",
                None,
            )
        ],
    )
    source = ScriptedSource([])
    patch_source(monkeypatch, source)
    patch_wanderer(monkeypatch, RecordingWanderer())

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01"],
    )

    assert result.exit_code == 0
    assert source.downloads == []
    with StateStore(tmp_path / "state" / "state.db") as state:
        assert state.get("s1").status == "skipped_excluded"


def test_status_shows_unresolved_failures(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    seed_state(
        tmp_path,
        [(state_activity("f1", datetime(2024, 5, 1, 9, 0)), "failed", None)],
    )

    result = CliRunner().invoke(cli.app, ["status", "--config", str(path)])

    assert result.exit_code == 0
    assert "Unresolved failures: failed 1, partial 0" in result.output


def test_default_run_sweeps_all_unresolved_failures(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    seed_state(
        tmp_path,
        [(state_activity("old", datetime(2024, 1, 1, 9, 0)), "failed", None)],
    )
    source = ScriptedSource([])
    patch_source(monkeypatch, source)
    patch_wanderer(monkeypatch, RecordingWanderer())

    result = CliRunner().invoke(cli.app, ["sync", "--config", str(path)])

    assert result.exit_code == 0
    assert source.downloads == ["old"]
    assert "deferred failures" not in result.output


def test_recovery_and_listing_do_not_process_the_same_activity_twice(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    duplicate = state_activity("dup", datetime(2024, 5, 10, 9, 0))
    seed_state(tmp_path, [(duplicate, "failed", None)])
    source = ScriptedSource([duplicate])
    wanderer = RecordingWanderer()
    patch_source(monkeypatch, source)
    patch_wanderer(monkeypatch, wanderer)

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01"],
    )

    assert result.exit_code == 0
    assert source.downloads == ["dup"]
    assert len(wanderer.uploaded) == 1


def test_dry_run_does_not_mutate_partial_without_trail_id(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    seed_state(
        tmp_path,
        [(state_activity("p1", datetime(2024, 5, 10, 9, 0)), "partial", None)],
    )
    patch_source(monkeypatch, ScriptedSource([]))
    patch_wanderer(monkeypatch, RecordingWanderer())

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01", "--dry-run"],
    )

    assert result.exit_code == 1
    with StateStore(tmp_path / "state" / "state.db") as state:
        assert state.get("p1").status == "partial"


def test_recovery_limit_is_not_bypassed_by_the_listing(tmp_path, monkeypatch):
    path = write_config(tmp_path, recovery_limit=1)
    older = state_activity("a", datetime(2024, 5, 1, 9, 0))
    newer = state_activity("b", datetime(2024, 5, 20, 9, 0))
    seed_state(tmp_path, [(newer, "failed", None), (older, "failed", None)])
    source = ScriptedSource([older, newer])
    patch_source(monkeypatch, source)
    patch_wanderer(monkeypatch, RecordingWanderer())

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01", "--until", "2024-05-31"],
    )

    assert result.exit_code == 0
    assert source.downloads == ["a"]
    assert "deferred failures: 1" in result.output
    with StateStore(tmp_path / "state" / "state.db") as state:
        assert state.get("b").status == "failed"


def test_recovery_limit_zero_does_not_retry_via_listing(tmp_path, monkeypatch):
    path = write_config(tmp_path, recovery_limit=0)
    failed = state_activity("a", datetime(2024, 5, 1, 9, 0))
    seed_state(tmp_path, [(failed, "failed", None)])
    source = ScriptedSource([failed])
    patch_source(monkeypatch, source)
    patch_wanderer(monkeypatch, RecordingWanderer())

    result = CliRunner().invoke(
        cli.app,
        ["sync", "--config", str(path), "--since", "2024-05-01"],
    )

    assert result.exit_code == 0
    assert source.downloads == []
    assert "deferred failures: 1" in result.output
    with StateStore(tmp_path / "state" / "state.db") as state:
        assert state.get("a").status == "failed"
