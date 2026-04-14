from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import RunReport, SliceResult


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_reports(report: RunReport, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report.started_at.replace(":", "-")
    json_path = reports_dir / f"run-{timestamp}.json"
    md_path = reports_dir / f"run-{timestamp}.md"
    json_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, md_path


def render_markdown_report(report: RunReport) -> str:
    lines = [
        "# BIN Sync Run Report",
        "",
        f"- Started: `{report.started_at}`",
        f"- Finished: `{report.finished_at}`",
        f"- Dry run: `{report.dry_run}`",
        f"- Gateway filter: `{report.gateway_filter or 'ALL'}`",
        f"- Network filter: `{report.network_filter or 'ALL'}`",
        "",
        "## Slices",
        "",
    ]

    for result in report.slice_results:
        lines.extend(
            [
                f"### {result.slice_name}",
                "",
                f"- Status: `{result.status}`",
                f"- Gateway: `{result.gateway}`",
                f"- Network: `{result.network}`",
                f"- Source: `{result.source_path}`",
                f"- Matched rows: `{result.matched_rows}`",
                f"- Desired BINs: `{result.desired_count}`",
                f"- Create: `{result.create_count}`",
                f"- Enable: `{result.enable_count}`",
                f"- Disable: `{result.disable_count}`",
                f"- Unchanged: `{result.unchanged_count}`",
                f"- Pending tracked: `{result.pending_count}`",
            ]
        )
        if result.errors:
            lines.append("- Errors:")
            for error in result.errors:
                lines.append(f"  - {error}")
        if result.warnings:
            lines.append("- Warnings:")
            for warning in result.warnings:
                lines.append(f"  - {warning}")
        lines.append("")

    return "\n".join(lines)
