"""
数据访问层 — 统一管理 xlsx/JSON 文件读取与缓存。
"""
import glob
import csv
import json
import os
import re
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from .report_paths import glob_reports, latest_report, resolve_report
except Exception:
    from report_paths import glob_reports, latest_report, resolve_report

try:
    from . import db_service as market_db
except Exception:
    try:
        import db_service as market_db
    except Exception:
        market_db = None

try:
    from . import market_store
except Exception:
    import market_store

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 轻量 TTL 缓存 ──

def ttl_cache(seconds: int):
    """Simple TTL cache decorator — no external dependencies."""
    def decorator(func):
        cache = {}

        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = datetime.now().timestamp()
            if key in cache:
                val, ts = cache[key]
                if now - ts < seconds:
                    return val
            result = func(*args, **kwargs)
            cache[key] = (result, now)
            return result
        return wrapper
    return decorator

# 追踪表列位置 (Excel col 0 是 index)
_COL = {
    "date": 1, "acc_08": 2, "acc_12": 3, "all": 4,
    "nc": 5, "t3": 6, "cold_alpha": 7,
    "cold_count": 8, "top3_count": 9,
    "next_08": 10, "next_10": 11, "next_12": 12,
}


# ── 底层 IO ──

def _latest(pattern):
    return latest_report(pattern)


def _read_safe(path, sheet_name=0, **kwargs):
    try:
        return pd.read_excel(path, sheet_name=sheet_name, **kwargs)
    except Exception:
        return None


def _table(df):
    if df is None or df.empty:
        return None

    def clean(v):
        if pd.isna(v):
            return ""
        if isinstance(v, float) and v == int(v):
            return int(v)
        return v

    rows = [{k: clean(v) for k, v in row.items()}
            for row in df.to_dict(orient="records")]
    return {"cols": list(rows[0].keys()), "rows": rows}


def _first_row(df):
    if df is None or df.empty:
        return None
    clean = df.dropna(how="all")
    return clean.iloc[0] if not clean.empty else None


def _parse_pct(s):
    if pd.isna(s) or not str(s).strip():
        return None
    m = re.search(r"([-+]?\d+\.?\d*)%", str(s))
    return float(m.group(1)) if m else None


def _parse_ratio(s):
    if pd.isna(s) or not str(s).strip():
        return None, None
    m = re.search(r"\((\d+)/(\d+)\)", str(s))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


# ── 公开工具函数（供 batch 脚本复用） ──

def df_to_table(df):
    """Convert DataFrame → {{cols, rows}} for JSON serialization."""
    return _table(df)


def parse_pct(s):
    """Extract percentage value from string like '49.25%(33/67)' → 49.25"""
    return _parse_pct(s)


def parse_ratio(s):
    """Extract (success, total) from string like '49.25%(33/67)' → (33, 67)"""
    return _parse_ratio(s)


def native_type(v):
    """Convert numpy types to native Python types for JSON serialization."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v) if not np.isnan(v) else None
    return v


def get_adjacent_dates(date, all_dates):
    """Return (prev_date, next_date) for date navigation."""
    if not all_dates or date not in all_dates:
        return None, None
    idx = all_dates.index(date)
    prev_date = all_dates[idx - 1] if idx > 0 else None
    next_date = all_dates[idx + 1] if idx < len(all_dates) - 1 else None
    return prev_date, next_date


def _to_scalar(v):
    if pd.isna(v):
        return None
    if isinstance(v, (int, float)):
        return int(v) if v == int(v) else v
    return v


def _mmdd_label(mmdd):
    if not mmdd or len(mmdd) != 4:
        return mmdd
    return f"{mmdd[:2]}/{mmdd[2:]}"


def _xlsx_to_json(path):
    if not path:
        return None
    return path.rsplit('.', 1)[0] + '.json'


def _try_json(path):
    """Read JSON report if available; returns (full_dict, True) or (None, False)."""
    jp = _xlsx_to_json(path)
    if jp and os.path.exists(jp):
        try:
            with open(jp, 'r', encoding='utf-8') as f:
                return json.load(f), True
        except Exception:
            pass
    return None, False


def _read_tracking_from_xlsx(path):
    """Fallback xlsx reading for tracking data."""
    df = _read_safe(path, sheet_name="0.每日追踪总表", header=[0, 1])
    row = _first_row(df)
    if row is None:
        return None

    def v(pos):
        try:
            return _to_scalar(row.iloc[pos])
        except Exception:
            return None

    date_val = v(_COL["date"])
    full = str(int(float(date_val))) if date_val is not None else ""
    date_str = full[4:] if len(full) >= 8 else full

    return {
        "date_raw": date_str,
        "date": _mmdd_label(date_str),
        "acc_08_raw": v(_COL["acc_08"]),
        "acc_12_raw": v(_COL["acc_12"]),
        "all_raw": v(_COL["all"]),
        "nc_raw": v(_COL["nc"]),
        "t3_raw": v(_COL["t3"]),
        "cold_alpha_raw": v(_COL["cold_alpha"]),
        "cold_stock_count": v(_COL["cold_count"]),
        "top3_stock_count": v(_COL["top3_count"]),
        "next_08": v(_COL["next_08"]),
        "next_10": v(_COL["next_10"]),
        "next_12": v(_COL["next_12"]),
    }


def _read_tracking_from_path(path):
    if not path:
        return None

    # Try JSON first
    report, ok = _try_json(path)
    if ok and report and 'tracking' in report:
        return report['tracking']

    return _read_tracking_from_xlsx(path)


# -- SQLite market cache helpers (phase 1: read-through cache) --

def _db_available_dates() -> list[str]:
    if not market_db:
        return []
    try:
        return market_db.get_market_dates()
    except Exception:
        return []


def _db_read_market_sheet(date: str):
    if not market_db or not date:
        return None
    try:
        df = market_db.read_market_sheet(date)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if '准确率' in df.columns:
        df['准确率'] = pd.to_numeric(df['准确率'], errors='coerce')
    if '今日指标' in df.columns:
        df['今日指标'] = pd.to_numeric(df['今日指标'], errors='coerce')
    return df


def _db_market_count(date: str) -> Optional[int]:
    if not market_db or not date:
        return None
    try:
        return market_db.count_market_rows(date)
    except Exception:
        return None


def _db_industries(date: str) -> list[str]:
    if not market_db or not date:
        return []
    try:
        return market_db.get_industries(date)
    except Exception:
        return []


# ── 公开 API ──

@ttl_cache(60)
def get_available_dates() -> list[str]:
    """返回所有交易日日期列表；优先 SQLite，缺失时回退 CSV。"""
    db_dates = _db_available_dates()
    if db_dates:
        return db_dates

    try:
        return market_store.list_legacy_dates()
    except Exception:
        return []


@ttl_cache(30)
def get_latest_tracking() -> Optional[dict[str, Any]]:
    return _read_tracking_from_path(_latest("*量化复盘报告*.xlsx"))


@ttl_cache(60)
def get_tracking_data(date: str) -> Optional[dict[str, Any]]:
    exact = resolve_report(f"{date}量化复盘报告.xlsx")
    if os.path.exists(exact):
        return _read_tracking_from_path(exact)
    files = glob_reports(f"*{date}*量化复盘报告*")
    if files:
        return _read_tracking_from_path(max(files, key=os.path.getmtime))
    return None


@ttl_cache(60)
def get_backtest_sheets(date: Optional[str] = None) -> dict[str, Any]:
    """读取指定日期的复盘报告。date=None 则取最新。"""
    path = None
    if date:
        exact = resolve_report(f"{date}量化复盘报告.xlsx")
        if os.path.exists(exact):
            path = exact
        else:
            files = glob_reports(f"*{date}*量化复盘报告*")
            if files:
                path = max(files, key=os.path.getmtime)
    if not path:
        path = _latest("*量化复盘报告*.xlsx")
    if not path:
        return {}

    # Try JSON first
    report, ok = _try_json(path)
    if ok and report and 'sheets' in report:
        return {k: v for k, v in report['sheets'].items() if v is not None}

    # Fall back to xlsx
    raw = {
        "backtest": _read_safe(path, "1.回测明细(跨日合并)"),
        "win_rates": _read_safe(path, "2.三阶胜率全景对比"),
        "industry_dist": _read_safe(path, "3.回测行业分布(含名单)"),
        "hot_split": _read_safe(path, "4.并列热门拆分对比"),
        "today_dist": _read_safe(path, "5.当日最新策略分布"),
        "today_industry": _read_safe(path, "6.当日最新行业热度"),
    }
    return {k: _table(v) for k, v in raw.items() if _table(v) is not None}


@ttl_cache(60)
def get_available_weekly_dates() -> list[str]:
    """返回所有礼拜攻势报告对应的 MMDD 日期列表。"""
    dates: set[str] = set()
    for f in glob_reports("*的选股策略礼拜攻势.xlsx"):
        d = os.path.basename(f)[:4]
        if d.isdigit():
            dates.add(d)
    return sorted(dates)


def _extract_trend_record(mmdd, summary_rows):
    """从 summary 行列表提取单条趋势记录。"""
    record = {"date": _mmdd_label(mmdd), "date_raw": mmdd}
    for row in summary_rows:
        group = row.get("策略分组", "")
        suffix = group.replace("指标大于", "gt_").replace(".", "_")
        count = int(row.get("入选股票数", 0))
        ret_str = str(row.get("平均持仓回报", "0%"))
        win_str = str(row.get("策略胜率(>0%)", "0%"))

        try:
            ret_val = float(ret_str.replace("%", ""))
        except ValueError:
            ret_val = 0.0
        try:
            win_val = float(win_str.replace("%", ""))
        except ValueError:
            win_val = 0.0

        record[f"{suffix}_回报"] = ret_val
        record[f"{suffix}_胜率"] = win_val
        record[f"{suffix}_股票数"] = count
    return record


@ttl_cache(120)
def get_weekly_trend_data() -> list[dict[str, Any]]:
    """聚合所有日期的礼拜攻势数据，生成趋势图用时间序列。
    优先读 batch_weekly.py 生成的缓存文件 weekly_trend.json。
    """
    cache_path = os.path.join(PROJECT_ROOT, 'weekly_trend.json')
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    # 缓存不存在时回退：逐文件解析
    records = []
    files = sorted(glob_reports("*的选股策略礼拜攻势.json"))
    for f in files:
        base = os.path.basename(f)
        mmdd = base[:4]
        if not mmdd.isdigit():
            continue
        try:
            with open(f, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
        except Exception:
            continue

        if 'standard' in data:
            std_summary = data.get('standard', {}).get('summary', [])
            if std_summary:
                records.append(_extract_trend_record(mmdd, std_summary))
        else:
            summary = data.get("整体回报总结")
            if not summary or not summary.get("rows"):
                continue
            records.append(_extract_trend_record(mmdd, summary["rows"]))

    return records


@ttl_cache(60)
def get_weekly_data(date: Optional[str] = None) -> dict[str, Any]:
    path = None
    if date:
        exact = resolve_report(f"{date}的选股策略礼拜攻势.xlsx")
        if os.path.exists(exact):
            path = exact
    if not path:
        path = _latest("*选股策略礼拜攻势*.xlsx")
    if not path:
        return {}

    # Try JSON first
    report, ok = _try_json(path)
    if ok and report:
        return report

    # Fall back to xlsx
    try:
        xls = pd.ExcelFile(path)
    except Exception:
        return {}
    sheets = {}
    for name in xls.sheet_names:
        t = _table(_read_safe(path, name))
        if t:
            sheets[name] = t
    return sheets


def extract_weekly_view(report, strategy='standard'):
    """从双轨 report 中提取指定策略的 sheets + chart_data。

    支持新旧两种 JSON 格式，返回 (sheets: dict, chart_data: list | None).
    """
    if not report:
        return {}, None

    # ── 新格式：嵌套结构 ──
    if 'standard' in report:
        strat = report.get(strategy, report.get('standard', {}))
        sheets = strat.get('sheets', {})
        chart_data = strat.get('summary', [])
        return sheets, chart_data

    # ── 旧格式：扁平结构 ──
    chart_data = None
    if "整体回报总结" in report:
        chart_data = report["整体回报总结"].get("rows", [])
    return report, chart_data


def _weighted_weekly_return(summary_rows: list[dict[str, Any]]) -> tuple[Optional[float], int]:
    """Return weighted average weekly return as decimal plus total valid count."""
    weighted_sum = 0.0
    total = 0
    for row in summary_rows or []:
        ret = _parse_pct(row.get('平均持仓回报'))
        if ret is None:
            continue
        try:
            count = int(row.get('有效收益股票数') or row.get('入选股票数') or 0)
        except Exception:
            count = 0
        if count <= 0:
            continue
        weighted_sum += (ret / 100.0) * count
        total += count
    if total <= 0:
        return None, 0
    return weighted_sum / total, total


def _standard_gt1_summary(report: dict[str, Any]) -> tuple[Optional[float], int]:
    for row in (report.get('standard') or {}).get('summary', []):
        group = str(row.get('策略分组') or '')
        if group == '指标大于1.0' or '1.0' in group:
            ret = _parse_pct(row.get('平均持仓回报'))
            try:
                count = int(row.get('入选股票数') or 0)
            except Exception:
                count = 0
            return (ret / 100.0 if ret is not None else None), count
    return None, 0


def _pct_value(v: Optional[float]) -> Optional[float]:
    return round(v * 100.0, 4) if v is not None else None


def _index_close(index_by_date: dict[str, dict[str, Any]], mmdd: str) -> Optional[float]:
    row = index_by_date.get(f"2026{mmdd}")
    if not row:
        return None
    try:
        close = float(row.get('close'))
    except Exception:
        return None
    return close if close > 0 else None


def _build_index_sleeve_nav(
    signal_dates: list[str],
    index_by_date: dict[str, dict[str, Any]],
    date_sequence: list[str],
    hold_days: int = 5,
    sleeve_weight: float = 0.2,
) -> dict[str, tuple[float, float]]:
    """Build benchmark NAV by applying the same rolling sleeve schedule.

    Each signal opens one index sleeve after the signal date and holds it for
    the next ``hold_days`` trading days. This avoids compounding overlapping
    5-day benchmark windows as if they were independent full-capital trades.
    """
    if not signal_dates or not date_sequence:
        return {}

    date_pos = {d: i for i, d in enumerate(date_sequence)}
    signal_positions = [date_pos[d] for d in signal_dates if d in date_pos]
    if not signal_positions:
        return {}

    first_i = min(signal_positions) + 1
    last_i = min(max(signal_positions) + hold_days, len(date_sequence) - 1)

    nav = 1.0
    peak = 1.0
    by_exit_date: dict[str, tuple[float, float]] = {}
    sleeve_allocations: dict[int, float] = {}

    for i in range(first_i, last_i + 1):
        today = date_sequence[i]
        pnl = 0.0

        for pos in signal_positions:
            day_offset = i - pos
            if not (1 <= day_offset <= hold_days):
                continue
            if pos not in sleeve_allocations:
                sleeve_allocations[pos] = sleeve_weight * nav

            start_close = _index_close(index_by_date, date_sequence[pos])
            prev_close = _index_close(index_by_date, date_sequence[i - 1])
            today_close = _index_close(index_by_date, today)
            if start_close and prev_close and today_close:
                prev_gross = prev_close / start_close
                today_gross = today_close / start_close
                pnl += sleeve_allocations[pos] * (today_gross - prev_gross)

        nav += pnl

        peak = max(peak, nav)
        drawdown = nav / peak - 1.0 if peak else 0.0
        by_exit_date[today] = (nav, drawdown)

    return by_exit_date


def _weekly_detail_rows(report: dict[str, Any], strategy_key: str) -> list[dict[str, Any]]:
    if strategy_key == 'top':
        sheets = (report.get('top_industries') or {}).get('sheets', {})
        rows = []
        for table in sheets.values():
            rows.extend((table or {}).get('rows', []))
        return rows

    if strategy_key == 'standard':
        sheets = (report.get('standard') or {}).get('sheets', {})
        for name, table in sheets.items():
            if '1.0' in str(name):
                return (table or {}).get('rows', [])
        return []

    if strategy_key == 'cold':
        sheets = (report.get('cold_industry') or {}).get('sheets', {})
        rows = []
        for name, table in sheets.items():
            if str(name) == 'combined_trajectory':
                continue
            rows.extend((table or {}).get('rows', []))
        return rows

    return []


def _average_gross_path(rows: list[dict[str, Any]], hold_days: int = 5) -> list[Optional[float]]:
    gross_by_stock = []
    for row in rows:
        gross = 1.0
        path: list[Optional[float]] = []
        has_value = False
        for day in range(1, hold_days + 1):
            ret = _parse_pct(row.get(f'T+{day}回报'))
            if ret is None:
                path.append(None)
                continue
            gross *= 1.0 + ret / 100.0
            path.append(gross)
            has_value = True
        if has_value:
            gross_by_stock.append(path)

    avg_path: list[Optional[float]] = []
    for day in range(1, hold_days + 1):
        vals = []
        for path in gross_by_stock:
            gross = path[day - 1]
            if gross is not None:
                vals.append(gross)
        avg_path.append(sum(vals) / len(vals) if vals else None)
    return avg_path


def _gross_path_or_summary(
    rows: list[dict[str, Any]],
    summary_return: Optional[float],
    hold_days: int = 5,
) -> list[Optional[float]]:
    path = _average_gross_path(rows, hold_days)
    if any(v is not None for v in path):
        return path
    if summary_return is None:
        return path
    return [None] * (hold_days - 1) + [1.0 + summary_return]


def _build_strategy_sleeve_nav(
    reports: list[tuple[str, dict[str, Any]]],
    index_by_date: dict[str, dict[str, Any]],
    date_sequence: list[str],
    min_gt1_count: int = 60,
    hold_days: int = 5,
    sleeve_weight: float = 0.2,
) -> dict[str, dict[str, tuple[float, float]]]:
    """Build real rolling-sleeve NAVs for weekly strategy history charts."""
    result = {
        'top': {},
        'filtered_top': {},
        'long_short_top': {},
        'cold': {},
        'standard': {},
    }
    if not reports or not date_sequence:
        return result

    date_pos = {d: i for i, d in enumerate(date_sequence)}
    sleeves = []
    for mmdd, report in reports:
        if (report.get('meta') or {}).get('n_available') != hold_days:
            continue
        if mmdd not in date_pos:
            continue
        start_pos = date_pos[mmdd]
        if start_pos + hold_days >= len(date_sequence):
            continue

        top_ret, _top_count = _weighted_weekly_return(
            (report.get('top_industries') or {}).get('summary', [])
        )
        cold_ret, _cold_count = _weighted_weekly_return(
            (report.get('cold_industry') or {}).get('summary', [])
        )
        standard_ret, gt1_count = _standard_gt1_summary(report)
        passes_filter = gt1_count >= min_gt1_count

        sleeves.append({
            'start_pos': start_pos,
            'exit_date': date_sequence[start_pos + hold_days],
            'passes_filter': passes_filter,
            'top_path': _gross_path_or_summary(_weekly_detail_rows(report, 'top'), top_ret, hold_days),
            'standard_path': _gross_path_or_summary(_weekly_detail_rows(report, 'standard'), standard_ret, hold_days),
            'cold_path': _gross_path_or_summary(_weekly_detail_rows(report, 'cold'), cold_ret, hold_days),
        })

    if not sleeves:
        return result

    nav = {key: 1.0 for key in result}
    peak = dict(nav)
    allocations: dict[tuple[int, str], float] = {}
    first_i = min(s['start_pos'] for s in sleeves) + 1
    last_i = min(max(s['start_pos'] for s in sleeves) + hold_days, len(date_sequence) - 1)
    sleeves_by_exit = {}
    for sleeve in sleeves:
        sleeves_by_exit.setdefault(sleeve['exit_date'], []).append(sleeve)

    for i in range(first_i, last_i + 1):
        today = date_sequence[i]
        yesterday = date_sequence[i - 1]

        day_ret = {key: 0.0 for key in result}
        for sleeve in sleeves:
            day_offset = i - sleeve['start_pos']
            if not (1 <= day_offset <= hold_days):
                continue
            idx = day_offset - 1
            index_delta = None
            start_close = _index_close(index_by_date, date_sequence[sleeve['start_pos']])
            prev_close = _index_close(index_by_date, yesterday)
            today_close = _index_close(index_by_date, today)
            if start_close and prev_close and today_close:
                index_delta = today_close / start_close - prev_close / start_close

            prev_idx = idx - 1

            def path_delta(path):
                today_gross = path[idx]
                if today_gross is None:
                    return None
                prev_gross = 1.0
                for j in range(prev_idx, -1, -1):
                    if path[j] is not None:
                        prev_gross = path[j]
                        break
                return today_gross - prev_gross

            top_delta = path_delta(sleeve['top_path'])
            standard_delta = path_delta(sleeve['standard_path'])
            cold_delta = path_delta(sleeve['cold_path'])

            sleeve_id = sleeve['start_pos']
            if top_delta is not None:
                alloc_key = (sleeve_id, 'top')
                allocations.setdefault(alloc_key, sleeve_weight * nav['top'])
                day_ret['top'] += allocations[alloc_key] * top_delta
                if sleeve['passes_filter']:
                    alloc_key = (sleeve_id, 'filtered_top')
                    allocations.setdefault(alloc_key, sleeve_weight * nav['filtered_top'])
                    day_ret['filtered_top'] += allocations[alloc_key] * top_delta
            if standard_delta is not None:
                alloc_key = (sleeve_id, 'standard')
                allocations.setdefault(alloc_key, sleeve_weight * nav['standard'])
                day_ret['standard'] += allocations[alloc_key] * standard_delta
            if cold_delta is not None:
                alloc_key = (sleeve_id, 'cold')
                allocations.setdefault(alloc_key, sleeve_weight * nav['cold'])
                day_ret['cold'] += allocations[alloc_key] * cold_delta

            combo_delta = None
            if sleeve['passes_filter']:
                combo_delta = 0.0
                if top_delta is not None:
                    combo_delta += 0.8 * top_delta
                if index_delta is not None:
                    combo_delta += 0.2 * index_delta
            elif index_delta is not None:
                combo_delta = -1.0 * index_delta
            if combo_delta is not None:
                alloc_key = (sleeve_id, 'long_short_top')
                allocations.setdefault(alloc_key, sleeve_weight * nav['long_short_top'])
                day_ret['long_short_top'] += allocations[alloc_key] * combo_delta

        for key, pnl in day_ret.items():
            nav[key] += pnl
            peak[key] = max(peak[key], nav[key])

        for _sleeve in sleeves_by_exit.get(today, []):
            for key in result:
                drawdown = nav[key] / peak[key] - 1.0 if peak[key] else 0.0
                result[key][today] = (nav[key], drawdown)

    return result


def _build_weekly_strategy_history(
    reports: list[tuple[str, dict[str, Any]]],
    min_gt1_count: int = 60,
    index_rows: Optional[list[dict[str, Any]]] = None,
    date_sequence: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Build weekly strategy history rows with NAV and drawdown.

    Input reports must be sorted by MMDD. Only completed 5-day weekly reports
    participate. The filtered strategy treats non-passing dates as cash, i.e.
    return 0%.
    """
    nav = {
        'top': 1.0,
        'filtered_top': 1.0,
        'long_short_top': 1.0,
        'cold': 1.0,
        'standard': 1.0,
        'csi1000': 1.0,
    }
    peak = dict(nav)
    rows = []
    index_by_date = {str(row.get('date')): row for row in (index_rows or [])}
    date_pos = {d: i for i, d in enumerate(date_sequence or [])}
    completed_signal_dates = [
        mmdd for mmdd, report in reports
        if (report.get('meta') or {}).get('n_available') == 5
        and mmdd in date_pos
        and date_pos[mmdd] + 5 < len(date_sequence or [])
    ]
    csi1000_sleeve_nav = _build_index_sleeve_nav(
        completed_signal_dates,
        index_by_date,
        date_sequence or [],
    )
    strategy_sleeve_nav = _build_strategy_sleeve_nav(
        reports,
        index_by_date,
        date_sequence or [],
        min_gt1_count=min_gt1_count,
    )

    for mmdd, report in reports:
        if (report.get('meta') or {}).get('n_available') != 5:
            continue
        if mmdd not in date_pos or date_pos[mmdd] + 5 >= len(date_sequence or []):
            continue

        top_ret, top_count = _weighted_weekly_return(
            (report.get('top_industries') or {}).get('summary', [])
        )
        cold_ret, cold_count = _weighted_weekly_return(
            (report.get('cold_industry') or {}).get('summary', [])
        )
        standard_ret, gt1_count = _standard_gt1_summary(report)
        passes_filter = gt1_count >= min_gt1_count
        filtered_top_ret = top_ret if passes_filter and top_ret is not None else 0.0

        returns = {
            'top': top_ret or 0.0,
            'filtered_top': filtered_top_ret,
            'cold': cold_ret or 0.0,
            'standard': standard_ret or 0.0,
        }
        csi1000_ret = None
        csi1000_nav = None
        csi1000_drawdown = None
        strategy_exit_date = None
        if mmdd in date_pos and date_sequence:
            end_idx = date_pos[mmdd] + 5
            if end_idx < len(date_sequence):
                strategy_exit_date = date_sequence[end_idx]
                start_key = f"2026{mmdd}"
                end_key = f"2026{strategy_exit_date}"
                start_row = index_by_date.get(start_key)
                end_row = index_by_date.get(end_key)
                if start_row and end_row:
                    try:
                        start_close = float(start_row.get('close'))
                        end_close = float(end_row.get('close'))
                        if start_close:
                            csi1000_ret = end_close / start_close - 1.0
                    except Exception:
                        csi1000_ret = None
                nav_tuple = csi1000_sleeve_nav.get(date_sequence[end_idx])
                if nav_tuple is not None:
                    csi1000_nav, csi1000_drawdown = nav_tuple

        index_ret = csi1000_ret or 0.0
        futures_ret = 0.2 * index_ret if passes_filter else -1.0 * index_ret
        long_short_top_ret = futures_ret
        if passes_filter:
            long_short_top_ret += 0.8 * (top_ret or 0.0)
        returns['long_short_top'] = long_short_top_ret

        for key, ret in returns.items():
            nav[key] *= (1.0 + ret)
            peak[key] = max(peak[key], nav[key])
        if strategy_exit_date is not None:
            for key in ['top', 'filtered_top', 'long_short_top', 'cold', 'standard']:
                nav_tuple = strategy_sleeve_nav.get(key, {}).get(strategy_exit_date)
                if nav_tuple is not None:
                    nav[key] = nav_tuple[0]
                    peak[key] = max(peak[key], nav[key])
        if csi1000_nav is not None:
            nav['csi1000'] = csi1000_nav
            peak['csi1000'] = max(peak['csi1000'], nav['csi1000'])

        row = {
            'date_raw': mmdd,
            'date': _mmdd_label(mmdd),
            'gt1_count': gt1_count,
            'passes_filter': passes_filter,
            'top_count': top_count,
            'cold_count': cold_count,
            'top_return': _pct_value(top_ret),
            'filtered_top_return': _pct_value(filtered_top_ret),
            'long_short_top_return': _pct_value(long_short_top_ret),
            'cold_return': _pct_value(cold_ret),
            'standard_return': _pct_value(standard_ret),
            'csi1000_return': _pct_value(csi1000_ret),
        }
        for key in ['top', 'filtered_top', 'long_short_top', 'cold', 'standard', 'csi1000']:
            row[f'{key}_nav'] = round(nav[key], 6)
            strategy_drawdown = None
            if strategy_exit_date is not None and key != 'csi1000':
                nav_tuple = strategy_sleeve_nav.get(key, {}).get(strategy_exit_date)
                if nav_tuple is not None:
                    strategy_drawdown = nav_tuple[1]
            if strategy_drawdown is not None:
                drawdown = strategy_drawdown
            elif key == 'csi1000' and csi1000_drawdown is not None:
                drawdown = csi1000_drawdown
            else:
                drawdown = nav[key] / peak[key] - 1.0 if peak[key] else 0.0
            row[f'{key}_drawdown'] = round(drawdown * 100.0, 4)
        rows.append(row)

    return rows


def _read_index_cache_rows(symbol: str) -> list[dict[str, Any]]:
    path = os.path.join(PROJECT_ROOT, "index_cache", f"{symbol}.csv")
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    except Exception:
        return []
    return rows


@ttl_cache(120)
def get_weekly_strategy_history(min_gt1_count: int = 60) -> list[dict[str, Any]]:
    files = sorted(glob_reports("*的选股策略礼拜攻势.json"))
    reports: list[tuple[str, dict[str, Any]]] = []
    for f in files:
        mmdd = os.path.basename(f)[:4]
        if not mmdd.isdigit():
            continue
        try:
            with open(f, 'r', encoding='utf-8') as jf:
                reports.append((mmdd, json.load(jf)))
        except Exception:
            continue
    date_sequence = []
    try:
        if market_db:
            date_sequence = market_db.get_market_dates()
    except Exception:
        date_sequence = []
    return _build_weekly_strategy_history(
        reports,
        min_gt1_count=min_gt1_count,
        index_rows=_read_index_cache_rows("sh000852"),
        date_sequence=date_sequence,
    )


def _normalize_history(raw_list: list) -> list:
    """Convert raw tracking format (acc_08_raw strings) → parsed history format."""
    result = []
    for r in raw_list:
        # Already in parsed format — pass through
        if 'acc_08' in r and 'all_pct' in r:
            result.append(r)
            continue

        all_raw = r.get('all_raw', '')
        all_pct = _parse_pct(all_raw)
        all_s, all_t = _parse_ratio(all_raw)

        result.append({
            'date': r.get('date', ''),
            'date_raw': r.get('date_raw', ''),
            'acc_08': _parse_pct(r.get('acc_08_raw', '')),
            'acc_12': _parse_pct(r.get('acc_12_raw', '')),
            'all_pct': all_pct,
            'all_success': all_s,
            'all_total': all_t,
            'cold_alpha': _parse_pct(r.get('cold_alpha_raw', '')),
            'next_10': int(r.get('next_10', 0)),
        })
    return result


@ttl_cache(120)
def get_history_data() -> list[dict[str, Any]]:
    # Try history.json first
    history_path = os.path.join(PROJECT_ROOT, 'history.json')
    if os.path.exists(history_path):
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            return _normalize_history(raw)
        except Exception:
            pass

    # Fall back to xlsx aggregation
    files = glob_reports("*量化复盘报告*.xlsx")
    records = []
    for f in files:
        df = _read_safe(f, sheet_name="0.每日追踪总表", header=[0, 1])
        row = _first_row(df)
        if row is None:
            continue

        def v(pos):
            try:
                return row.iloc[pos]
            except Exception:
                return None

        date_raw = v(_COL["date"])
        try:
            date_str = str(int(float(str(date_raw))))
            dt = datetime.strptime(date_str, "%Y%m%d")
            date_label = dt.strftime("%m/%d")
        except Exception:
            date_label = str(date_raw)

        acc_08 = _parse_pct(v(_COL["acc_08"]))
        acc_12 = _parse_pct(v(_COL["acc_12"]))
        all_str = v(_COL["all"])
        all_pct = _parse_pct(all_str)
        all_s, all_t = _parse_ratio(all_str)
        cold_alpha = _parse_pct(v(_COL["cold_alpha"]))
        next_10 = v(_COL["next_10"])

        records.append({
            "date": date_label,
            "date_raw": date_str,
            "acc_08": acc_08,
            "acc_12": acc_12,
            "all_pct": all_pct,
            "all_success": all_s,
            "all_total": all_t,
            "cold_alpha": cold_alpha,
            "next_10": int(next_10) if pd.notna(next_10) else 0,
        })
    records.sort(key=lambda r: r["date_raw"])
    seen = set()
    deduped = []
    for r in records:
        if r["date_raw"] not in seen:
            seen.add(r["date_raw"])
            deduped.append(r)
    return deduped


# ── 筛选器（全市场股票） ──

def get_screener_data(date: Optional[str] = None) -> list[dict[str, Any]]:
    """返回 Whole Market 中指定日期的全量股票数据。"""
    return _query_market(date, acc_min=0, ind_min=-999, industry="")


@ttl_cache(300)
def get_screener_count(date: Optional[str] = None) -> int:
    """返回全市场股票总数（只读单列统计行数）。"""
    if not date:
        dates = get_available_dates()
        date = dates[-1] if dates else None
    if not date:
        return 0
    db_count = _db_market_count(date)
    if db_count is not None:
        return db_count

    try:
        df = market_store.read_snapshot(date)
        return len(df)
    except Exception:
        return 0


def query_screener(date: str, acc_min: float = 0, ind_min: float = -999,
                   industry: str = "", page: int = 1, per_page: int = 100) -> dict:
    """分页查询全市场股票。返回 {rows, total, page, per_page, pages}。"""
    rows = _query_market(date, acc_min=acc_min, ind_min=ind_min, industry=industry)
    total = len(rows)
    pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "rows": rows[start:end],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


@ttl_cache(120)
def _read_market_sheet(date: str):
    """读取单日市场快照，返回 cleaned DataFrame（2min 缓存）。"""
    if not date:
        dates = get_available_dates()
        date = dates[-1] if dates else None
    if not date:
        return None
    db_df = _db_read_market_sheet(date)
    if db_df is not None:
        return db_df

    try:
        df = market_store.read_snapshot(date)
    except Exception:
        return None
    df['准确率'] = pd.to_numeric(df['准确率'], errors='coerce')
    df['今日指标'] = pd.to_numeric(df['今日指标'], errors='coerce')
    return df


def _query_market(date: str, acc_min: float = 0, ind_min: float = -999,
                  industry: str = "") -> list[dict[str, Any]]:
    """按条件筛选全市场股票，返回 dict 列表。"""
    df = _read_market_sheet(date)
    if df is None:
        return []

    mask = (df['准确率'] >= acc_min) & (df['今日指标'] >= ind_min)
    if industry:
        mask &= (df['行业'].astype(str).str.strip() == industry)
    df = df[mask]

    def _extract_return(h):
        if pd.isna(h):
            return ""
        matches = re.findall(r'\(([+-]?\d+\.?\d*)%\)', str(h))
        if not matches:
            return ""
        return f"{float(matches[-1]):+.2f}%"

    df = df.copy()
    df['今日收益率'] = df['指标历史'].apply(_extract_return)

    display_cols = ['代码', '全称', '行业', '准确率', '今日指标', '今日收益率']
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        d = {}
        for c in display_cols:
            v = row.get(c)
            if pd.isna(v):
                d[c] = ""
            elif isinstance(v, (np.floating, float)):
                d[c] = round(float(v), 2)
            elif isinstance(v, (np.integer,)):
                d[c] = int(v)
            else:
                d[c] = str(v)
        rows.append(d)

    return rows


@ttl_cache(300)
def get_all_industries() -> list[str]:
    """从最新单日市场快照获取行业列表。"""
    dates = get_available_dates()
    if not dates:
        return []
    db_inds = _db_industries(dates[-1])
    if db_inds:
        return db_inds

    try:
        df = market_store.read_snapshot(dates[-1])
    except Exception:
        return []
    inds = [str(v).strip() for v in df['行业'].dropna().unique() if str(v).strip()]
    return sorted(inds)
