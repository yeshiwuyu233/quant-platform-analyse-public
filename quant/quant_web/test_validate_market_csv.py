import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd

from quant_web import market_store, validate_market_csv


def sample_market(rows=3):
    return pd.DataFrame({
        "全称": [f"股票{i}" for i in range(rows)],
        "代码": [f"{i:06d}.SZ" for i in range(rows)],
        "行业": ["银行"] * rows,
        "地域": ["深圳"] * rows,
        "准确率": [0.7] * rows,
        "追踪天数": [90] * rows,
        "倍数": ["1.48(5.05)"] * rows,
        "指标历史": ["(+1.20%)"] * rows,
        "近三日涨幅": ["-"] * rows,
        "今日指标": [1.2] * rows,
        "指标趋势": [0.2] * rows,
    })


class TestValidateMarketCsv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "market"
        self.lock = self.base / "market.lock"
        self.db = self.base / "market.db"

    def tearDown(self):
        self.tmp.cleanup()

    def write_snapshot(self, frame=None):
        return market_store.write_snapshot(
            "20260714",
            sample_market() if frame is None else frame,
            root=self.root,
            lock_path=self.lock,
            min_rows=1,
        )

    def write_raw_snapshot(self, frame):
        path = market_store.snapshot_path("20260714", self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
        return path

    def write_db(self, *, rows=3, meta_rows=None, trade_date="0714"):
        connection = sqlite3.connect(self.db)
        try:
            connection.executescript("""
                CREATE TABLE import_meta (
                    trade_date TEXT PRIMARY KEY,
                    rows_count INTEGER NOT NULL,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE market_snapshot (
                    id INTEGER PRIMARY KEY,
                    trade_date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    industry TEXT NOT NULL DEFAULT '',
                    accuracy REAL,
                    indicator REAL,
                    indicator_history TEXT,
                    raw_json TEXT,
                    row_order INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(trade_date, code)
                );
            """)
            connection.execute(
                "INSERT INTO import_meta VALUES (?, ?, datetime('now'))",
                (trade_date, rows if meta_rows is None else meta_rows),
            )
            connection.executemany(
                """INSERT INTO market_snapshot
                   (trade_date, code, row_order) VALUES (?, ?, ?)""",
                [(trade_date, f"{index:06d}.SZ", index) for index in range(rows)],
            )
            connection.commit()
        finally:
            connection.close()

    def assert_invalid(self, result, message):
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(message in error for error in result["errors"]),
            result["errors"],
        )

    def test_valid_latest_csv_and_db_parity_emit_one_json_object(self):
        self.write_snapshot()
        self.write_db()
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = validate_market_csv.main([
                "--root", str(self.root),
                "--db", str(self.db),
                "--min-rows", "3",
                "--json",
            ])

        lines = output.getvalue().splitlines()
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(lines), 1)
        result = json.loads(lines[0])
        self.assertEqual(
            list(result),
            [
                "ok", "mode", "latest_date", "rows", "csv_files",
                "csv_size_mb", "db_rows", "errors",
            ],
        )
        self.assertEqual(result["mode"], "csv")
        self.assertEqual(result["latest_date"], "20260714")
        self.assertEqual(result["rows"], 3)
        self.assertEqual(result["csv_files"], 1)
        self.assertEqual(result["db_rows"], 3)
        self.assertEqual(result["errors"], [])

    def test_missing_column_is_invalid(self):
        self.write_raw_snapshot(sample_market().drop(columns=["地域"]))

        result = validate_market_csv.validate(self.root, min_rows=1)

        self.assert_invalid(result, "exact columns")

    def test_snapshot_below_minimum_rows_is_invalid(self):
        self.write_raw_snapshot(sample_market(2))

        result = validate_market_csv.validate(self.root, min_rows=3)

        self.assert_invalid(result, "minimum is 3")

    def test_duplicate_codes_are_invalid(self):
        frame = sample_market()
        frame.loc[1, "代码"] = frame.loc[0, "代码"]
        self.write_raw_snapshot(frame)

        result = validate_market_csv.validate(self.root, min_rows=1)

        self.assert_invalid(result, "duplicate codes")

    def test_manifest_hash_mismatch_is_invalid(self):
        self.write_snapshot()
        path = market_store.snapshot_path("20260714", self.root)
        frame = sample_market()
        frame.loc[0, "全称"] = "外部变更"
        frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")

        result = validate_market_csv.validate(self.root, min_rows=1)

        self.assert_invalid(result, "manifest mismatch")

    def test_db_latest_row_mismatch_is_invalid(self):
        self.write_snapshot()
        self.write_db(rows=2)

        result = validate_market_csv.validate(
            self.root, db_path=self.db, min_rows=1
        )

        self.assertEqual(result["db_rows"], 2)
        self.assert_invalid(result, "DB row mismatch")

    def test_stale_tmp_older_than_thirty_minutes_is_invalid(self):
        self.write_snapshot()
        stale = self.root / "2026" / ".20260714.123.tmp"
        stale.write_text("partial", encoding="utf-8")
        old = time.time() - (31 * 60)
        os.utime(stale, (old, old))

        result = validate_market_csv.validate(self.root, min_rows=1)

        self.assert_invalid(result, "stale temporary file")


if __name__ == "__main__":
    unittest.main()
