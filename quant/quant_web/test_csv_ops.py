import datetime
import hashlib
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


GUARDIAN = Path("/root/system_guardian.py")
BACKUP = Path("/root/sop/backup.sh")
RESTORE = Path("/root/sop/restore.sh")
REPAIR = Path("/root/sop/repair_xlsx.sh")


class TestCsvHostOperations(unittest.TestCase):
    def test_guardian_selects_validator_and_reports_csv_stats(self):
        source = GUARDIAN.read_text(encoding="utf-8")

        self.assertIn("def read_storage_mode", source)
        self.assertIn("validate_market_csv.py", source)
        self.assertIn("validate_xlsx.py", source)
        self.assertIn('if read_storage_mode() == "csv"', source)
        self.assertIn('"csv_files"', source)
        self.assertIn('"csv_size_mb"', source)
        self.assertIn('"archive_size_mb"', source)
        self.assertNotIn("source quant_web/.env", source)

        validate_block = source.split("def validate_data():", 1)[1].split(
            "# ═", 1
        )[0]
        csv_branch = validate_block.split(
            'if read_storage_mode() == "csv":', 1
        )[1].split("else:", 1)[0]
        self.assertNotIn("Whole Market.xlsx", csv_branch)
        self.assertNotIn("mtime", csv_branch)

    def test_csv_backup_uses_shared_lock_atomic_archive_and_sha(self):
        source = BACKUP.read_text(encoding="utf-8")
        self.assertIn("market-csv.tar.gz.tmp", source)
        self.assertIn("market-csv.tar.gz.sha256", source)
        self.assertIn("flock -s 9", source)
        self.assertIn('LOCK_FILE="${LOCK_FILE:-$PROJECT/.locks/market.lock}"', source)

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            project = base / "project"
            backup_dir = base / "backups"
            lock_file = base / "locks" / "market.lock"
            (project / "quant_web").mkdir(parents=True)
            (project / "quant_web" / ".env").write_text(
                "MARKET_STORAGE_MODE=csv\n", encoding="utf-8"
            )
            snapshot = project / "data" / "market" / "2026" / "20260715.csv"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text("code,name\n000001.SZ,test\n", encoding="utf-8")

            env = os.environ.copy()
            env.update({
                "PROJECT": str(project),
                "BACKUP_DIR": str(backup_dir),
                "LOCK_FILE": str(lock_file),
            })
            subprocess.run(
                ["bash", str(BACKUP), "daily"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            today = datetime.date.today().isoformat()
            target = backup_dir / "daily" / today
            archive = target / "market-csv.tar.gz"
            checksum = target / "market-csv.tar.gz.sha256"
            self.assertTrue(archive.is_file())
            self.assertTrue(checksum.is_file())
            self.assertFalse((target / "market-csv.tar.gz.tmp").exists())
            expected_hash = checksum.read_text(encoding="utf-8").split()[0]
            self.assertEqual(
                hashlib.sha256(archive.read_bytes()).hexdigest(), expected_hash
            )
            with tarfile.open(archive, "r:gz") as bundle:
                self.assertIn("market/2026/20260715.csv", bundle.getnames())

    def test_restore_stages_validates_and_rolls_back_both_stores(self):
        source = RESTORE.read_text(encoding="utf-8")

        self.assertIn("market-csv.tar.gz.sha256", source)
        self.assertIn("mktemp -d", source)
        self.assertIn("validate_market_csv.py", source)
        self.assertIn("import_market_csv.py", source)
        self.assertIn("--all", source)
        self.assertIn("flock -x 9", source)
        self.assertIn("ROLLBACK_MARKET", source)
        self.assertIn("ROLLBACK_DB", source)
        self.assertIn("ROLLBACK_DB_WAL", source)
        self.assertIn("ROLLBACK_DB_SHM", source)
        self.assertIn("repair-artifacts", source)
        self.assertIn("rollback_csv_restore", source)
        self.assertIn("docker exec quant-web", source)
        self.assertNotIn("curl -sf http://localhost:5000/health", source)
        self.assertNotIn('rm -rf "$MARKET_ROOT"', source)

        rollback_block = source.split("rollback_csv_restore()", 1)[1].split(
            "on_csv_restore_error()", 1
        )[0]
        self.assertIn('if [ "$LOCK_HELD" -eq 0 ]', rollback_block)
        self.assertIn("flock -x 9", rollback_block)

        post_swap = source.split('mv "$STAGING/market.db" "$DB"', 1)[1]
        self.assertLess(post_swap.index("flock -u 9"), post_swap.index("docker start quant-web"))

    def test_restore_failure_before_swap_preserves_live_wal_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            project = base / "project"
            backup_dir = base / "backups"
            day_dir = backup_dir / "daily" / "2026-07-15"
            bin_dir = base / "bin"
            (project / "quant_web").mkdir(parents=True)
            day_dir.mkdir(parents=True)
            bin_dir.mkdir()
            (project / "quant_web" / ".env").write_text(
                "MARKET_STORAGE_MODE=csv\n", encoding="utf-8"
            )
            validator = project / "quant_web" / "validate_market_csv.py"
            validator.write_text("raise SystemExit(1)\n", encoding="utf-8")
            (project / "quant_web" / "import_market_csv.py").write_text(
                "raise SystemExit(0)\n", encoding="utf-8"
            )
            market_dir = base / "archive" / "market"
            market_dir.mkdir(parents=True)
            archive = day_dir / "market-csv.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(market_dir, arcname="market")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (day_dir / "market-csv.tar.gz.sha256").write_text(
                f"{digest}  market-csv.tar.gz\n", encoding="utf-8"
            )
            database = project / "market.db"
            wal = project / "market.db-wal"
            shm = project / "market.db-shm"
            database.write_bytes(b"database")
            wal.write_bytes(b"live-wal")
            shm.write_bytes(b"live-shm")
            docker = bin_dir / "docker"
            docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            docker.chmod(0o755)

            env = os.environ.copy()
            env.update({
                "PROJECT": str(project),
                "BACKUP_DIR": str(backup_dir),
                "LOCK_FILE": str(base / "locks" / "market.lock"),
                "PATH": f"{bin_dir}:{env['PATH']}",
            })
            result = subprocess.run(
                ["bash", str(RESTORE), "--date", "2026-07-15"],
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(wal.read_bytes(), b"live-wal")
            self.assertEqual(shm.read_bytes(), b"live-shm")

    def test_csv_repair_only_exports_and_validates_workbook(self):
        source = REPAIR.read_text(encoding="utf-8")
        self.assertIn('if [ "$MODE" = "csv" ]', source)
        csv_branch = source.split('if [ "$MODE" = "csv" ]', 1)[1].split(
            "fi", 1
        )[0]

        self.assertIn("export_market_xlsx.py", csv_branch)
        self.assertIn("validate_workbook.py", csv_branch)
        self.assertNotIn("import_market_xlsx.py", csv_branch)
        self.assertNotIn("cp ", csv_branch)


if __name__ == "__main__":
    unittest.main()
