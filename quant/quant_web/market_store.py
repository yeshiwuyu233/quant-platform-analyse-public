from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKET_ROOT = PROJECT_ROOT / "data" / "market"
LOCK_PATH = PROJECT_ROOT / ".locks" / "market.lock"
MIN_MARKET_ROWS = 4000

MARKET_COLUMNS = [
    "全称", "代码", "行业", "地域", "准确率", "追踪天数",
    "倍数", "指标历史", "近三日涨幅", "今日指标", "指标趋势",
]
TEXT_COLUMNS = ["全称", "代码", "行业", "地域", "倍数", "指标历史", "近三日涨幅"]
FLOAT_COLUMNS = ["准确率", "今日指标", "指标趋势"]
NUMERIC_COLUMNS = FLOAT_COLUMNS + ["追踪天数"]
MANIFEST_COLUMNS = [
    "full_date", "legacy_date", "path", "rows", "sha256",
    "schema_version", "written_at",
]
SCHEMA_VERSION = 1


class StorageMode(str, Enum):
    XLSX = "xlsx"
    SHADOW = "shadow"
    CSV = "csv"


@dataclass(frozen=True)
class SnapshotMeta:
    full_date: str
    legacy_date: str
    path: str
    rows: int
    sha256: str
    schema_version: int
    written_at: str


def get_storage_mode(value: str | None = None) -> StorageMode:
    raw = os.environ.get("MARKET_STORAGE_MODE", "xlsx") if value is None else value
    try:
        return StorageMode(raw.strip().lower())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"invalid MARKET_STORAGE_MODE: {raw!r}") from exc


def validate_full_date(full_date: str) -> str:
    value = str(full_date)
    if not re.fullmatch(r"20\d{6}", value):
        raise ValueError(f"date must be YYYYMMDD: {value!r}")
    pd.Timestamp(value)
    return value


def full_to_legacy(full_date: str) -> str:
    return validate_full_date(full_date)[4:]


def snapshot_path(full_date: str, root: Path = MARKET_ROOT) -> Path:
    value = validate_full_date(full_date)
    return Path(root) / value[:4] / f"{value}.csv"


def canonicalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in MARKET_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    result = df.loc[:, MARKET_COLUMNS].copy()
    for column in TEXT_COLUMNS:
        result[column] = result[column].fillna("").astype(str).str.strip()
    for column in FLOAT_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["追踪天数"] = pd.to_numeric(result["追踪天数"], errors="coerce").astype("Int64")
    return result


@contextlib.contextmanager
def market_lock(*, exclusive: bool, lock_path: Path = LOCK_PATH):
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(handle.fileno(), operation)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_raw_csv(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    if list(raw.columns) != MARKET_COLUMNS:
        raise ValueError(
            f"snapshot must have exact columns in canonical order: {list(raw.columns)}"
        )
    return raw


def _read_csv(path: Path) -> pd.DataFrame:
    return canonicalize_dataframe(_read_raw_csv(path))


def _list_full_dates_unlocked(root: Path = MARKET_ROOT) -> list[str]:
    values = []
    for path in Path(root).glob("20??/20??????.csv"):
        if (
            re.fullmatch(r"20\d{6}", path.stem)
            and path.parent.name == path.stem[:4]
        ):
            values.append(path.stem)
    return sorted(set(values))


def _resolve_date_unlocked(date_key: str, root: Path) -> str:
    key = str(date_key)
    if re.fullmatch(r"20\d{6}", key):
        return validate_full_date(key)
    if not re.fullmatch(r"\d{4}", key):
        raise ValueError(f"date must be YYYYMMDD or MMDD: {key!r}")
    matches = [value for value in _list_full_dates_unlocked(root) if value[4:] == key]
    if len(matches) != 1:
        raise ValueError(f"ambiguous or missing legacy date {key}: {matches}")
    return matches[0]


class SnapshotReader:
    def __init__(self, root: Path):
        self.root = Path(root)

    def list_full_dates(self) -> list[str]:
        return _list_full_dates_unlocked(self.root)

    def read_snapshot(self, date_key: str) -> pd.DataFrame:
        full_date = _resolve_date_unlocked(date_key, self.root)
        return _read_csv(snapshot_path(full_date, self.root))


@contextlib.contextmanager
def market_read_session(root: Path = MARKET_ROOT, lock_path: Path = LOCK_PATH):
    with market_lock(exclusive=False, lock_path=lock_path):
        yield SnapshotReader(Path(root))


def list_full_dates(
    root: Path = MARKET_ROOT,
    lock_path: Path = LOCK_PATH,
) -> list[str]:
    with market_read_session(root, lock_path) as reader:
        return reader.list_full_dates()


def list_legacy_dates(
    root: Path = MARKET_ROOT,
    lock_path: Path = LOCK_PATH,
) -> list[str]:
    return [full_to_legacy(value) for value in list_full_dates(root, lock_path)]


def read_snapshot(
    date_key: str,
    root: Path = MARKET_ROOT,
    lock_path: Path = LOCK_PATH,
) -> pd.DataFrame:
    with market_read_session(root, lock_path) as reader:
        return reader.read_snapshot(date_key)


def compare_frames(left: pd.DataFrame, right: pd.DataFrame) -> None:
    canonical_left = canonicalize_dataframe(left).reset_index(drop=True)
    canonical_right = canonicalize_dataframe(right).reset_index(drop=True)
    pd.testing.assert_frame_equal(
        canonical_left,
        canonical_right,
        check_dtype=False,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def _validated_frame(df: pd.DataFrame, min_rows: int) -> pd.DataFrame:
    try:
        frame = canonicalize_dataframe(df)
    except TypeError as exc:
        raise ValueError("invalid numeric values") from exc
    if len(frame) < min_rows:
        raise ValueError(f"snapshot has {len(frame)} rows; minimum is {min_rows}")
    if frame["代码"].eq("").any():
        raise ValueError("snapshot contains blank codes")
    if frame["代码"].duplicated().any():
        raise ValueError("snapshot contains duplicate codes")
    invalid_numeric = [
        column for column in NUMERIC_COLUMNS
        if frame[column].isna().any()
        or (
            column in FLOAT_COLUMNS
            and frame[column].abs().eq(float("inf")).any()
        )
    ]
    if invalid_numeric:
        raise ValueError(f"snapshot contains invalid numeric values: {invalid_numeric}")
    return frame


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_snapshot_path(full_date: str) -> str:
    return f"{full_date[:4]}/{full_date}.csv"


def _filesystem_written_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(
        timespec="seconds"
    )


def _snapshot_meta_unlocked(
    full_date: str,
    root: Path,
    *,
    min_rows: int,
) -> SnapshotMeta:
    value = validate_full_date(full_date)
    path = snapshot_path(value, root)
    if not path.is_file():
        raise ValueError(f"snapshot missing: {path}")
    frame = _validated_frame(_read_csv(path), min_rows)
    return SnapshotMeta(
        full_date=value,
        legacy_date=full_to_legacy(value),
        path=_relative_snapshot_path(value),
        rows=len(frame),
        sha256=_sha256(path),
        schema_version=SCHEMA_VERSION,
        written_at=_filesystem_written_at(path),
    )


def _read_manifest_unlocked(root: Path) -> list[SnapshotMeta]:
    path = Path(root) / "manifest.csv"
    raw = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    if list(raw.columns) != MANIFEST_COLUMNS:
        raise ValueError(f"manifest must have exact columns: {list(raw.columns)}")
    rows = []
    try:
        for record in raw.to_dict(orient="records"):
            rows.append(SnapshotMeta(
                full_date=validate_full_date(record["full_date"]),
                legacy_date=record["legacy_date"],
                path=record["path"],
                rows=int(record["rows"]),
                sha256=record["sha256"],
                schema_version=int(record["schema_version"]),
                written_at=record["written_at"],
            ))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid manifest: {exc}") from exc
    return rows


def _matching_manifest_meta_unlocked(
    actual: SnapshotMeta,
    root: Path,
) -> SnapshotMeta:
    entries = [
        row for row in _read_manifest_unlocked(root)
        if row.full_date == actual.full_date
    ]
    if len(entries) != 1:
        raise ValueError(
            f"manifest mismatch for {actual.full_date}: found {len(entries)} entries"
        )
    expected = entries[0]
    comparable_fields = (
        "full_date", "legacy_date", "path", "rows", "sha256", "schema_version",
    )
    differences = [
        field for field in comparable_fields
        if getattr(expected, field) != getattr(actual, field)
    ]
    if differences:
        raise ValueError(
            f"manifest mismatch for {actual.full_date}: {differences}"
        )
    return expected


def validate_snapshot(
    full_date: str,
    *,
    root: Path = MARKET_ROOT,
    lock_path: Path = LOCK_PATH,
    min_rows: int = MIN_MARKET_ROWS,
) -> SnapshotMeta:
    with market_lock(exclusive=False, lock_path=lock_path):
        actual = _snapshot_meta_unlocked(full_date, Path(root), min_rows=min_rows)
        if (Path(root) / "manifest.csv").exists():
            return _matching_manifest_meta_unlocked(actual, Path(root))
        return actual


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_csv_temp(df: pd.DataFrame, temp_path: Path) -> None:
    with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        df.to_csv(handle, index=False, lineterminator="\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_manifest_unlocked(rows: list[SnapshotMeta], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.csv"
    temp_path = root / f".manifest.{os.getpid()}.tmp"
    frame = pd.DataFrame([asdict(row) for row in rows], columns=MANIFEST_COLUMNS)
    try:
        _write_csv_temp(frame, temp_path)
        os.replace(temp_path, manifest_path)
        _fsync_directory(root)
    finally:
        temp_path.unlink(missing_ok=True)


def _reject_legacy_collisions(full_dates: list[str]) -> None:
    by_legacy: dict[str, list[str]] = {}
    for full_date in full_dates:
        by_legacy.setdefault(full_to_legacy(full_date), []).append(full_date)
    collisions = [values for values in by_legacy.values() if len(values) > 1]
    if collisions:
        raise ValueError(f"legacy date collision: {collisions}")


def _build_manifest_unlocked(
    root: Path,
    overrides: dict[str, SnapshotMeta] | None = None,
) -> list[SnapshotMeta]:
    full_dates = _list_full_dates_unlocked(root)
    _reject_legacy_collisions(full_dates)
    current = overrides or {}
    return [
        current.get(full_date)
        or _snapshot_meta_unlocked(full_date, root, min_rows=0)
        for full_date in full_dates
    ]


def write_snapshot(
    full_date: str,
    df: pd.DataFrame,
    *,
    root: Path = MARKET_ROOT,
    lock_path: Path = LOCK_PATH,
    min_rows: int = MIN_MARKET_ROWS,
) -> SnapshotMeta:
    value = validate_full_date(full_date)
    root = Path(root)
    with market_lock(exclusive=True, lock_path=lock_path):
        collisions = [
            existing for existing in _list_full_dates_unlocked(root)
            if existing != value and full_to_legacy(existing) == full_to_legacy(value)
        ]
        if collisions:
            raise ValueError(f"legacy date collision: {value} conflicts with {collisions}")

        frame = _validated_frame(df, min_rows)
        destination = snapshot_path(value, root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.parent / f".{value}.{os.getpid()}.tmp"
        try:
            _write_csv_temp(frame, temp_path)
            reread = _validated_frame(_read_csv(temp_path), min_rows)
            compare_frames(frame, reread)
            meta = SnapshotMeta(
                full_date=value,
                legacy_date=full_to_legacy(value),
                path=_relative_snapshot_path(value),
                rows=len(reread),
                sha256=_sha256(temp_path),
                schema_version=SCHEMA_VERSION,
                written_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )
            os.replace(temp_path, destination)
            _fsync_directory(destination.parent)
        finally:
            temp_path.unlink(missing_ok=True)

        rows = _build_manifest_unlocked(root, {value: meta})
        _write_manifest_unlocked(rows, root)
        return meta


def rebuild_manifest(
    *,
    root: Path = MARKET_ROOT,
    lock_path: Path = LOCK_PATH,
) -> list[SnapshotMeta]:
    root = Path(root)
    with market_lock(exclusive=True, lock_path=lock_path):
        rows = _build_manifest_unlocked(root)
        _write_manifest_unlocked(rows, root)
        return rows
