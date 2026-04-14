# SI Hub BIN Sync

Config-driven Python job for syncing card-mandate BINs into Juspay `gatewayCardInfo`.

## What It Does

- Reads full-snapshot CSV files.
- Filters rows by configured `gateway + network`.
- Validates the entire slice before any write call.
- Creates only genuinely new BINs.
- Disables missing BINs instead of deleting them.
- Re-enables previously disabled BINs when they reappear.
- Keeps a local state manifest so one network sync does not disable BINs owned by another network under the same gateway.
- Produces JSON and Markdown run summaries.

## Why The Local State Exists

Your business unit is `gateway + network`, but the internal API examples do not clearly expose `network` as a first-class field/filter. Because of that, the job keeps a local ownership manifest per slice and only disables BINs that were previously managed by that exact slice.

## Quick Start

1. Create and activate a virtual environment.
2. Install the package:

```bash
pip install -e .
```

3. Copy the sample config and adjust it:

```bash
cp configs/example.yaml configs/local.yaml
```

4. Export the required auth headers as environment variables.
5. Run a dry run:

```bash
sihub-bin-sync --config configs/local.yaml --dry-run
```

6. Run one slice only:

```bash
sihub-bin-sync --config configs/local.yaml --gateway PAYU --network VISA
```

## Runtime Layout

- `runtime/state/`: local manifest for managed BINs and pending review operations
- `runtime/reports/`: JSON and Markdown run reports
- `runtime/processed/`: successfully consumed input files
- `runtime/failed/`: files that failed validation or processing

## Notes

- Dry runs still call the read/list API so the diff is accurate; they only skip write calls.
- Because Dashboard writes return `IN_REVIEW`, the job treats successful submission as success and tracks pending operations locally until the remote state reflects them.
- Empty filtered snapshots are blocked by default to avoid accidental mass disables. This can be overridden per slice with `allow_empty_snapshot: true`.

More detail lives in [docs/architecture.md](/Users/anjireddymodugula/Documents/GitHub/SIHUB_GCI/docs/architecture.md).
