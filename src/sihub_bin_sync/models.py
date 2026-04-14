from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    list_path: str
    batch_create_path: str
    update_path_template: str
    timeout_seconds: int
    change_description: str
    headers_from_env: dict[str, str]


@dataclass(frozen=True)
class RuntimeConfig:
    state_file: Path
    reports_dir: Path
    processed_dir: Path
    failed_dir: Path


@dataclass(frozen=True)
class DefaultsConfig:
    auth_type: str
    validation_type: str
    payment_method_type: str
    min_isin_length: int
    max_isin_length: int


@dataclass(frozen=True)
class CsvColumnsConfig:
    isin: str
    gateway: str | None = None
    network: str | None = None


@dataclass(frozen=True)
class CsvSourceConfig:
    type: str
    file: str
    header_row: int
    encoding: str
    delimiter: str
    quotechar: str
    allow_empty_snapshot: bool
    columns: CsvColumnsConfig
    normalization: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class SliceConfig:
    name: str
    gateway: str
    network: str
    enabled: bool
    source: CsvSourceConfig
    auth_type: str | None = None
    validation_type: str | None = None
    payment_method_type: str | None = None
    gateway_bank_code: str | None = None
    juspay_bank_code: str | None = None

    def resolved_auth_type(self, defaults: DefaultsConfig) -> str:
        return self.auth_type or defaults.auth_type

    def resolved_validation_type(self, defaults: DefaultsConfig) -> str:
        return self.validation_type or defaults.validation_type

    def resolved_payment_method_type(self, defaults: DefaultsConfig) -> str:
        return self.payment_method_type or defaults.payment_method_type


@dataclass(frozen=True)
class AppConfig:
    api: ApiConfig
    runtime: RuntimeConfig
    defaults: DefaultsConfig
    slices: list[SliceConfig]


@dataclass(frozen=True)
class ParsedCsv:
    path: Path
    fingerprint: str
    headers: list[str]
    rows: list[dict[str, str]]


@dataclass(frozen=True)
class SliceSnapshot:
    slice_name: str
    gateway: str
    network: str
    source_path: Path
    source_fingerprint: str
    matched_rows: int
    desired_isins: set[str]


@dataclass(frozen=True)
class RemoteRecord:
    id: str
    gateway: str
    isin: str
    disabled: bool
    auth_type: str | None
    validation_type: str | None
    payment_method_type: str | None
    raw: dict[str, Any]


@dataclass
class SliceState:
    managed_isins: set[str] = field(default_factory=set)
    pending_create: set[str] = field(default_factory=set)
    pending_disable: set[str] = field(default_factory=set)
    pending_enable: set[str] = field(default_factory=set)
    last_source_fingerprint: str | None = None
    last_run_at: str | None = None


@dataclass(frozen=True)
class SlicePlan:
    to_create: set[str]
    to_enable: set[str]
    to_disable: set[str]
    unchanged: set[str]


@dataclass
class SliceResult:
    slice_name: str
    gateway: str
    network: str
    source_path: str
    matched_rows: int = 0
    desired_count: int = 0
    create_count: int = 0
    enable_count: int = 0
    disable_count: int = 0
    unchanged_count: int = 0
    pending_count: int = 0
    status: str = "PENDING"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.status = "FAILED"


@dataclass
class RunReport:
    started_at: str
    finished_at: str | None
    dry_run: bool
    gateway_filter: str | None
    network_filter: str | None
    slice_results: list[SliceResult] = field(default_factory=list)

