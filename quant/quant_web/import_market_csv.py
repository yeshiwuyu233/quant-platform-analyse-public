"""Import canonical market CSV snapshots into the SQLite market cache."""

import argparse
import sys
from pathlib import Path

try:
    from . import db_service, market_store
    from .market_import import import_frame
except ImportError:
    import db_service
    import market_store
    from market_import import import_frame


MARKET_ROOT = market_store.MARKET_ROOT


def import_csv_snapshot(full_date, root=MARKET_ROOT, conn=None) -> int:
    owned_connection = conn is None
    connection = db_service.get_db() if owned_connection else conn
    try:
        frame = market_store.read_snapshot(full_date, root=Path(root))
        db_service.init_db(connection)
        count = import_frame(
            connection, market_store.full_to_legacy(full_date), frame
        )
        connection.commit()
        return count
    except Exception:
        connection.rollback()
        raise
    finally:
        if owned_connection:
            connection.close()


def _import_all(root: Path) -> list[tuple[str, int]]:
    full_dates = market_store.list_full_dates(root=root)
    connection = db_service.get_db()
    try:
        db_service.init_db(connection)
        connection.execute("BEGIN")
        connection.execute("DELETE FROM market_snapshot")
        connection.execute("DELETE FROM import_meta")
        results = []
        for full_date in full_dates:
            frame = market_store.read_snapshot(full_date, root=root)
            count = import_frame(
                connection, market_store.full_to_legacy(full_date), frame
            )
            results.append((full_date, count))
        connection.commit()
        return results
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _validate(full_dates: list[str], root: Path) -> list[tuple[str, int]]:
    return [
        (full_date, len(market_store.read_snapshot(full_date, root=root)))
        for full_date in full_dates
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import canonical market CSV snapshots into market.db"
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--date", help="Import one YYYYMMDD snapshot")
    selection.add_argument("--all", action="store_true", help="Replace all snapshots")
    parser.add_argument("--root", type=Path, default=MARKET_ROOT)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    if args.db is not None:
        db_service.DB_PATH = str(args.db)

    try:
        if args.validate_only:
            full_dates = (
                market_store.list_full_dates(root=args.root)
                if args.all
                else [args.date]
            )
            results = _validate(full_dates, args.root)
        elif args.all:
            results = _import_all(args.root)
        else:
            results = [
                (args.date, import_csv_snapshot(args.date, args.root))
            ]
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for full_date, count in results:
        print(f"{full_date}: {count}")
    print(f"snapshots: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
