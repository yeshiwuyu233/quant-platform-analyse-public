"""Index history fetch/cache utilities.

Uses Eastmoney's public kline endpoint directly because the akshare wrapper can
be unstable in this deployment environment.
"""
from __future__ import annotations

import csv
import os
import time
from typing import Iterable

import requests


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_CACHE_DIR = os.path.join(PROJECT_ROOT, "index_cache")

EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
INDEX_SYMBOLS = {
    "sh000001": {"name": "上证指数", "secid": "1.000001"},
    "sh000300": {"name": "沪深300", "secid": "1.000300"},
    "sh000852": {"name": "中证1000", "secid": "1.000852"},
    "sh000985": {"name": "中证全指", "secid": "1.000985"},
    "sz399001": {"name": "深证成指", "secid": "0.399001"},
    "sz399006": {"name": "创业板指", "secid": "0.399006"},
}


def parse_eastmoney_klines(payload: dict) -> list[dict]:
    """Parse Eastmoney kline JSON into normalized rows."""
    klines = ((payload or {}).get("data") or {}).get("klines") or []
    rows = []
    for item in klines:
        parts = str(item).split(",")
        if len(parts) < 8:
            continue
        date_raw, open_, close, high, low, volume, amount, pct_chg = parts[:8]
        rows.append({
            "date": date_raw.replace("-", ""),
            "open": float(open_),
            "close": float(close),
            "high": float(high),
            "low": float(low),
            "volume": float(volume),
            "amount": float(amount),
            "pct_chg": float(pct_chg),
        })
    return rows


def parse_tencent_klines(payload: dict, symbol: str) -> list[dict]:
    """Parse Tencent index kline JSON into normalized rows."""
    day_rows = (((payload or {}).get("data") or {}).get(symbol) or {}).get("day") or []
    rows = []
    prev_close = None
    for item in day_rows:
        if len(item) < 6:
            continue
        date_raw, open_, close, high, low, volume = item[:6]
        close_f = float(close)
        pct_chg = 0.0 if prev_close in (None, 0) else (close_f / prev_close - 1) * 100
        rows.append({
            "date": str(date_raw).replace("-", ""),
            "open": float(open_),
            "close": close_f,
            "high": float(high),
            "low": float(low),
            "volume": float(volume),
            "amount": 0.0,
            "pct_chg": pct_chg,
        })
        prev_close = close_f
    return rows


def fetch_index_history(symbol: str, beg: str = "19900101", end: str = "20500101",
                        retries: int = 3, timeout: int = 15) -> list[dict]:
    """Fetch index daily history from Eastmoney.

    Args:
        symbol: one of INDEX_SYMBOLS keys, e.g. sh000001.
        beg/end: YYYYMMDD date bounds.
    """
    if symbol not in INDEX_SYMBOLS:
        raise ValueError(f"Unsupported index symbol: {symbol}")

    params = {
        "secid": INDEX_SYMBOLS[symbol]["secid"],
        "fields1": "f1,f2,f3,f4,f5",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101",
        "fqt": "0",
        "beg": beg,
        "end": end,
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }

    last_exc = None
    for attempt in range(retries):
        try:
            response = requests.get(
                EASTMONEY_KLINE_URL,
                params=params,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            rows = parse_eastmoney_klines(response.json())
            if rows:
                return rows
            last_exc = RuntimeError(f"Eastmoney returned empty kline data for {symbol}")
        except Exception as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch index history for {symbol}: {last_exc}")


def fetch_index_history_tencent(symbol: str, beg: str = "19900101", end: str = "20500101",
                                retries: int = 3, timeout: int = 15) -> list[dict]:
    """Fetch index daily history from Tencent as a fallback source."""
    if symbol not in INDEX_SYMBOLS:
        raise ValueError(f"Unsupported index symbol: {symbol}")

    beg_dash = f"{beg[:4]}-{beg[4:6]}-{beg[6:8]}"
    end_dash = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
    params = {"param": f"{symbol},day,{beg_dash},{end_dash},640"}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://gu.qq.com/",
    }

    last_exc = None
    for attempt in range(retries):
        try:
            response = requests.get(
                TENCENT_KLINE_URL,
                params=params,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            rows = parse_tencent_klines(response.json(), symbol)
            if rows:
                return rows
            last_exc = RuntimeError(f"Tencent returned empty kline data for {symbol}")
        except Exception as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch Tencent index history for {symbol}: {last_exc}")


def fetch_index_history_robust(symbol: str, beg: str = "20200101", end: str = "20500101") -> list[dict]:
    """Fetch index history using Eastmoney first, Tencent fallback second."""
    try:
        return fetch_index_history(symbol, beg=beg, end=end)
    except Exception:
        return fetch_index_history_tencent(symbol, beg=beg, end=end)


def cache_path(symbol: str, cache_dir: str = INDEX_CACHE_DIR) -> str:
    return os.path.join(cache_dir, f"{symbol}.csv")


def write_cache(symbol: str, rows: Iterable[dict], cache_dir: str = INDEX_CACHE_DIR) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    path = cache_path(symbol, cache_dir)
    fieldnames = ["date", "open", "close", "high", "low", "volume", "amount", "pct_chg"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


def read_cache(symbol: str, cache_dir: str = INDEX_CACHE_DIR) -> list[dict]:
    path = cache_path(symbol, cache_dir)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "date": row["date"],
                "open": float(row["open"]),
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "volume": float(row["volume"]),
                "amount": float(row["amount"]),
                "pct_chg": float(row["pct_chg"]),
            })
    return rows


def update_index_cache(symbols: Iterable[str] | None = None, beg: str = "20200101",
                       end: str = "20500101", cache_dir: str = INDEX_CACHE_DIR) -> dict[str, int]:
    """Fetch and cache supported indexes. Returns symbol -> row count."""
    result = {}
    for symbol in symbols or INDEX_SYMBOLS.keys():
        rows = fetch_index_history_robust(symbol, beg=beg, end=end)
        write_cache(symbol, rows, cache_dir=cache_dir)
        result[symbol] = len(rows)
    return result


def window_return(rows: list[dict], start_date: str, end_date: str) -> float | None:
    """Return close-to-close return between two YYYYMMDD dates."""
    by_date = {str(row["date"]): row for row in rows}
    start = by_date.get(start_date)
    end = by_date.get(end_date)
    if not start or not end:
        return None
    start_close = float(start["close"])
    if start_close == 0:
        return None
    return float(end["close"]) / start_close - 1


if __name__ == "__main__":
    counts = update_index_cache()
    for symbol, count in counts.items():
        print(f"{symbol} {INDEX_SYMBOLS[symbol]['name']} {count}")
