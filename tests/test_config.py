from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from garmin_to_wanderer.config import ConfigError, load_config, save_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "CONFIG_PATH",
        "STATE_DIR",
        "WANDERER_URL",
        "WANDERER_TOKEN",
        "WANDERER_TIMEOUT",
        "GARMIN_EMAIL",
        "GARMIN_PASSWORD",
        "SYNC_SINCE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_load_config(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
wanderer:
  url: https://w.test
  token: wanderer_key_config
garmin:
  email: me@example.com
state_dir: /tmp/g2w-state
retry_attempts: 5
retry_backoff: 0.5
sync:
  since: 2024-01-01
  exclude: [strength_training, indoor_cycling]
  category_map:
    road_biking: Biking/Road
    hiking: Hiking
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.wanderer_url == "https://w.test"
    assert config.wanderer_token == "wanderer_key_config"
    assert config.garmin_email == "me@example.com"
    assert config.state_dir == Path("/tmp/g2w-state")
    assert config.sync.since == date(2024, 1, 1)
    assert config.sync.exclude == ("strength_training", "indoor_cycling")
    assert config.sync.category_map["road_biking"] == ("Biking", "Road")
    assert config.sync.category_map["hiking"] == ("Hiking", None)
    assert config.retry_attempts == 5
    assert config.retry_backoff == 0.5


def test_env_overrides(tmp_path, monkeypatch):
    path = tmp_path / "config.yml"
    path.write_text(
        "wanderer:\n  url: https://config.test\nsync:\n  since: 2023-01-01\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WANDERER_URL", "https://env.test")
    monkeypatch.setenv("WANDERER_TOKEN", "wanderer_key_env")
    monkeypatch.setenv("SYNC_SINCE", "2024-06-01")

    config = load_config(path)

    assert config.wanderer_url == "https://env.test"
    assert config.wanderer_token == "wanderer_key_env"
    assert config.sync.since == date(2024, 6, 1)


def test_missing_config_raises():
    with pytest.raises(ConfigError, match="Config file not found"):
        load_config("/nonexistent/garmin-to-wanderer/config.yml")


def test_invalid_category_map(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("sync:\n  category_map:\n    hiking: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="needs a category name"):
        load_config(path)


def test_save_config_creates_private_file_and_merges(tmp_path):
    path = tmp_path / "nested" / "config.yml"
    saved = save_config(path, {"wanderer": {"url": "https://w.test"}})
    save_config(path, {"garmin": {"email": "me@example.com"}})

    assert saved == path
    assert path.stat().st_mode & 0o777 == 0o600
    text = path.read_text(encoding="utf-8")
    assert "url: https://w.test" in text
    assert "email: me@example.com" in text
    assert path.stat().st_size > 0
