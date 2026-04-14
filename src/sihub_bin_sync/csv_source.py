from __future__ import annotations

import csv
import glob
import hashlib
from pathlib import Path

from .errors import ValidationError
from .models import CsvSourceConfig, DefaultsConfig, ParsedCsv, SliceConfig, SliceSnapshot


def resolve_single_source_file(file_pattern: str, working_dir: Path) -> Path:
    pattern = str((working_dir / file_pattern).resolve()) if not Path(file_pattern).is_absolute() else file_pattern
    matches = [Path(match).resolve() for match in glob.glob(pattern)]
    if not matches:
        raise ValidationError(f"No input file matched '{file_pattern}'.")
    if len(matches) > 1:
        raise ValidationError(
            f"Ambiguous input for '{file_pattern}'. Expected exactly one file, found {len(matches)}."
        )
    return matches[0]


def load_csv(path: Path, source: CsvSourceConfig) -> ParsedCsv:
    raw_bytes = path.read_bytes()
    fingerprint = hashlib.sha256(raw_bytes).hexdigest()

    with path.open("r", encoding=source.encoding, newline="") as handle:
        for _ in range(max(source.header_row - 1, 0)):
            next(handle, None)
        reader = csv.DictReader(
            handle,
            delimiter=source.delimiter,
            quotechar=source.quotechar,
        )
        if reader.fieldnames is None:
            raise ValidationError(f"CSV '{path}' has no header row.")
        rows = [{key: value or "" for key, value in row.items()} for row in reader]
        return ParsedCsv(path=path, fingerprint=fingerprint, headers=list(reader.fieldnames), rows=rows)


def _normalize(value: str, mapping: dict[str, str]) -> str:
    trimmed = value.strip()
    return mapping.get(trimmed.casefold(), trimmed)


def build_slice_snapshot(
    parsed_csv: ParsedCsv,
    slice_config: SliceConfig,
    defaults: DefaultsConfig,
) -> SliceSnapshot:
    headers = set(parsed_csv.headers)
    isin_column = slice_config.source.columns.isin
    gateway_column = slice_config.source.columns.gateway
    network_column = slice_config.source.columns.network

    required_columns = {isin_column}
    if gateway_column:
        required_columns.add(gateway_column)
    if network_column:
        required_columns.add(network_column)

    missing_columns = sorted(column for column in required_columns if column not in headers)
    if missing_columns:
        raise ValidationError(
            f"CSV '{parsed_csv.path}' is missing required columns for slice '{slice_config.name}': "
            + ", ".join(missing_columns)
        )

    gateway_map = slice_config.source.normalization.get("gateway", {})
    network_map = slice_config.source.normalization.get("network", {})

    desired_isins: set[str] = set()
    matched_rows = 0
    duplicates: set[str] = set()

    for row in parsed_csv.rows:
        row_gateway = slice_config.gateway
        if gateway_column:
            row_gateway = _normalize(row[gateway_column], gateway_map)
        row_network = slice_config.network
        if network_column:
            row_network = _normalize(row[network_column], network_map)

        if row_gateway != slice_config.gateway or row_network != slice_config.network:
            continue

        matched_rows += 1
        isin = row[isin_column].strip()
        if not isin:
            raise ValidationError(
                f"Slice '{slice_config.name}' matched a row with empty ISIN in '{parsed_csv.path}'."
            )
        if not isin.isdigit():
            raise ValidationError(
                f"Slice '{slice_config.name}' found non-numeric ISIN '{isin}' in '{parsed_csv.path}'."
            )
        if not defaults.min_isin_length <= len(isin) <= defaults.max_isin_length:
            raise ValidationError(
                f"Slice '{slice_config.name}' found ISIN '{isin}' outside supported length "
                f"{defaults.min_isin_length}-{defaults.max_isin_length}."
            )
        if isin in desired_isins:
            duplicates.add(isin)
        desired_isins.add(isin)

    if duplicates:
        duplicate_text = ", ".join(sorted(duplicates))
        raise ValidationError(
            f"Slice '{slice_config.name}' contains duplicate ISINs in the snapshot: {duplicate_text}"
        )

    if matched_rows == 0 and not slice_config.source.allow_empty_snapshot:
        raise ValidationError(
            f"Slice '{slice_config.name}' matched zero rows in '{parsed_csv.path}'. "
            "Empty snapshots are blocked by default."
        )

    return SliceSnapshot(
        slice_name=slice_config.name,
        gateway=slice_config.gateway,
        network=slice_config.network,
        source_path=parsed_csv.path,
        source_fingerprint=parsed_csv.fingerprint,
        matched_rows=matched_rows,
        desired_isins=desired_isins,
    )
