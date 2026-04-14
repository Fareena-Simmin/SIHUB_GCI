from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError
from .models import (
    ApiConfig,
    AppConfig,
    CsvColumnsConfig,
    CsvSourceConfig,
    DefaultsConfig,
    RuntimeConfig,
    SliceConfig,
)


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"Missing required key '{key}' in {context}.")
    return mapping[key]


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def load_config(config_path: str) -> AppConfig:
    path = Path(config_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ConfigError("Top-level YAML must be a mapping.")

    base_dir = path.parent.parent if path.parent.name == "configs" else path.parent

    api_data = _require(data, "api", "top-level config")
    runtime_data = _require(data, "runtime", "top-level config")
    defaults_data = _require(data, "defaults", "top-level config")
    slices_data = _require(data, "slices", "top-level config")

    api = ApiConfig(
        base_url=_require(api_data, "base_url", "api"),
        list_path=_require(api_data, "list_path", "api"),
        batch_create_path=_require(api_data, "batch_create_path", "api"),
        update_path_template=_require(api_data, "update_path_template", "api"),
        timeout_seconds=int(api_data.get("timeout_seconds", 30)),
        change_description=str(api_data.get("change_description", "SI Hub BIN sync")),
        headers_from_env=dict(api_data.get("headers_from_env", {})),
    )

    runtime = RuntimeConfig(
        state_file=_resolve_path(base_dir, _require(runtime_data, "state_file", "runtime")),
        reports_dir=_resolve_path(base_dir, _require(runtime_data, "reports_dir", "runtime")),
        processed_dir=_resolve_path(base_dir, _require(runtime_data, "processed_dir", "runtime")),
        failed_dir=_resolve_path(base_dir, _require(runtime_data, "failed_dir", "runtime")),
    )

    defaults = DefaultsConfig(
        auth_type=_require(defaults_data, "auth_type", "defaults"),
        validation_type=_require(defaults_data, "validation_type", "defaults"),
        payment_method_type=_require(defaults_data, "payment_method_type", "defaults"),
        min_isin_length=int(defaults_data.get("min_isin_length", 6)),
        max_isin_length=int(defaults_data.get("max_isin_length", 9)),
    )

    if not isinstance(slices_data, list) or not slices_data:
        raise ConfigError("'slices' must be a non-empty list.")

    seen_names: set[str] = set()
    slices: list[SliceConfig] = []
    for item in slices_data:
        if not isinstance(item, dict):
            raise ConfigError("Each slice entry must be a mapping.")
        name = _require(item, "name", "slice")
        if name in seen_names:
            raise ConfigError(f"Duplicate slice name '{name}'.")
        seen_names.add(name)
        source_data = _require(item, "source", f"slice {name}")
        columns_data = _require(source_data, "columns", f"slice {name}.source")
        source = CsvSourceConfig(
            type=_require(source_data, "type", f"slice {name}.source"),
            file=str(_resolve_path(base_dir, _require(source_data, "file", f"slice {name}.source"))),
            header_row=int(source_data.get("header_row", 1)),
            encoding=str(source_data.get("encoding", "utf-8-sig")),
            delimiter=str(source_data.get("delimiter", ",")),
            quotechar=str(source_data.get("quotechar", '"')),
            allow_empty_snapshot=bool(source_data.get("allow_empty_snapshot", False)),
            columns=CsvColumnsConfig(
                isin=_require(columns_data, "isin", f"slice {name}.source.columns"),
                gateway=columns_data.get("gateway"),
                network=columns_data.get("network"),
            ),
            normalization={
                bucket: {str(k).casefold(): str(v) for k, v in values.items()}
                for bucket, values in dict(source_data.get("normalization", {})).items()
            },
        )
        if source.type != "csv":
            raise ConfigError(
                f"Unsupported source type '{source.type}' for slice '{name}'. Only 'csv' is enabled in v1."
            )
        slices.append(
            SliceConfig(
                name=name,
                gateway=_require(item, "gateway", f"slice {name}"),
                network=_require(item, "network", f"slice {name}"),
                enabled=bool(item.get("enabled", True)),
                source=source,
                auth_type=item.get("auth_type"),
                validation_type=item.get("validation_type"),
                payment_method_type=item.get("payment_method_type"),
                gateway_bank_code=item.get("gateway_bank_code"),
                juspay_bank_code=item.get("juspay_bank_code"),
            )
        )

    return AppConfig(api=api, runtime=runtime, defaults=defaults, slices=slices)
