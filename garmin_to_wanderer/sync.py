from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from garmin_to_wanderer.config import Config
from garmin_to_wanderer.mapping import WandererTaxonomy, base_type_key, resolve_category
from garmin_to_wanderer.models import ActivityStatus, GarminActivity
from garmin_to_wanderer.reporting import Report
from garmin_to_wanderer.sources.base import GarminSource
from garmin_to_wanderer.state import ActivityRecord, StateStore
from garmin_to_wanderer.wanderer import WandererClient, WandererError


@dataclass(frozen=True, slots=True)
class SyncOptions:
    since: date
    until: date
    dry_run: bool = False
    force: bool = False


class SyncRunner:
    def __init__(
        self,
        *,
        source: GarminSource,
        wanderer: WandererClient,
        state: StateStore,
        taxonomy: WandererTaxonomy,
        config: Config,
    ):
        self.source = source
        self.wanderer = wanderer
        self.state = state
        self.taxonomy = taxonomy
        self.config = config

    def run(self, options: SyncOptions) -> Report:
        report = Report(since=options.since, until=options.until, dry_run=options.dry_run)
        processed: set[str] = set()

        for record in self.state.list_by_status(ActivityStatus.PARTIAL):
            self._retry_partial(record, report, options)
            processed.add(record.garmin_id)

        for record in self.state.list_by_status(ActivityStatus.FAILED):
            activity = _activity_from_record(record)
            self._import_activity(activity, report, options, existing=record)
            processed.add(record.garmin_id)

        for activity in self.source.iter_activities(options.since, options.until):
            if activity.garmin_id in processed:
                continue
            self._process_activity(activity, report, options)
            processed.add(activity.garmin_id)

        return report

    def _process_activity(
        self,
        activity: GarminActivity,
        report: Report,
        options: SyncOptions,
    ) -> None:
        if not self._included(activity):
            report.add(activity, ActivityStatus.SKIPPED_EXCLUDED)
            return
        if not activity.has_gps:
            report.add(activity, ActivityStatus.SKIPPED_NO_GPS)
            return

        existing = self.state.get(activity.garmin_id)
        if existing is not None and not options.force:
            if existing.status == ActivityStatus.DELETED_IN_WANDERER:
                report.add(
                    activity,
                    ActivityStatus.DELETED_IN_WANDERER,
                    wanderer_id=existing.wanderer_trail_id,
                    message="not re-imported; use --force",
                )
                return

            if existing.status == ActivityStatus.IMPORTED:
                if (
                    not options.dry_run
                    and existing.wanderer_trail_id
                    and self.wanderer.get_trail(existing.wanderer_trail_id) is None
                ):
                    self.state.set_status(activity.garmin_id, ActivityStatus.DELETED_IN_WANDERER)
                    report.add(
                        activity,
                        ActivityStatus.DELETED_IN_WANDERER,
                        wanderer_id=existing.wanderer_trail_id,
                        message="deleted in Wanderer",
                    )
                    return
                report.add(
                    activity,
                    ActivityStatus.SKIPPED_ALREADY_IMPORTED,
                    wanderer_id=existing.wanderer_trail_id,
                )
                return

            if existing.status == ActivityStatus.PARTIAL:
                self._retry_partial(existing, report, options)
                return

        self._import_activity(activity, report, options, existing=existing)

    def _retry_partial(
        self,
        record: ActivityRecord,
        report: Report,
        options: SyncOptions,
    ) -> None:
        activity = _activity_from_record(record)
        if not record.wanderer_trail_id:
            self.state.set_status(
                record.garmin_id,
                ActivityStatus.FAILED,
                error="partial record has no Wanderer trail id",
            )
            report.add(
                activity,
                ActivityStatus.FAILED,
                message="partial record has no Wanderer trail id",
            )
            return

        if options.dry_run:
            report.add(
                activity,
                ActivityStatus.PARTIAL,
                wanderer_id=record.wanderer_trail_id,
                message="would retry metadata",
            )
            return

        try:
            if self.wanderer.get_trail(record.wanderer_trail_id) is None:
                self.state.set_status(record.garmin_id, ActivityStatus.DELETED_IN_WANDERER)
                report.add(
                    activity,
                    ActivityStatus.DELETED_IN_WANDERER,
                    wanderer_id=record.wanderer_trail_id,
                    message="metadata not retried",
                )
                return
            self._apply_metadata(record.wanderer_trail_id, activity)
        except Exception as exc:
            self.state.set_status(record.garmin_id, ActivityStatus.PARTIAL, error=str(exc))
            report.add(
                activity,
                ActivityStatus.PARTIAL,
                wanderer_id=record.wanderer_trail_id,
                message=str(exc),
            )
            return

        self.state.set_status(record.garmin_id, ActivityStatus.IMPORTED, error=None)
        report.add(
            activity,
            ActivityStatus.IMPORTED,
            wanderer_id=record.wanderer_trail_id,
            message="metadata retried",
        )

    def _import_activity(
        self,
        activity: GarminActivity,
        report: Report,
        options: SyncOptions,
        *,
        existing: ActivityRecord | None,
    ) -> None:
        if options.dry_run:
            report.add(activity, ActivityStatus.WOULD_IMPORT)
            return

        trail_id: str | None = None
        try:
            downloaded = self.source.download_original(activity.garmin_id)
            existing_id = existing.wanderer_trail_id if existing else None

            if existing_id and self.wanderer.get_trail(existing_id) is not None:
                self.wanderer.update_trail_file(existing_id, downloaded, name=activity.name)
                trail_id = existing_id
            else:
                trail = self.wanderer.upload_file(downloaded, name=activity.name)
                trail_id = str(trail.get("id", "")) or None
                if trail_id is None:
                    raise WandererError("Wanderer upload returned no trail id")

            self._apply_metadata(trail_id, activity)
        except Exception as exc:
            status = ActivityStatus.PARTIAL if trail_id else ActivityStatus.FAILED
            self.state.upsert(
                activity,
                status=status,
                wanderer_trail_id=trail_id,
                error=str(exc),
            )
            report.add(activity, status, wanderer_id=trail_id, message=str(exc))
            return

        self.state.upsert(
            activity,
            status=ActivityStatus.IMPORTED,
            wanderer_trail_id=trail_id,
        )
        report.add(activity, ActivityStatus.IMPORTED, wanderer_id=trail_id)

    def _apply_metadata(self, trail_id: str, activity: GarminActivity) -> None:
        category_id, subcategory_id = resolve_category(
            type_key=activity.type_key,
            parent_type_id=activity.parent_type_id,
            config_map=self.config.sync.category_map,
            taxonomy=self.taxonomy,
            default_category=self.config.sync.default_category,
        )
        self.wanderer.update_trail(
            trail_id,
            name=activity.name,
            description=activity.description,
            date=activity.start_time.date().isoformat(),
            category=category_id,
            subcategory=subcategory_id,
        )

    def _included(self, activity: GarminActivity) -> bool:
        include = {value.lower() for value in self.config.sync.include}
        exclude = {value.lower() for value in self.config.sync.exclude}
        key = activity.type_key.lower()
        base = base_type_key(key)

        if exclude and (key in exclude or base in exclude):
            return False
        return not (include and not (key in include or base in include))


def _activity_from_record(record: ActivityRecord) -> GarminActivity:
    return GarminActivity(
        garmin_id=record.garmin_id,
        name=record.name,
        start_time=datetime.fromisoformat(record.started_at),
        type_key=record.type_key,
        parent_type_id=record.parent_type_id,
        has_gps=record.has_gps,
        description=record.description,
    )
