"""Validate canonical CSV market storage and optional SQLite parity."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

try:
    from . import db_service, market_store
except ImportError:
    import db_service
    import market_store


STALE_TMP_SECONDS = 30 * 60


def _snapshot_paths(root: Path) -> list[Path]:
    return [
        market_store.snapshot_path(full_date, root)
        for full_date in market_store.list_full_dates(root=root)
    ]


def _stale_tmp_errors(root: Path, now: float) -> list[str]:
    errors = []
    for path in sorted(root.rglob("*.tmp")) if root.is_dir() else []:
        try:
            if now - path.stat().st_mtime > STALE_TMP_SECONDS:
                errors.append(f"stale temporary file: {path.relative_to(root)}")
        except OSError as exc:
            errors.append(f"temporary file stat failed: {path}: {exc}")
    return errors


def _database_errors(
    db_path: Path,
    latest_date: str,
    csv_rows: int,
) -> tuple[int, list[str]]:
    previous_db_path = db_service.DB_PATH
    try:
        db_service.DB_PATH = str(db_path)
        status = db_service.get_cache_status()
    finally:
        db_service.DB_PATH = previous_db_path

    db_rows = int(status.get("latest_actual_rows") or 0)
    errors = []
    if not status.get("db_exists"):
        errors.append(f"database missing: {db_path}")
        return db_rows, errors
    if status.get("error"):
        errors.append(f"database error: {status['error']}")
        return db_rows, errors

    expected_date = market_store.full_to_legacy(latest_date)
    actual_date = status.get("latest_trade_date")
    if actual_date != expected_date:
        errors.append(
            f"DB latest date mismatch: CSV={expected_date} DB={actual_date}"
        )
    if db_rows != csv_rows:
        errors.append(f"DB row mismatch: CSV={csv_rows} DB={db_rows}")

    metadata_rows = int(status.get("latest_rows_count") or 0)
    if metadata_rows != db_rows:
        errors.append(
            f"DB metadata row mismatch: metadata={metadata_rows} actual={db_rows}"
        )
    return db_rows, errors


def validate(
    root: Path,
    *,
    db_path: Path | None = None,
    min_rows: int = market_store.MIN_MARKET_ROWS,
) -> dict:
    root = Path(root)
    result = {
        "ok": False,
        "mode": "csv",
        "latest_date": None,
        "rows": 0,
        "csv_files": 0,
        "csv_size_mb": 0.0,
        "db_rows": None,
        "errors": [],
    }

    try:
        paths = _snapshot_paths(root)
        result["csv_files"] = len(paths)
        result["csv_size_mb"] = round(
            sum(path.stat().st_size for path in paths) / (1024 * 1024), 2
        )
        if not paths:
            result["errors"].append(f"no CSV snapshots found: {root}")
        else:
            latest_date = paths[-1].stem
            result["latest_date"] = latest_date
            meta = market_store.validate_snapshot(
                latest_date,
                root=root,
                min_rows=min_rows,
            )
            result["rows"] = meta.rows
    except Exception as exc:
        result["errors"].append(str(exc))

    result["errors"].extend(_stale_tmp_errors(root, time.time()))

    if db_path is not None:
        if result["latest_date"] is None:
            result["db_rows"] = 0
            result["errors"].append("database parity unavailable without a CSV snapshot")
        elif result["rows"]:
            try:
                db_rows, errors = _database_errors(
                    Path(db_path), result["latest_date"], result["rows"]
                )
                result["db_rows"] = db_rows
                result["errors"].extend(errors)
            except Exception as exc:
                result["db_rows"] = 0
                result["errors"].append(f"database validation failed: {exc}")

    result["errors"] = sorted(result["errors"])
    result["ok"] = not result["errors"]
    return result


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate canonical CSV market storage"
    )
    parser.add_argument("--root", type=Path, default=market_store.MARKET_ROOT)
    parser.add_argument("--db", type=Path, help="Optional SQLite cache path")
    parser.add_argument(
        "--min-rows",
        type=_positive_int,
        default=market_store.MIN_MARKET_ROWS,
    )
    parser.add_argument("--json", action="store_true", help="Emit one JSON object")
    args = parser.parse_args(argv)

    result = validate(args.root, db_path=args.db, min_rows=args.min_rows)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print("CSV market storage: " + ("OK" if result["ok"] else "INVALID"))
        for key in (
            "latest_date", "rows", "csv_files", "csv_size_mb", "db_rows"
        ):
            print(f"{key}: {result[key]}")
        for error in result["errors"]:
            print(f"error: {error}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
