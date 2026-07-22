"""Migrate dated sheets from a market workbook to canonical CSV snapshots."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

try:
    from . import market_store
except ImportError:
    import market_store


def _full_date(sheet_name: str, year: int) -> str:
    if not isinstance(year, int) or not 2000 <= year <= 2099:
        raise ValueError(f"year must be between 2000 and 2099: {year!r}")
    try:
        month = int(sheet_name[:2])
        day = int(sheet_name[2:])
        value = date(year, month, day)
    except ValueError as exc:
        raise ValueError(
            f"invalid MMDD sheet for year {year}: {sheet_name!r}"
        ) from exc
    return value.strftime("%Y%m%d")


def _dated_sheets(sheet_names: list[str], year: int) -> list[tuple[str, str]]:
    dated = []
    for sheet_name in sheet_names:
        if len(sheet_name) != 4 or not sheet_name.isascii() or not sheet_name.isdigit():
            continue
        dated.append((_full_date(sheet_name, year), sheet_name))
    return sorted(dated)


def migrate_workbook(
    xlsx_path,
    year,
    root,
    min_rows,
    *,
    validate_only=False,
) -> list[market_store.SnapshotMeta]:
    """Migrate or validate all MMDD sheets in one workbook."""
    xlsx_path = Path(xlsx_path)
    root = Path(root)
    results = []
    total_rows = 0
    total_bytes = 0
    total_write_seconds = 0.0
    total_validation_seconds = 0.0

    with pd.ExcelFile(xlsx_path) as workbook:
        sheets = _dated_sheets(workbook.sheet_names, year)
        for full_date, sheet_name in sheets:
            source = pd.read_excel(workbook, sheet_name=sheet_name)

            write_seconds = 0.0
            if validate_only:
                validation_started = time.perf_counter()
                reread = market_store.read_snapshot(full_date, root=root)
                market_store.compare_frames(source, reread)
                meta = market_store.validate_snapshot(
                    full_date, root=root, min_rows=min_rows
                )
                validation_seconds = time.perf_counter() - validation_started
            else:
                write_started = time.perf_counter()
                meta = market_store.write_snapshot(
                    full_date, source, root=root, min_rows=min_rows
                )
                write_seconds = time.perf_counter() - write_started

                validation_started = time.perf_counter()
                reread = market_store.read_snapshot(full_date, root=root)
                market_store.compare_frames(source, reread)
                validation_seconds = time.perf_counter() - validation_started

            csv_bytes = (root / meta.path).stat().st_size
            results.append(meta)
            total_rows += meta.rows
            total_bytes += csv_bytes
            total_write_seconds += write_seconds
            total_validation_seconds += validation_seconds
            print(
                f"{full_date} rows={meta.rows} bytes={csv_bytes} "
                f"write_seconds={write_seconds:.6f} "
                f"validation_seconds={validation_seconds:.6f}"
            )

    print(
        f"total snapshots={len(results)} rows={total_rows} bytes={total_bytes} "
        f"write_seconds={total_write_seconds:.6f} "
        f"validation_seconds={total_validation_seconds:.6f}"
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate market workbook sheets to canonical CSV snapshots"
    )
    parser.add_argument("--xlsx", required=True, type=Path, help="Source XLSX workbook")
    parser.add_argument("--year", required=True, type=int, help="Year for MMDD sheets")
    parser.add_argument(
        "--output",
        type=Path,
        default=market_store.MARKET_ROOT,
        help="CSV snapshot root",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Compare workbook sheets with existing CSV snapshots",
    )
    args = parser.parse_args()

    try:
        migrate_workbook(
            args.xlsx,
            year=args.year,
            root=args.output,
            min_rows=market_store.MIN_MARKET_ROWS,
            validate_only=args.validate_only,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
