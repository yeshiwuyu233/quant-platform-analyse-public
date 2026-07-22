import os
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest import mock

import pandas as pd

from quant_web import market_store


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


class TestMarketSchema(unittest.TestCase):
    def test_canonical_columns_and_types(self):
        df = sample_market()[list(reversed(market_store.MARKET_COLUMNS))]
        actual = market_store.canonicalize_dataframe(df)
        self.assertEqual(list(actual.columns), market_store.MARKET_COLUMNS)
        self.assertEqual(actual.loc[0, "代码"], "000000.SZ")
        self.assertEqual(float(actual.loc[0, "准确率"]), 0.7)

    def test_missing_column_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing columns"):
            market_store.canonicalize_dataframe(sample_market().drop(columns=["地域"]))

    def test_dates_are_explicit(self):
        self.assertEqual(market_store.full_to_legacy("20260714"), "0714")
        with self.assertRaisesRegex(ValueError, "YYYYMMDD"):
            market_store.full_to_legacy("0714")

    def test_storage_mode_defaults_to_xlsx(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(market_store.get_storage_mode(), market_store.StorageMode.XLSX)

    def test_invalid_explicit_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "MARKET_STORAGE_MODE"):
            market_store.get_storage_mode("invalid")

    def test_snapshot_path_uses_full_date(self):
        root = Path("/tmp/market-test")
        self.assertEqual(
            market_store.snapshot_path("20260714", root),
            root / "2026" / "20260714.csv",
        )


class TestSnapshotIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "data" / "market"
        self.lock = Path(self.tmp.name) / ".locks" / "market.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, full_date="20260714", frame=None, *, min_rows=1):
        return market_store.write_snapshot(
            full_date,
            sample_market() if frame is None else frame,
            root=self.root,
            lock_path=self.lock,
            min_rows=min_rows,
        )

    def test_utf8_round_trip_and_manifest(self):
        source = sample_market()
        source.loc[0, "全称"] = '测试,"银行"'

        meta = self.write(frame=source)
        actual = market_store.read_snapshot(
            "20260714", root=self.root, lock_path=self.lock
        )

        self.assertEqual(meta.rows, 3)
        self.assertEqual(actual.loc[0, "全称"], '测试,"银行"')
        self.assertTrue((self.root / "manifest.csv").exists())

    def test_csv_has_exact_header_encoding_and_line_endings(self):
        self.write()
        content = market_store.snapshot_path("20260714", self.root).read_bytes()

        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", content)
        header = content.decode("utf-8-sig").splitlines()[0]
        self.assertEqual(header, ",".join(market_store.MARKET_COLUMNS))

    def test_manifest_has_exact_schema_and_snapshot_hash(self):
        meta = self.write()
        manifest = pd.read_csv(
            self.root / "manifest.csv", dtype=str, keep_default_na=False
        )
        snapshot = market_store.snapshot_path("20260714", self.root)

        self.assertEqual(list(manifest.columns), market_store.MANIFEST_COLUMNS)
        self.assertEqual(manifest.loc[0, "path"], "2026/20260714.csv")
        self.assertEqual(manifest.loc[0, "sha256"], sha256(snapshot.read_bytes()).hexdigest())
        self.assertEqual(meta.sha256, manifest.loc[0, "sha256"])

    def test_legacy_key_resolves_when_unique(self):
        self.write()

        actual = market_store.read_snapshot(
            "0714", root=self.root, lock_path=self.lock
        )

        self.assertEqual(len(actual), 3)

    def test_lists_full_and_legacy_dates_in_order(self):
        self.write("20260715")
        self.write("20260714")

        self.assertEqual(
            market_store.list_full_dates(root=self.root, lock_path=self.lock),
            ["20260714", "20260715"],
        )
        self.assertEqual(
            market_store.list_legacy_dates(root=self.root, lock_path=self.lock),
            ["0714", "0715"],
        )

    def test_list_ignores_snapshot_in_wrong_year_directory(self):
        misplaced = self.root / "2027" / "20260714.csv"
        misplaced.parent.mkdir(parents=True)
        sample_market().to_csv(misplaced, index=False, encoding="utf-8-sig")

        self.assertEqual(
            market_store.list_full_dates(root=self.root, lock_path=self.lock),
            [],
        )

    def test_read_session_supports_multiple_unlocked_operations(self):
        self.write()

        with market_store.market_read_session(self.root, self.lock) as reader:
            self.assertEqual(reader.list_full_dates(), ["20260714"])
            self.assertEqual(len(reader.read_snapshot("0714")), 3)

    def test_write_rejects_cross_year_legacy_collision(self):
        self.write()

        with self.assertRaisesRegex(ValueError, "legacy date collision"):
            self.write("20270714")

        self.assertFalse(market_store.snapshot_path("20270714", self.root).exists())

    def test_reader_rejects_preexisting_cross_year_collision(self):
        self.write()
        corrupt_path = market_store.snapshot_path("20270714", self.root)
        corrupt_path.parent.mkdir(parents=True)
        sample_market().to_csv(corrupt_path, index=False, encoding="utf-8-sig")

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            market_store.read_snapshot(
                "0714", root=self.root, lock_path=self.lock
            )

    def test_failed_validation_preserves_existing_file(self):
        self.write()
        path = market_store.snapshot_path("20260714", self.root)
        before = path.read_bytes()

        with self.assertRaisesRegex(ValueError, "minimum"):
            self.write(frame=sample_market(1), min_rows=2)

        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_failed_snapshot_replace_preserves_existing_file_and_manifest(self):
        self.write()
        path = market_store.snapshot_path("20260714", self.root)
        manifest_path = self.root / "manifest.csv"
        before_snapshot = path.read_bytes()
        before_manifest = manifest_path.read_bytes()
        changed = sample_market()
        changed.loc[0, "全称"] = "变更名称"

        with mock.patch.object(
            market_store.os, "replace", side_effect=OSError("replace failed")
        ):
            with self.assertRaisesRegex(OSError, "replace failed"):
                self.write(frame=changed)

        self.assertEqual(path.read_bytes(), before_snapshot)
        self.assertEqual(manifest_path.read_bytes(), before_manifest)
        self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_failed_manifest_replace_preserves_existing_manifest(self):
        self.write()
        manifest_path = self.root / "manifest.csv"
        before_manifest = manifest_path.read_bytes()
        changed = sample_market()
        changed.loc[0, "全称"] = "变更名称"
        real_replace = os.replace

        def fail_manifest(source, destination):
            if Path(destination) == manifest_path:
                raise OSError("manifest replace failed")
            return real_replace(source, destination)

        with mock.patch.object(market_store.os, "replace", side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, "manifest replace failed"):
                self.write(frame=changed)

        self.assertEqual(manifest_path.read_bytes(), before_manifest)
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_successful_write_fsyncs_files_and_parent_directories(self):
        with mock.patch.object(
            market_store.os, "fsync", wraps=os.fsync
        ) as fsync_mock:
            self.write()

        self.assertGreaterEqual(fsync_mock.call_count, 4)

    def test_manifest_can_be_rebuilt(self):
        self.write()
        (self.root / "manifest.csv").unlink()

        rows = market_store.rebuild_manifest(root=self.root, lock_path=self.lock)

        self.assertEqual(rows[0].full_date, "20260714")
        self.assertTrue((self.root / "manifest.csv").exists())

    def test_manifest_rebuild_replaces_stale_entries(self):
        self.write()
        manifest_path = self.root / "manifest.csv"
        manifest_path.write_text("broken\nvalue\n", encoding="utf-8")

        rows = market_store.rebuild_manifest(root=self.root, lock_path=self.lock)
        manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)

        self.assertEqual([row.full_date for row in rows], ["20260714"])
        self.assertEqual(list(manifest.columns), market_store.MANIFEST_COLUMNS)

    def test_validate_snapshot_rejects_duplicate_codes(self):
        corrupt = sample_market()
        corrupt.loc[1, "代码"] = corrupt.loc[0, "代码"]
        path = market_store.snapshot_path("20260714", self.root)
        path.parent.mkdir(parents=True)
        corrupt.to_csv(path, index=False, encoding="utf-8-sig")

        with self.assertRaisesRegex(ValueError, "duplicate codes"):
            market_store.validate_snapshot(
                "20260714", root=self.root, lock_path=self.lock, min_rows=1
            )

    def test_write_and_validation_reject_blank_codes(self):
        corrupt = sample_market()
        corrupt.loc[1, "代码"] = "  "

        with self.assertRaisesRegex(ValueError, "blank codes"):
            self.write(frame=corrupt)

        path = market_store.snapshot_path("20260714", self.root)
        path.parent.mkdir(parents=True)
        corrupt.to_csv(path, index=False, encoding="utf-8-sig")
        with self.assertRaisesRegex(ValueError, "blank codes"):
            market_store.validate_snapshot(
                "20260714", root=self.root, lock_path=self.lock, min_rows=1
            )

    def test_write_and_validation_reject_invalid_numeric_values(self):
        corrupt = sample_market()
        corrupt["准确率"] = corrupt["准确率"].astype(object)
        corrupt.loc[1, "准确率"] = "invalid"

        with self.assertRaisesRegex(ValueError, "invalid numeric"):
            self.write(frame=corrupt)

        path = market_store.snapshot_path("20260714", self.root)
        path.parent.mkdir(parents=True)
        corrupt.to_csv(path, index=False, encoding="utf-8-sig")
        with self.assertRaisesRegex(ValueError, "invalid numeric"):
            market_store.validate_snapshot(
                "20260714", root=self.root, lock_path=self.lock, min_rows=1
            )

    def test_write_rejects_nonfinite_numeric_values(self):
        corrupt = sample_market()
        corrupt.loc[1, "准确率"] = float("inf")

        with self.assertRaisesRegex(ValueError, "invalid numeric"):
            self.write(frame=corrupt)

    def test_read_and_validation_reject_noncanonical_raw_headers(self):
        path = market_store.snapshot_path("20260714", self.root)
        path.parent.mkdir(parents=True)
        variants = {
            "extra": sample_market().assign(extra="value"),
            "reordered": sample_market()[list(reversed(market_store.MARKET_COLUMNS))],
            "missing": sample_market().drop(columns=["地域"]),
        }

        for label, corrupt in variants.items():
            with self.subTest(label=label):
                corrupt.to_csv(path, index=False, encoding="utf-8-sig")
                with self.assertRaisesRegex(ValueError, "exact columns"):
                    market_store.read_snapshot(
                        "20260714", root=self.root, lock_path=self.lock
                    )
                with self.assertRaisesRegex(ValueError, "exact columns"):
                    market_store.validate_snapshot(
                        "20260714", root=self.root, lock_path=self.lock, min_rows=1
                    )

    def test_validate_snapshot_detects_manifest_hash_mismatch(self):
        self.write()
        path = market_store.snapshot_path("20260714", self.root)
        changed = sample_market()
        changed.loc[0, "全称"] = "外部变更"
        changed.to_csv(
            path, index=False, encoding="utf-8-sig", lineterminator="\n"
        )

        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            market_store.validate_snapshot(
                "20260714", root=self.root, lock_path=self.lock, min_rows=1
            )

    def test_read_snapshot_does_not_require_manifest(self):
        self.write()
        (self.root / "manifest.csv").unlink()

        actual = market_store.read_snapshot(
            "20260714", root=self.root, lock_path=self.lock
        )

        self.assertEqual(len(actual), 3)


class TestFrameComparison(unittest.TestCase):
    def test_compare_frames_canonicalizes_order_and_numeric_types(self):
        left = sample_market()
        right = left[list(reversed(market_store.MARKET_COLUMNS))].astype(str)

        market_store.compare_frames(left, right)

    def test_compare_frames_allows_tiny_float_difference(self):
        left = sample_market()
        right = sample_market()
        right.loc[0, "准确率"] += 1e-13

        market_store.compare_frames(left, right)

    def test_compare_frames_rejects_meaningful_difference(self):
        left = sample_market()
        right = sample_market()
        right.loc[0, "准确率"] += 0.01

        with self.assertRaises(AssertionError):
            market_store.compare_frames(left, right)


if __name__ == "__main__":
    unittest.main()
