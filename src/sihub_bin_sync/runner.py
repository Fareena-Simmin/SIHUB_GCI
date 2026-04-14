from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path

from .api import GatewayCardInfoClient
from .config import load_config
from .csv_source import build_slice_snapshot, load_csv, resolve_single_source_file
from .errors import ApiError, ConfigError, StateError, ValidationError
from .models import AppConfig, RunReport, SliceConfig, SlicePlan, SliceResult, SliceSnapshot
from .reporting import utc_now, write_reports
from .state import ManifestStore


def _select_slices(config: AppConfig, gateway: str | None, network: str | None) -> list[SliceConfig]:
    selected: list[SliceConfig] = []
    for slice_config in config.slices:
        if not slice_config.enabled:
            continue
        if gateway and slice_config.gateway != gateway:
            continue
        if network and slice_config.network != network:
            continue
        selected.append(slice_config)
    return selected


def _plan_slice(snapshot: SliceSnapshot, state, remote_by_isin) -> SlicePlan:
    existing_isins = set(remote_by_isin)
    active_isins = {isin for isin, record in remote_by_isin.items() if not record.disabled}
    disabled_isins = {isin for isin, record in remote_by_isin.items() if record.disabled}

    to_create = snapshot.desired_isins - existing_isins - state.pending_create
    to_enable = (snapshot.desired_isins & disabled_isins) - state.pending_enable
    to_disable = (state.managed_isins - snapshot.desired_isins) & active_isins
    to_disable -= state.pending_disable
    unchanged = snapshot.desired_isins - to_create - to_enable

    return SlicePlan(
        to_create=to_create,
        to_enable=to_enable,
        to_disable=to_disable,
        unchanged=unchanged,
    )


def _move_file(source_path: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source_path.name
    if destination.exists():
        destination.unlink()
    shutil.move(str(source_path), str(destination))


def _sources_share_parse_settings(slices_for_file: list[SliceConfig]) -> bool:
    if not slices_for_file:
        return True
    first = slices_for_file[0].source
    baseline = (
        first.header_row,
        first.encoding,
        first.delimiter,
        first.quotechar,
    )
    for slice_config in slices_for_file[1:]:
        current = (
            slice_config.source.header_row,
            slice_config.source.encoding,
            slice_config.source.delimiter,
            slice_config.source.quotechar,
        )
        if current != baseline:
            return False
    return True


def run_job(config_path: str, gateway: str | None, network: str | None, dry_run: bool) -> RunReport:
    config = load_config(config_path)
    report = RunReport(
        started_at=utc_now(),
        finished_at=None,
        dry_run=dry_run,
        gateway_filter=gateway,
        network_filter=network,
    )

    selected_slices = _select_slices(config, gateway, network)
    if not selected_slices:
        report.finished_at = utc_now()
        write_reports(report, config.runtime.reports_dir)
        return report

    manifest = ManifestStore(config.runtime.state_file)
    manifest.load()
    client = GatewayCardInfoClient(config.api)
    selected_by_name = {slice_config.name: slice_config for slice_config in selected_slices}

    results_by_name: dict[str, SliceResult] = {}
    snapshots_by_name: dict[str, SliceSnapshot] = {}
    files_to_slices: dict[Path, list[SliceConfig]] = defaultdict(list)

    for slice_config in selected_slices:
        result = SliceResult(
            slice_name=slice_config.name,
            gateway=slice_config.gateway,
            network=slice_config.network,
            source_path=slice_config.source.file,
        )
        results_by_name[slice_config.name] = result
        try:
            source_path = resolve_single_source_file(slice_config.source.file, Path.cwd())
            files_to_slices[source_path].append(slice_config)
            result.source_path = str(source_path)
        except ValidationError as exc:
            result.add_error(str(exc))

    for source_path, slices_for_file in files_to_slices.items():
        if not _sources_share_parse_settings(slices_for_file):
            for slice_config in slices_for_file:
                results_by_name[slice_config.name].add_error(
                    f"Shared source file '{source_path}' has conflicting CSV parse settings across slices."
                )
            if not dry_run:
                _move_file(source_path, config.runtime.failed_dir)
            continue
        try:
            parsed_csv = load_csv(source_path, slices_for_file[0].source)
        except ValidationError as exc:
            for slice_config in slices_for_file:
                results_by_name[slice_config.name].add_error(str(exc))
            if not dry_run:
                _move_file(source_path, config.runtime.failed_dir)
            continue

        for slice_config in slices_for_file:
            result = results_by_name[slice_config.name]
            if result.status == "FAILED":
                continue
            try:
                snapshot = build_slice_snapshot(parsed_csv, slice_config, config.defaults)
                snapshots_by_name[slice_config.name] = snapshot
                result.matched_rows = snapshot.matched_rows
                result.desired_count = len(snapshot.desired_isins)
            except ValidationError as exc:
                result.add_error(str(exc))

    ownership: dict[tuple[str, str], str] = {}
    for slice_name, snapshot in snapshots_by_name.items():
        result = results_by_name[slice_name]
        if result.status == "FAILED":
            continue
        for isin in snapshot.desired_isins:
            key = (snapshot.gateway, isin)
            existing_owner = ownership.get(key)
            if existing_owner and existing_owner != slice_name:
                message = (
                    f"BIN '{isin}' under gateway '{snapshot.gateway}' is owned by multiple slices: "
                    f"'{existing_owner}' and '{slice_name}'."
                )
                results_by_name[existing_owner].add_error(message)
                result.add_error(message)
            else:
                ownership[key] = slice_name

    gateway_cache = {}
    gateway_seed_slice = {}
    for slice_name, snapshot in snapshots_by_name.items():
        if results_by_name[slice_name].status == "FAILED":
            continue
        gateway_seed_slice.setdefault(snapshot.gateway, selected_by_name[slice_name])

    for gateway_name, seed_slice in gateway_seed_slice.items():
        try:
            gateway_cache[gateway_name] = client.list_gateway_records(gateway_name, seed_slice, config.defaults)
        except (ApiError, ConfigError) as exc:
            for slice_name, snapshot in snapshots_by_name.items():
                if snapshot.gateway == gateway_name:
                    results_by_name[slice_name].add_error(str(exc))

    for slice_config in selected_slices:
        result = results_by_name[slice_config.name]
        if result.status == "FAILED":
            continue
        snapshot = snapshots_by_name[slice_config.name]
        remote_by_isin = gateway_cache.get(slice_config.gateway, {})
        state = manifest.reconcile_pending(slice_config.name, remote_by_isin)
        plan = _plan_slice(snapshot, state, remote_by_isin)
        result.create_count = len(plan.to_create)
        result.enable_count = len(plan.to_enable)
        result.disable_count = len(plan.to_disable)
        result.unchanged_count = len(plan.unchanged)
        result.pending_count = (
            len(state.pending_create) + len(state.pending_disable) + len(state.pending_enable)
        )

        if dry_run:
            result.status = "DRY_RUN"
            continue

        successful_creates: set[str] = set()
        successful_disables: set[str] = set()
        successful_enables: set[str] = set()
        try:
            if plan.to_create:
                client.submit_create_batch(slice_config, config.defaults, sorted(plan.to_create))
                successful_creates = set(plan.to_create)
            for isin in sorted(plan.to_enable):
                remote_record = remote_by_isin.get(isin)
                if remote_record is None:
                    raise ApiError(f"Cannot re-enable ISIN '{isin}' because it was not found remotely.")
                client.update_disabled(remote_record.id, disabled=False)
                successful_enables.add(isin)
            for isin in sorted(plan.to_disable):
                remote_record = remote_by_isin.get(isin)
                if remote_record is None:
                    raise ApiError(f"Cannot disable ISIN '{isin}' because it was not found remotely.")
                client.update_disabled(remote_record.id, disabled=True)
                successful_disables.add(isin)
        except ApiError as exc:
            if successful_creates or successful_disables or successful_enables:
                manifest.record_submissions(
                    slice_name=slice_config.name,
                    create_isins=successful_creates,
                    disable_isins=successful_disables,
                    enable_isins=successful_enables,
                )
            result.add_error(str(exc))
            continue

        manifest.mark_slice_success(
            slice_name=slice_config.name,
            desired_isins=snapshot.desired_isins,
            fingerprint=snapshot.source_fingerprint,
            create_isins=plan.to_create,
            disable_isins=plan.to_disable,
            enable_isins=plan.to_enable,
        )
        result.status = "SUCCESS"

    if not dry_run:
        manifest.save()

    for source_path, slices_for_file in files_to_slices.items():
        if dry_run or not source_path.exists():
            continue
        slice_statuses = [results_by_name[slice_config.name].status for slice_config in slices_for_file]
        destination_dir = config.runtime.processed_dir
        if any(status == "FAILED" for status in slice_statuses):
            destination_dir = config.runtime.failed_dir
        _move_file(source_path, destination_dir)

    report.slice_results = [results_by_name[slice_config.name] for slice_config in selected_slices]
    report.finished_at = utc_now()
    write_reports(report, config.runtime.reports_dir)
    return report
