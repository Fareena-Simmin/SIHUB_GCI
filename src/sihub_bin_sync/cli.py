from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync gateway card BINs from CSV snapshots.")
    parser.add_argument("--config", required=True, help="Path to the YAML config file.")
    parser.add_argument("--gateway", help="Run only one gateway.")
    parser.add_argument("--network", help="Run only one gateway+network slice.")
    parser.add_argument("--dry-run", action="store_true", help="Compute the diff but skip write calls.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    from .errors import ApiError, ConfigError, StateError, ValidationError
    from .runner import run_job

    try:
        report = run_job(
            config_path=args.config,
            gateway=args.gateway,
            network=args.network,
            dry_run=args.dry_run,
        )
    except (ApiError, ConfigError, StateError, ValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    failed = [item for item in report.slice_results if item.status == "FAILED"]
    print(f"Started: {report.started_at}")
    print(f"Finished: {report.finished_at}")
    print(f"Dry run: {report.dry_run}")
    print(f"Slices processed: {len(report.slice_results)}")
    print(f"Failed slices: {len(failed)}")
    for result in report.slice_results:
        print(
            f"- {result.slice_name}: {result.status} "
            f"(create={result.create_count}, enable={result.enable_count}, disable={result.disable_count})"
        )

    return 1 if failed else 0
