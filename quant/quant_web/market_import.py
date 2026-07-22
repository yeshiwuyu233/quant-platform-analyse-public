"""Shared DataFrame importer for the SQLite market cache."""

import pandas as pd


def clean_text(value):
    return "" if pd.isna(value) else str(value).strip()


def clean_float(value):
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def import_frame(conn, legacy_date: str, df: pd.DataFrame) -> int:
    required = {"代码", "全称", "行业", "准确率", "今日指标", "指标历史"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"snapshot {legacy_date} missing columns: {sorted(missing)}")

    rows = []
    for row_order, (_, row) in enumerate(df.iterrows()):
        code = clean_text(row.get("代码"))
        if code:
            rows.append((
                legacy_date,
                row_order,
                code,
                clean_text(row.get("全称")),
                clean_text(row.get("行业")),
                clean_float(row.get("准确率")),
                clean_float(row.get("今日指标")),
                clean_text(row.get("指标历史")),
            ))

    conn.execute("DELETE FROM market_snapshot WHERE trade_date = ?", (legacy_date,))
    conn.executemany(
        """INSERT INTO market_snapshot
           (trade_date, row_order, code, name, industry, accuracy, indicator, indicator_history)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.execute(
        """INSERT INTO import_meta (trade_date, rows_count, imported_at)
           VALUES (?, ?, datetime('now','localtime'))
           ON CONFLICT(trade_date) DO UPDATE SET
             rows_count=excluded.rows_count, imported_at=excluded.imported_at""",
        (legacy_date, len(rows)),
    )
    return len(rows)
