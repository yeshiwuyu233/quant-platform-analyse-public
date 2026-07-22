"""Helpers for locating generated backtest and weekly report files."""
from __future__ import annotations

import glob
import os
from typing import Iterable

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")


def ensure_reports_dir() -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    return REPORTS_DIR


def _dedupe(paths: Iterable[str]) -> list[str]:
    by_name: dict[str, str] = {}
    for path in paths:
        base = os.path.basename(path)
        existing = by_name.get(base)
        if existing and os.path.getmtime(existing) >= os.path.getmtime(path):
            continue
        by_name[base] = path
    return list(by_name.values())


def glob_reports(pattern: str) -> list[str]:
    """Return matching report files from reports/ and legacy root paths."""
    report_matches = glob.glob(os.path.join(REPORTS_DIR, pattern))
    legacy_matches = glob.glob(os.path.join(PROJECT_ROOT, pattern))
    return sorted(_dedupe(sorted(report_matches) + sorted(legacy_matches)))


def latest_report(pattern: str) -> str | None:
    files = glob_reports(pattern)
    return max(files, key=os.path.getmtime) if files else None


def resolve_report(filename: str) -> str:
    """Resolve a report filename for reading, preferring reports/."""
    report_path = os.path.join(REPORTS_DIR, filename)
    if os.path.exists(report_path):
        return report_path
    return os.path.join(PROJECT_ROOT, filename)


def output_report(filename: str) -> str:
    """Return the canonical path for newly generated reports."""
    return os.path.join(ensure_reports_dir(), filename)
