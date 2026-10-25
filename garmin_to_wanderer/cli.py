from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import typer

from garmin_to_wanderer.config import (
    Config,
    ConfigError,
    ensure_state_dir,
    load_config,
    save_config,
)
from garmin_to_wanderer.mapping import WandererTaxonomy
from garmin_to_wanderer.sources import (
    GarminAuthError,
    GarminConnectSource,
    GarminSourceError,
)
from garmin_to_wanderer.state import StateStore
from garmin_to_wanderer.sync import SyncOptions, SyncRunner
from garmin_to_wanderer.wanderer import (
    WandererAuthError,
    WandererClient,
    WandererError,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Synchronise Garmin Connect activities to Wanderer.",
)
setup_app = typer.Typer(no_args_is_help=True, help="Configure Garmin and Wanderer.")
app.add_typer(setup_app, name="setup")

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="Path to config.yml."),
]


@setup_app.command("garmin")
def setup_garmin(
    email: Annotated[str | None, typer.Option("--email", help="Garmin account email.")] = None,
    password: Annotated[
        str | None,
        typer.Option("--password", help="Garmin password (not stored).", hide_input=True),
    ] = None,
    config_path: ConfigOption = None,
) -> None:
    """Log in to Garmin and cache the session tokens."""
    try:
        config = load_config(config_path, require_file=False)
        email = email or config.garmin_email or os.environ.get("GARMIN_EMAIL")
        if not email:
            email = typer.prompt("Garmin email")
        password = password or os.environ.get("GARMIN_PASSWORD")
        if not password:
            password = typer.prompt("Garmin password", hide_input=True)

        from garminconnect import Garmin

        tokenstore = config.garmin_tokenstore
        tokenstore.mkdir(parents=True, exist_ok=True)
        client = Garmin(
            email,
            password,
            prompt_mfa=lambda: typer.prompt("MFA code"),
        )
        client.login(str(tokenstore))
        path = save_config(config_path, {"garmin": {"email": email}})
        typer.echo(f"Garmin login OK. Tokens cached in {tokenstore}.")
        typer.echo(f"Config written to {path}.")
    except ConfigError as exc:
        _fail(str(exc), 2)
    except Exception as exc:
        _fail(f"Garmin setup failed: {exc}", 2)


@setup_app.command("wanderer")
def setup_wanderer(
    url: Annotated[str | None, typer.Option("--url", help="Wanderer base URL.")] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help="Wanderer API token (wanderer_key_...).",
            hide_input=True,
        ),
    ] = None,
    store_token: Annotated[
        bool,
        typer.Option(
            "--store-token",
            help="Write the token to config.yml (mode 0600) instead of using the env.",
        ),
    ] = False,
    config_path: ConfigOption = None,
) -> None:
    """Validate and store the Wanderer connection details."""
    try:
        config = load_config(config_path, require_file=False)
        base_url = url or config.wanderer_url or os.environ.get("WANDERER_URL")
        if not base_url:
            base_url = typer.prompt("Wanderer URL")

        token_value = token or config.wanderer_token or os.environ.get("WANDERER_TOKEN")
        if not token_value:
            token_value = typer.prompt("Wanderer API token", hide_input=True)

        client = WandererClient(
            base_url,
            token_value,
            timeout=config.timeout,
            retry_attempts=config.retry_attempts,
            retry_backoff=config.retry_backoff,
        )
        client.validate()

        updates: dict[str, dict[str, str]] = {"wanderer": {"url": base_url.rstrip("/")}}
        if store_token:
            updates["wanderer"]["token"] = token_value

        path = save_config(config_path, updates)
        typer.echo(f"Wanderer token OK. Config written to {path}.")
        if not store_token:
            typer.echo("Export WANDERER_TOKEN for sync, or re-run with --store-token.")
    except ConfigError as exc:
        _fail(str(exc), 2)
    except WandererAuthError as exc:
        _fail(str(exc), 2)
    except WandererError as exc:
        _fail(str(exc), 3)


@app.command()
def sync(
    since: Annotated[
        str | None,
        typer.Option("--since", help="Start date (YYYY-MM-DD), inclusive."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="End date (YYYY-MM-DD), inclusive. Default: today."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would happen without writing."),
    ] = False,
    report_path: Annotated[
        Path | None,
        typer.Option("--report", help="Write a JSON report to this path."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-import or refresh activities already in state."),
    ] = False,
    rebuild_state: Annotated[
        bool,
        typer.Option("--rebuild-state", help="Clear the local mapping before syncing."),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Show every activity in the report.")
    ] = False,
    config_path: ConfigOption = None,
) -> None:
    """Import Garmin activities into Wanderer."""
    try:
        config = load_config(config_path)
        wanderer_url, wanderer_token = config.require_wanderer()
    except ConfigError as exc:
        _fail(str(exc), 2)

    if not config.garmin_tokenstore.is_dir():
        _fail("Garmin token store not found. Run `setup garmin` first.", 2)

    ensure_state_dir(config)
    state = StateStore(config.state_db)
    try:
        if rebuild_state:
            if dry_run:
                typer.echo("--rebuild-state ignored during --dry-run.", err=True)
            else:
                state.reset()

        since_date = _resolve_since(since, config, state)
        until_date = _parse_date(until, "--until") if until else date.today()
        if until_date < since_date:
            _fail("--until must be on or after --since.", 2)

        wanderer = WandererClient(
            wanderer_url,
            wanderer_token,
            timeout=config.timeout,
            retry_attempts=config.retry_attempts,
            retry_backoff=config.retry_backoff,
        )
        taxonomy = WandererTaxonomy.from_api(
            wanderer.list_categories(),
            wanderer.list_subcategories(),
        )
        source = GarminConnectSource(
            config.garmin_tokenstore,
            retry_attempts=config.retry_attempts,
            retry_backoff=config.retry_backoff,
        )
        runner = SyncRunner(
            source=source,
            wanderer=wanderer,
            state=state,
            taxonomy=taxonomy,
            config=config,
        )
        report = runner.run(
            SyncOptions(
                since=since_date,
                until=until_date,
                dry_run=dry_run,
                force=force,
            )
        )
    except ConfigError as exc:
        _fail(str(exc), 2)
    except (WandererAuthError, GarminAuthError) as exc:
        _fail(str(exc), 2)
    except (WandererError, GarminSourceError) as exc:
        _fail(str(exc), 3)
    finally:
        state.close()

    report.print_human(verbose=verbose)
    if report_path is not None:
        report.write_json(report_path)
        typer.echo(f"Report written to {report_path}.")
    if report.has_failures():
        raise typer.Exit(1)


@app.command()
def status(config_path: ConfigOption = None) -> None:
    """Show configuration and local sync state without contacting either service."""
    try:
        config = load_config(config_path, require_file=False)
    except ConfigError as exc:
        _fail(str(exc), 2)

    typer.echo(f"Config: {config.path} ({'found' if config.path.is_file() else 'missing'})")
    typer.echo(f"Wanderer: {config.wanderer_url or '(not configured)'}")
    typer.echo(f"Wanderer token: {'set' if config.wanderer_token else 'missing'}")
    typer.echo(
        f"Garmin token store: {config.garmin_tokenstore} "
        f"({'found' if config.garmin_tokenstore.is_dir() else 'missing'})"
    )
    typer.echo(
        f"State DB: {config.state_db} ({'found' if config.state_db.is_file() else 'missing'})"
    )
    if config.sync.since is not None:
        typer.echo(f"Configured since: {config.sync.since}")

    if config.state_db.is_file():
        with StateStore(config.state_db) as state:
            cursor = state.last_imported_start()
            typer.echo(f"Last imported: {cursor.isoformat() if cursor is not None else '(none)'}")
            counts = state.counts()
            if counts:
                typer.echo("Stored activities:")
                for stored_status, count in sorted(counts.items()):
                    typer.echo(f"  {stored_status}: {count}")


def _resolve_since(value: str | None, config: Config, state: StateStore) -> date:
    if value:
        return _parse_date(value, "--since")

    cursor = state.last_imported_start()
    if cursor is not None:
        return cursor.date() - timedelta(days=2)

    if config.sync.since is not None:
        return config.sync.since

    raise ConfigError(
        "No --since, no previous sync, and sync.since is unset. "
        "Pass --since or set sync.since in config.yml."
    )


def _parse_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"{option_name} must be YYYY-MM-DD, got {value!r}") from exc


def _fail(message: str, code: int) -> None:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)
