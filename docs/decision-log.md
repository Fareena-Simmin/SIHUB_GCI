# Discovery Decision Log

This document captures the key decisions made during the discovery and architecture phase so the project can be reviewed quickly later without replaying the full conversation.

## Purpose

Build a Python job that syncs card-mandate BIN support data into Juspay `gatewayCardInfo`, starting with CSV sources and leaving room for future source types.

## Product Scope

- Project type: Python scheduled job
- Domain: India card-mandate BIN support
- Target system: Juspay `gatewayCardInfo`
- Initial implementation scope: CSV ingestion only
- Future scope: gateway APIs and SI Hub APIs

## Core Business Goal

Keep Juspay BIN support data aligned with the latest source snapshots provided per payment gateway and card network.

## Important Terminology

- `ISIN` in this project means the card BIN value used by the internal Dashboard APIs.
- `SI Hub` refers to Standing Instruction Hub.
- `gateway + network` is the business-level unit we manage.

## Confirmed Design Decisions

### 1. Unit Of Configuration

- Each config entry represents one `gateway + network` slice.
- Different networks under the same gateway may use different source types in the future.

Examples:

- `PAYU + VISA` from CSV
- `PAYU + MASTERCARD` from CSV
- `PAYU + RUPAY` from a future API

### 2. Source Model

- V1 supports `csv` only.
- Future source types will include:
  - gateway API source
  - SI Hub API source
- A single CSV file can be reused by multiple config entries.
- A single CSV file may contain:
  - multiple gateways
  - multiple networks
- If a CSV contains multiple gateways, it will include a `gateway` column.
- If a CSV contains multiple networks, it will include a `network` column.

### 3. Snapshot Semantics

- Every source payload is a full current snapshot, not a delta.
- Sync decisions are always made against the full latest state for that slice.

### 4. Sync Behavior

- Missing BINs must be disabled, not deleted.
- Previously disabled BINs must be re-enabled if they reappear.
- New BINs are created through batch create.
- Existing BINs must not be re-sent in create payloads because the batch API errors on duplicates.
- Success currently means the change request was submitted successfully, even if the Dashboard response is `IN_REVIEW`.

### 5. Validation Rules

- Validate the full slice before any write call.
- If the same BIN appears twice in the same `gateway + network` snapshot, fail the slice.
- If more than one candidate snapshot file exists for a configured file pattern, fail the slice.
- Empty filtered snapshots are unsafe by default and should fail unless explicitly allowed.
- If a CSV or source payload is invalid, do not allow partial updates.

### 6. Operational Failure Behavior

- If one `gateway + network` slice fails, other slices must continue.
- If one network under a gateway fails, the other networks under that same gateway should still continue.
- The system must support rerunning a single:
  - gateway
  - gateway + network
- Detailed failure reporting is required so reruns are easy.

### 7. File Lifecycle

- Successfully processed files should be moved to `processed` or `archive`.
- Failed files should be moved to `failed`.
- Because one CSV can feed multiple slices, file movement happens after all dependent slices are processed.

### 8. Reporting

- The job must generate a detailed summary after each run.
- Current reporting output should be file-based.
- Future reporting should include email notifications.
- The scaffold currently writes:
  - JSON report
  - Markdown report

### 9. CSV Mapping Rules

- CSV formats will vary by gateway.
- Different files may use different header names.
- The main fields extracted from CSV are:
  - `isin`
  - sometimes `network`
  - sometimes `gateway`
- `gatewayBankCode` and `juspayBankCode` are not required from CSV in V1.
- Header mapping must be configurable.
- Value normalization must be configurable.

Examples:

- `Visa`, `VISA`, and `Visa Card` may all normalize to `VISA`
- gateway names may also need source-specific normalization

### 10. Default Constants For V1

These values are treated as constants by default unless a config entry overrides them:

- `authType = THREE_DS`
- `validationType = CARD_MANDATE`
- `paymentMethodType = CARD`

### 11. API Understanding

Based on the internal curl documentation:

- List endpoint exists
- Batch create endpoint exists
- Disable uses update with `{"disabled": true}`
- Re-enable uses the same update API with `{"disabled": false}`
- List supports gateway-level filtering
- Network support in the target API is still not clearly exposed

### 12. Local Ownership State

Because the business model is `gateway + network` but the target API examples do not clearly expose `network` as a first-class field, the job must keep local ownership state.

Reason:

- one network slice must not disable BINs managed by another network slice under the same gateway

This local state also helps track submitted changes that are still `IN_REVIEW`.

## Config Decisions

- Config format: YAML
- One config entry per `gateway + network`
- Shared CSVs are supported
- Each config entry can define:
  - file or file pattern
  - header row
  - encoding
  - delimiter
  - quote character
  - column mapping
  - normalization rules

## Runtime Decisions

- The job should support:
  - run all
  - run one gateway
  - run one gateway + network
  - dry-run
- Scheduler choice is not finalized yet.
- Production auth strategy is not finalized yet.
- For local testing, auth can temporarily follow the pattern shown in the sample curl doc.

## Deferred Decisions

These were intentionally left for later:

- production authentication model
- final scheduler or deployment platform
- email notification implementation
- API-based source implementations
- SI Hub API source implementation
- batch-size or rate-limit handling, unless later required

## Known Constraints

- Different gateways provide different CSV formats.
- Bulk create errors on duplicates.
- Dashboard writes may enter maker-checker flow and remain `IN_REVIEW`.
- The internal sample API file contains session-like credentials and should be treated as sensitive.

## Current Implementation Status

The scaffold currently includes:

- config-driven CSV ingestion
- per-slice validation
- diff computation
- create / enable / disable API boundaries
- local state manifest
- JSON and Markdown run reports
- runtime directory structure

## Remaining Inputs Needed For Live Testing

- one real sample CSV
- real auth values for the current environment
- any gateway-specific payload details if they differ from the default constants

## Related Docs

- [Architecture](/Users/anjireddymodugula/Documents/GitHub/SIHUB_GCI/docs/architecture.md)
- [Sample Config](/Users/anjireddymodugula/Documents/GitHub/SIHUB_GCI/configs/example.yaml)
