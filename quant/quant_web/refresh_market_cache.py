"""Refresh the SQLite market cache from the configured storage backend."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

try:
    from . import import_market_csv, import_market_xlsx, market_store
except ImportError:
    import import_market_csv
    import import_market_xlsx
    import market_store


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def refresh_market_cache(full_date: str, mode: str | None = None) -> int:
    selected = market_store.get_storage_mode(mode)
    full_date = market_store.validate_full_date(full_date)
    if selected is market_store.StorageMode.CSV:
        return import_market_csv.import_csv_snapshot(full_date)

    results = import_market_xlsx.import_workbook(
        str(PROJECT_ROOT / "Whole Market.xlsx"),
        sheet_names=[market_store.full_to_legacy(full_date)],
    )
    return results[0][1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--date", help="Import one YYYYMMDD market date")
    selection.add_argument("--latest", action="store_true", help="Import the latest market date")
    args = parser.parse_args(argv)

    try:
        mode = market_store.get_storage_mode()
        if args.latest:
            if mode is market_store.StorageMode.CSV:
                dates = market_store.list_full_dates()
                if not dates:
                    raise ValueError("no stored CSV market dates")
                full_date = dates[-1]
            else:
                full_date = datetime.now().strftime("%Y%m%d")
        else:
            full_date = market_store.validate_full_date(args.date)
        rows = refresh_market_cache(full_date, mode=mode.value)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"mode={mode.value} date={full_date} rows={rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
