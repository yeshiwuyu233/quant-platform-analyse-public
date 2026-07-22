"""Import Whole Market.xlsx sheets into the SQLite market cache."""
import argparse
import os
import sys

import pandas as pd

try:
    from .db_service import get_db, init_db
    from .market_import import import_frame
except ImportError:
    from db_service import get_db, init_db
    from market_import import import_frame

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_XLSX = os.path.join(PROJECT_ROOT, "Whole Market.xlsx")


def import_sheet(conn, xlsx_path: str, sheet_name: str) -> int:
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
    return import_frame(conn, sheet_name, df)


def import_workbook(xlsx_path: str, limit_sheets: int | None = None, validate_only: bool = False, sheet_names: list[str] | None = None) -> list[tuple[str, int]]:
    xls = pd.ExcelFile(xlsx_path)
    available = [s for s in xls.sheet_names if s.isdigit() and len(s) == 4]
    if sheet_names:
        wanted = [str(s).zfill(4) for s in sheet_names]
        missing = [s for s in wanted if s not in available]
        if missing:
            raise ValueError(f"sheet(s) not found in workbook: {missing}")
        sheets = wanted
    else:
        sheets = sorted(available)
        if limit_sheets:
            sheets = sheets[-limit_sheets:]

    if validate_only:
        return [(s, len(pd.read_excel(xlsx_path, sheet_name=s, usecols=["代码"]))) for s in sheets]

    conn = get_db()
    try:
        init_db(conn)
        results = []
        for sheet in sheets:
            count = import_sheet(conn, xlsx_path, sheet)
            results.append((sheet, count))
        conn.commit()
        return results
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Whole Market.xlsx into market.db")
    parser.add_argument("--xlsx", default=DEFAULT_XLSX)
    parser.add_argument("--limit-sheets", type=int, default=None)
    parser.add_argument("--sheet", action="append", dest="sheets", help="Import a specific MMDD sheet; may be repeated")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    if not os.path.exists(args.xlsx):
        print(f"missing workbook: {args.xlsx}", file=sys.stderr)
        return 1

    results = import_workbook(args.xlsx, args.limit_sheets, args.validate_only, args.sheets)
    for sheet, count in results:
        print(f"{sheet}: {count}")
    print(f"sheets: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
