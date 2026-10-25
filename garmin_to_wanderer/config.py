from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "garmin-to-wanderer" / "config.yml"
DEFAULT_STATE_DIR = Path.home() / ".local" / "share" / "garmin-to-wanderer"


class ConfigError(Exception):
    """Raised when the configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class SyncSettings:
    since: date | None = None
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    default_category: str | None = "Other"
    category_map: dict[str, tuple[str, str | None]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Config:
    path: Path
    wanderer_url: str | None
    wanderer_token: str | None
    garmin_email: str | None
    state_dir: Path
    sync: SyncSettings
    timeout: float = 30.0
    retry_attempts: int = 3
    retry_backoff: float = 1.0

    @property
    def state_db(self) -> Path:
        return self.state_dir / "state.db"

    @property
    def garmin_tokenstore(self) -> Path:
        return self.state_dir / "garmintoken"

    def require_wanderer(self) -> tuple[str, str]:
        if not self.wanderer_url:
            raise ConfigError("wanderer.url is missing. Run `garmin-to-wanderer setup wanderer`.")
        if not self.wanderer_token:
            raise ConfigError(
                "WANDERER_TOKEN is missing. Export it or run `garmin-to-wanderer setup wanderer`."
            )
        return self.wanderer_url, self.wanderer_token


def resolve_config_path(path: str | Path | None = None) -> Path:
    raw = path or os.environ.get("CONFIG_PATH") or DEFAULT_CONFIG_PATH
    return Path(os.path.expandvars(os.path.expanduser(str(raw))))


def load_config(path: str | Path | None = None, *, require_file: bool = True) -> Config:
    config_path = resolve_config_path(path)
    data: dict[str, Any] = {}

    if config_path.is_file():
        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"Config root must be a mapping: {config_path}")
        data = loaded
    elif require_file:
        raise ConfigError(
            f"Config file not found: {config_path}. Run `garmin-to-wanderer setup wanderer` first."
        )

    wanderer = data.get("wanderer") or {}
    garmin = data.get("garmin") or {}
    sync = data.get("sync") or {}
    for section_name, section in (
        ("wanderer", wanderer),
        ("garmin", garmin),
        ("sync", sync),
    ):
        if not isinstance(section, dict):
            raise ConfigError(f"`{section_name}` must be a mapping in {config_path}")

    state_dir = _as_path(
        os.environ.get("STATE_DIR") or data.get("state_dir"),
        DEFAULT_STATE_DIR,
    )
    sync_settings = SyncSettings(
        since=_as_date(os.environ.get("SYNC_SINCE") or sync.get("since"), "sync.since"),
        include=_as_tuple(sync.get("include")),
        exclude=_as_tuple(sync.get("exclude")),
        default_category=sync.get("default_category", "Other"),
        category_map=_as_category_map(sync.get("category_map")),
    )

    retry_attempts = int(os.environ.get("RETRY_ATTEMPTS") or data.get("retry_attempts") or 3)
    retry_backoff = float(os.environ.get("RETRY_BACKOFF") or data.get("retry_backoff") or 1.0)
    if retry_attempts < 1:
        raise ConfigError("`retry_attempts` must be at least 1")
    if retry_backoff < 0:
        raise ConfigError("`retry_backoff` cannot be negative")

    return Config(
        path=config_path,
        wanderer_url=os.environ.get("WANDERER_URL") or wanderer.get("url"),
        wanderer_token=os.environ.get("WANDERER_TOKEN") or wanderer.get("token"),
        garmin_email=os.environ.get("GARMIN_EMAIL") or garmin.get("email"),
        state_dir=state_dir,
        sync=sync_settings,
        timeout=float(os.environ.get("WANDERER_TIMEOUT") or data.get("timeout") or 30),
        retry_attempts=retry_attempts,
        retry_backoff=retry_backoff,
    )


def save_config(path: str | Path | None, updates: dict[str, Any]) -> Path:
    config_path = resolve_config_path(path)
    data: dict[str, Any] = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"Config root must be a mapping: {config_path}")
        data = loaded

    _deep_merge(data, updates)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(config_path.parent, 0o700)
    config_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    os.chmod(config_path, 0o600)
    return config_path


def ensure_state_dir(config: Config) -> Path:
    config.state_dir.mkdir(parents=True, exist_ok=True)
    return config.state_dir


def _as_path(value: Any, default: Path) -> Path:
    raw = value or default
    return Path(os.path.expandvars(os.path.expanduser(str(raw))))


def _as_date(value: Any, field_name: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigError(f"`{field_name}` must be YYYY-MM-DD, got {value!r}") from exc


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return tuple(str(item).strip() for item in value if str(item).strip())


def _as_category_map(value: Any) -> dict[str, tuple[str, str | None]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("`sync.category_map` must be a mapping")
    result: dict[str, tuple[str, str | None]] = {}
    for key, target in value.items():
        result[str(key).strip().lower()] = _parse_category_target(target)
    return result


def _parse_category_target(value: Any) -> tuple[str, str | None]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split("/", 1)]
    elif isinstance(value, (list, tuple)):
        parts = [str(part).strip() for part in value]
    elif isinstance(value, dict):
        parts = [
            str(value.get("category", "")).strip(),
            str(value.get("subcategory", "")).strip(),
        ]
    else:
        raise ConfigError(f"Invalid category mapping target: {value!r}")

    if not parts or not parts[0]:
        raise ConfigError(f"Category mapping needs a category name: {value!r}")
    subcategory = parts[1] if len(parts) > 1 and parts[1] else None
    return parts[0], subcategory


def _deep_merge(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
