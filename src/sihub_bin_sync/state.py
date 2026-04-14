from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import StateError
from .models import RemoteRecord, SliceState


class ManifestStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.slices: dict[str, SliceState] = {}

    def load(self) -> None:
        if not self.path.exists():
            self.slices = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise StateError(f"Unable to load state file '{self.path}': {exc}") from exc
        raw_slices = data.get("slices", {})
        self.slices = {
            name: SliceState(
                managed_isins=set(value.get("managed_isins", [])),
                pending_create=set(value.get("pending_create", [])),
                pending_disable=set(value.get("pending_disable", [])),
                pending_enable=set(value.get("pending_enable", [])),
                last_source_fingerprint=value.get("last_source_fingerprint"),
                last_run_at=value.get("last_run_at"),
            )
            for name, value in raw_slices.items()
        }

    def get_slice(self, slice_name: str) -> SliceState:
        if slice_name not in self.slices:
            self.slices[slice_name] = SliceState()
        return self.slices[slice_name]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "slices": {
                name: {
                    "managed_isins": sorted(state.managed_isins),
                    "pending_create": sorted(state.pending_create),
                    "pending_disable": sorted(state.pending_disable),
                    "pending_enable": sorted(state.pending_enable),
                    "last_source_fingerprint": state.last_source_fingerprint,
                    "last_run_at": state.last_run_at,
                }
                for name, state in self.slices.items()
            },
        }
        try:
            self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            raise StateError(f"Unable to save state file '{self.path}': {exc}") from exc

    def reconcile_pending(self, slice_name: str, remote_by_isin: dict[str, RemoteRecord]) -> SliceState:
        state = self.get_slice(slice_name)
        state.pending_create = {
            isin for isin in state.pending_create if isin not in remote_by_isin
        }
        state.pending_disable = {
            isin
            for isin in state.pending_disable
            if isin not in remote_by_isin or not remote_by_isin[isin].disabled
        }
        state.pending_enable = {
            isin
            for isin in state.pending_enable
            if isin not in remote_by_isin or remote_by_isin[isin].disabled
        }
        return state

    def mark_slice_success(
        self,
        slice_name: str,
        desired_isins: set[str],
        fingerprint: str,
        create_isins: set[str],
        disable_isins: set[str],
        enable_isins: set[str],
    ) -> None:
        state = self.get_slice(slice_name)
        state.managed_isins = set(desired_isins)
        state.last_source_fingerprint = fingerprint
        state.last_run_at = datetime.now(timezone.utc).isoformat()
        state.pending_create.update(create_isins)
        state.pending_disable.update(disable_isins)
        state.pending_enable.update(enable_isins)

    def record_submissions(
        self,
        slice_name: str,
        create_isins: set[str],
        disable_isins: set[str],
        enable_isins: set[str],
    ) -> None:
        state = self.get_slice(slice_name)
        state.last_run_at = datetime.now(timezone.utc).isoformat()
        state.pending_create.update(create_isins)
        state.pending_disable.update(disable_isins)
        state.pending_enable.update(enable_isins)
