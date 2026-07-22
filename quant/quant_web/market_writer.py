from __future__ import annotations

import os
import shutil

import pandas as pd

try:
    from .market_store import (
        StorageMode,
        compare_frames,
        full_to_legacy,
        get_storage_mode,
        read_snapshot,
        write_snapshot,
    )
    from .xlsx_lock import XLSXLock, XLSXReadLock
except ImportError:
    from market_store import (
        StorageMode,
        compare_frames,
        full_to_legacy,
        get_storage_mode,
        read_snapshot,
        write_snapshot,
    )
    from xlsx_lock import XLSXLock, XLSXReadLock


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER_FILE = os.path.join(PROJECT_ROOT, "Whole Market.xlsx")


def write_excel_snapshot(df: pd.DataFrame, excel_path: str, legacy_date: str) -> None:
    """Write or replace one legacy MMDD sheet using the existing Excel path."""
    with XLSXLock():
        if not os.path.exists(excel_path):
            df.to_excel(excel_path, sheet_name=legacy_date, index=False)
            print(f"[+] 已新建汇总表 {excel_path} 并创建 Sheet: {legacy_date}")
        else:
            tmp = excel_path + ".tmp.xlsx"
            shutil.copy2(excel_path, tmp)
            with pd.ExcelWriter(
                tmp, engine="openpyxl", mode="a", if_sheet_exists="replace"
            ) as writer:
                df.to_excel(writer, sheet_name=legacy_date, index=False)
            os.replace(tmp, excel_path)
            print(f"[+] 已在 {excel_path} 中更新/新建 Sheet: {legacy_date}")


def compare_csv_with_excel(full_date: str, excel_path: str) -> None:
    csv_frame = read_snapshot(full_date)
    legacy_date = full_to_legacy(full_date)
    with XLSXReadLock():
        excel_frame = pd.read_excel(excel_path, sheet_name=legacy_date)
    compare_frames(csv_frame, excel_frame)


def persist_market_dataframe(
    full_date: str, df: pd.DataFrame, mode: str | None = None
) -> dict:
    selected = get_storage_mode(mode)
    legacy_date = full_to_legacy(full_date)
    result = {
        "mode": selected.value,
        "full_date": full_date,
        "legacy_date": legacy_date,
    }

    if selected in (StorageMode.XLSX, StorageMode.SHADOW):
        write_excel_snapshot(df, MASTER_FILE, legacy_date)

    if selected is StorageMode.SHADOW:
        try:
            meta = write_snapshot(full_date, df)
            compare_csv_with_excel(full_date, MASTER_FILE)
            result.update({"csv_rows": meta.rows, "shadow_ok": True})
        except Exception as exc:
            result.update({"shadow_ok": False, "shadow_error": str(exc)})
    elif selected is StorageMode.CSV:
        meta = write_snapshot(full_date, df)
        result.update({"csv_rows": meta.rows})

    return result
