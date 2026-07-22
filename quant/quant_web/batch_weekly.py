"""
礼拜攻势生成器 — 前向视角（T 日选股 → 后一周验证）逻辑

核心逻辑：
  - 第 T 日生成报告时，用 T 日的选股条件（准确率>0.6 & 今日指标>阈值）选出股票
  - 逐日查 T+1 ~ T+5 各 sheet，提取该日单日收益（不足 5 天则有多少算多少）
  - 双轨制：全市场标准策略 + 冷门行业专属策略
  - 汇总表（整体回报总结）：记录每组的平均收益、胜率和 N 日轨迹均值
  - 明细 sheet：逐票 T+1~T+N 回报 + 累计，缺日标"待更新"
  - 未来日期不足时标记提示，但有多少天画多少天

用法:  python quant_web/batch_weekly.py
"""
import json
import logging
import os
import sys
import pandas as pd
import numpy as np
import re

from data_service import df_to_table
from report_paths import glob_reports, output_report, resolve_report

try:
    from . import db_service
except ImportError:
    import db_service

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER_FILE = os.path.join(PROJECT_ROOT, "Whole Market.xlsx")

HOLD_DAYS = 5

_THRESHOLDS = [("指标大于0.8", 0.8), ("指标大于1.0", 1.0), ("指标大于1.2", 1.2)]

_OUTPUT_COLS = [
    "代码", "全称", "准确率", "今日指标",
    "T+1回报", "T+2回报", "T+3回报", "T+4回报", "T+5回报", "累计回报%"
]
_RAW_CUM_COLS = ['T1_cum', 'T2_cum', 'T3_cum', 'T4_cum', 'T5_cum']


def _get_last_return(history_str):
    """从指标历史字符串中提取最近一个交易日的收益率（float），NaN 表示无数据。"""
    if pd.isna(history_str):
        return np.nan
    matches = re.findall(r'\(([+-]?\d+\.?\d*)%\)', str(history_str))
    if not matches:
        return np.nan
    return float(matches[-1]) / 100.0


def _prepare_df(df):
    df = df.copy()
    df["准确率"] = pd.to_numeric(df["准确率"], errors="coerce")
    df["今日指标"] = pd.to_numeric(df["今日指标"], errors="coerce")
    return df


def _compute_cumulative(daily_returns):
    """给定单日收益列表 [r1, r2, ...]，返回累计收益 [cum1, cum2, ...] 每个都是 float。"""
    cum_list = []
    cum = 1.0
    for r in daily_returns:
        if r is None or (isinstance(r, float) and np.isnan(r)):
            cum_list.append(np.nan)
        else:
            cum *= (1 + r)
            cum_list.append(cum - 1)
    return cum_list


def _split_cold_pool(df, base_pool):
    """冷门池：在指标>1.0 的入选股票中，行业符合数 == 1 的股票。

    对标每日回测的"当日最新行业热度"表。

    Returns: (cold_mask: pd.Series, cold_industries: list[str], ind_counts: pd.Series)
    cold_mask 的 index 对齐 detect_pool（指标>1.0），不是 base_pool。
    """
    # df_T 的行业列已由 generate_weekly_report 预处理（空行业→空1/空2...）
    if '行业' not in df.columns:
        ind_series = pd.Series([f'空{i}' for i in range(1, len(df) + 1)], index=df.index)
    else:
        ind_series = df['行业'].fillna('空1').astype(str).str.strip()

    # 对标回测"当日最新行业热度"：准确率>0.6 & 今日指标>1.0
    detect_pool = df[(df['准确率'] > 0.6) & (df['今日指标'] > 1.0)]
    detect_ind = ind_series.loc[detect_pool.index]
    ind_counts = detect_ind.value_counts()

    # 冷门行业 = 符合数 == 1
    cold_industries = ind_counts[ind_counts == 1].index.tolist()

    if not cold_industries:
        return pd.Series(False, index=detect_pool.index), [], ind_counts

    # mask 作用在 detect_pool（指标>1.0 池）上
    cold_mask = detect_ind.isin(cold_industries)

    return cold_mask, cold_industries, ind_counts


def _read_future_returns(all_dates, start_idx, codes):
    """预读 T+1 ~ T+5 各 sheet，构建 code → [r1..rN] 映射。

    Returns: (daily_map: dict, n_available: int)
    """
    future_dates = all_dates[start_idx + 1:start_idx + 1 + HOLD_DAYS]
    n_available = len(future_dates)

    daily_map = {}

    for day_i, fd in enumerate(future_dates):
        try:
            df_f = _prepare_df(db_service.read_market_sheet(fd))
        except Exception:
            continue
        if df_f is None:
            continue
        ret_map = {}
        for _, row in df_f.iterrows():
            r = _get_last_return(row.get("指标历史"))
            if not np.isnan(r):
                ret_map[row["代码"]] = r

        for code in codes:
            daily_map.setdefault(code, [None] * n_available)
            daily_map[code][day_i] = ret_map.get(code, np.nan)

    return daily_map, n_available


def _build_detail_and_summary(pool_df, daily_map, n_available):
    """对给定股票池执行阈值分组，构建明细表和汇总。

    Args:
        pool_df: 已过滤 准确率>0.6 的 DataFrame
        daily_map: code → [r1..rN]
        n_available: 可用未来交易日数

    Returns: (pools: dict, summary_list: list[dict])
    """
    stock_info_cols = ["代码", "全称", "准确率", "今日指标"]

    pools = {}
    summary_list = []

    for name, th in _THRESHOLDS:
        selected = pool_df[pool_df["今日指标"] > th][stock_info_cols].copy()
        if selected.empty:
            pools[name] = pd.DataFrame(columns=_OUTPUT_COLS + _RAW_CUM_COLS)
            entry = {
                "策略分组": name,
                "入选股票数": 0,
                "有效收益股票数": 0,
                "缺失收益股票数": 0,
                "平均持仓回报": 0.0,
                "策略胜率(>0%)": 0.0,
                "可用天数": n_available,
            }
            for i in range(1, HOLD_DAYS + 1):
                entry[f'T{i}均值'] = 0.0
            summary_list.append(entry)
            continue

        rows = []
        for _, stock in selected.iterrows():
            code = stock["代码"]
            dr = daily_map.get(code, [np.nan] * n_available)
            padded = (dr + [np.nan] * HOLD_DAYS)[:HOLD_DAYS]
            cum = _compute_cumulative(
                [r if isinstance(r, float) and not np.isnan(r) else np.nan for r in padded]
            )

            row = {
                "代码": code,
                "全称": stock["全称"],
                "准确率": stock["准确率"],
                "今日指标": stock["今日指标"],
            }
            for i in range(HOLD_DAYS):
                r = padded[i]
                if r is not None and isinstance(r, float) and not np.isnan(r):
                    row[f"T+{i+1}回报"] = f"{r*100:+.2f}%"
                else:
                    row[f"T+{i+1}回报"] = "待更新"
            valid_cum = [c for c in cum if not np.isnan(c)]
            row["累计回报%"] = f"{valid_cum[-1]*100:+.2f}%" if valid_cum else "待更新"
            for i in range(HOLD_DAYS):
                row[f"T{i+1}_cum"] = cum[i] if i < len(cum) else np.nan

            rows.append(row)

        detail_df = pd.DataFrame(rows)
        detail_df = detail_df.sort_values(by="今日指标", ascending=False)
        pools[name] = detail_df

        # ── 汇总 ──
        if n_available >= 5:
            cum_col = detail_df["T5_cum"].dropna()
        elif n_available >= 1:
            cum_col = detail_df[f"T{n_available}_cum"].dropna()
        else:
            cum_col = pd.Series(dtype=float)
        selected_count = len(selected)
        valid_count = len(cum_col)
        missing_count = selected_count - valid_count
        if valid_count > 0:
            avg_ret = cum_col.mean()
            win_rate = (cum_col > 0).mean()
        else:
            avg_ret = 0.0
            win_rate = 0.0

        entry = {
            "策略分组": name,
            "入选股票数": selected_count,
            "有效收益股票数": valid_count,
            "缺失收益股票数": missing_count,
            "平均持仓回报": avg_ret,
            "策略胜率(>0%)": win_rate,
            "可用天数": n_available,
        }
        for i in range(1, HOLD_DAYS + 1):
            col = f'T{i}_cum'
            if col in detail_df.columns and not detail_df.empty:
                vals = detail_df[col].dropna()
                entry[f'T{i}均值'] = float(vals.mean()) if len(vals) > 0 else 0.0
            else:
                entry[f'T{i}均值'] = 0.0

        summary_list.append(entry)

    return pools, summary_list


def _format_summary_for_display(summary_list):
    """将内部 summary 的 raw float 转为显示字符串，T均值保持 float。"""
    formatted = []
    for entry in summary_list:
        e = dict(entry)
        e["平均持仓回报"] = f"{e['平均持仓回报'] * 100:.2f}%"
        e["策略胜率(>0%)"] = f"{e['策略胜率(>0%)'] * 100:.2f}%"
        formatted.append(e)
    return formatted


def _build_strategy_sheets(pools):
    """将 pools DataFrame 转为 JSON-safe sheets dict。"""
    sheets_json = {}
    for name, pool_df in pools.items():
        key = name if not pool_df.empty else f"{name}(当日空仓)"
        if not pool_df.empty:
            write_cols = [c for c in _OUTPUT_COLS if c in pool_df.columns]
            sheets_json[key] = df_to_table(
                pool_df[write_cols].sort_values(by="今日指标", ascending=False)
            )
        else:
            sheets_json[key] = df_to_table(pd.DataFrame(columns=_OUTPUT_COLS))
    return sheets_json


def _build_top_industry_weekly(all_pool, ind_counts, daily_map, n_available):
    """构建前三行业分行业礼拜攻势（仅指标>1.0）。

    按入选数层级取前 N 个行业（边界并列穿透）。
    对每个选中行业，用仅 指标>1.0 的股票做 5 日礼拜攻势。

    Returns: (pools: dict, summary_list: list[dict], selected_industries: list[str])
    """
    valid_inds = ind_counts[ind_counts.index != 'Empty']
    if valid_inds.empty:
        return {}, [], []

    # 按入选数分组排序
    count_df = valid_inds.reset_index()
    count_df.columns = ['行业名称', '入选数量']
    grouped = count_df.groupby('入选数量')['行业名称'].apply(
        lambda x: sorted(x.tolist())
    ).reset_index()
    grouped = grouped.sort_values('入选数量', ascending=False)

    # 边界并列穿透选取
    selected = []
    for _, grp in grouped.iterrows():
        level_inds = grp['行业名称']
        if len(selected) >= 3:
            break
        if len(selected) + len(level_inds) <= 3:
            selected.extend(level_inds)
        else:
            selected.extend(level_inds)
            break

    stock_info_cols = ["代码", "全称", "准确率", "今日指标", "行业"]

    # 仅用指标 > 1.0
    pool_gt_10 = all_pool[all_pool["今日指标"] > 1.0].copy()

    pools = {}
    summary_list = []

    for ind_name in selected:
        ind_pool = pool_gt_10[pool_gt_10['行业'] == ind_name][stock_info_cols].copy()

        rows = []
        for _, stock in ind_pool.iterrows():
            code = stock["代码"]
            dr = daily_map.get(code, [np.nan] * n_available)
            padded = (dr + [np.nan] * HOLD_DAYS)[:HOLD_DAYS]
            cum = _compute_cumulative(
                [r if isinstance(r, float) and not np.isnan(r) else np.nan for r in padded]
            )

            row = {
                "代码": code,
                "全称": stock["全称"],
                "准确率": stock["准确率"],
                "今日指标": stock["今日指标"],
            }
            for i in range(HOLD_DAYS):
                r = padded[i]
                if r is not None and isinstance(r, float) and not np.isnan(r):
                    row[f"T+{i+1}回报"] = f"{r*100:+.2f}%"
                else:
                    row[f"T+{i+1}回报"] = "待更新"
            valid_cum = [c for c in cum if not np.isnan(c)]
            row["累计回报%"] = f"{valid_cum[-1]*100:+.2f}%" if valid_cum else "待更新"
            for i in range(HOLD_DAYS):
                row[f"T{i+1}_cum"] = cum[i] if i < len(cum) else np.nan
            rows.append(row)

        detail_df = pd.DataFrame(rows)
        if not detail_df.empty:
            detail_df = detail_df.sort_values(by="今日指标", ascending=False)

        name_key = ind_name if not detail_df.empty else f"{ind_name}(当日空仓)"
        pools[name_key] = detail_df

        # 汇总
        if n_available >= 5:
            cum_vals = detail_df["T5_cum"].dropna() if "T5_cum" in detail_df.columns else pd.Series(dtype=float)
        elif n_available >= 1:
            cum_vals = detail_df[f"T{n_available}_cum"].dropna() if f"T{n_available}_cum" in detail_df.columns else pd.Series(dtype=float)
        else:
            cum_vals = pd.Series(dtype=float)

        selected_count = len(ind_pool)
        valid_count = len(cum_vals)
        avg_ret = cum_vals.mean() if valid_count > 0 else 0.0
        win_rate = (cum_vals > 0).mean() if valid_count > 0 else 0.0

        entry = {
            "策略分组": ind_name,
            "入选股票数": selected_count,
            "有效收益股票数": valid_count,
            "缺失收益股票数": selected_count - valid_count,
            "平均持仓回报": avg_ret,
            "策略胜率(>0%)": win_rate,
            "可用天数": n_available,
        }
        for i in range(1, HOLD_DAYS + 1):
            col = f'T{i}_cum'
            if col in detail_df.columns and not detail_df.empty:
                vals = detail_df[col].dropna()
                entry[f'T{i}均值'] = float(vals.mean()) if len(vals) > 0 else 0.0
            else:
                entry[f'T{i}均值'] = 0.0

        summary_list.append(entry)

    return pools, summary_list, selected


def _build_cold_industry_weekly(cold_pool, daily_map, n_available):
    """构建冷门行业专属策略（按行业分组，不按指标阈值）。

    每个冷门行业一个 sheet，展示该行业所有股票的 5 日礼拜攻势。

    Returns: (pools: dict, summary_list: list[dict])
    """
    if cold_pool.empty:
        return {}, []

    stock_info_cols = ["代码", "全称", "准确率", "今日指标", "行业"]
    cold_pool_with_ind = cold_pool.copy()

    # 按行业分组
    industry_groups = cold_pool_with_ind.groupby('行业')

    pools = {}
    summary_list = []

    for ind_name, ind_pool in industry_groups:
        ind_pool = ind_pool[stock_info_cols].copy()

        rows = []
        for _, stock in ind_pool.iterrows():
            code = stock["代码"]
            dr = daily_map.get(code, [np.nan] * n_available)
            padded = (dr + [np.nan] * HOLD_DAYS)[:HOLD_DAYS]
            cum = _compute_cumulative(
                [r if isinstance(r, float) and not np.isnan(r) else np.nan for r in padded]
            )

            row = {
                "代码": code,
                "全称": stock["全称"],
                "准确率": stock["准确率"],
                "今日指标": stock["今日指标"],
            }
            for i in range(HOLD_DAYS):
                r = padded[i]
                if r is not None and isinstance(r, float) and not np.isnan(r):
                    row[f"T+{i+1}回报"] = f"{r*100:+.2f}%"
                else:
                    row[f"T+{i+1}回报"] = "待更新"
            valid_cum = [c for c in cum if not np.isnan(c)]
            row["累计回报%"] = f"{valid_cum[-1]*100:+.2f}%" if valid_cum else "待更新"
            for i in range(HOLD_DAYS):
                row[f"T{i+1}_cum"] = cum[i] if i < len(cum) else np.nan
            rows.append(row)

        detail_df = pd.DataFrame(rows)
        if not detail_df.empty:
            detail_df = detail_df.sort_values(by="今日指标", ascending=False)

        name_key = ind_name if not detail_df.empty else f"{ind_name}(当日空仓)"
        pools[name_key] = detail_df

        # 汇总
        if n_available >= 5:
            cum_vals = detail_df["T5_cum"].dropna() if "T5_cum" in detail_df.columns else pd.Series(dtype=float)
        elif n_available >= 1:
            cum_vals = detail_df[f"T{n_available}_cum"].dropna() if f"T{n_available}_cum" in detail_df.columns else pd.Series(dtype=float)
        else:
            cum_vals = pd.Series(dtype=float)

        selected_count = len(ind_pool)
        valid_count = len(cum_vals)
        avg_ret = cum_vals.mean() if valid_count > 0 else 0.0
        win_rate = (cum_vals > 0).mean() if valid_count > 0 else 0.0

        entry = {
            "策略分组": ind_name,
            "入选股票数": selected_count,
            "有效收益股票数": valid_count,
            "缺失收益股票数": selected_count - valid_count,
            "平均持仓回报": avg_ret,
            "策略胜率(>0%)": win_rate,
            "可用天数": n_available,
        }
        for i in range(1, HOLD_DAYS + 1):
            col = f'T{i}_cum'
            if col in detail_df.columns and not detail_df.empty:
                vals = detail_df[col].dropna()
                entry[f'T{i}均值'] = float(vals.mean()) if len(vals) > 0 else 0.0
            else:
                entry[f'T{i}均值'] = 0.0

        summary_list.append(entry)

    return pools, summary_list


def _compute_combined_trajectory(pools, n_available):
    """计算所有冷门行业股票的合并日轨迹（T1~Tn 每日累计均值）。"""
    all_cum = {f'T{i}_cum': [] for i in range(1, HOLD_DAYS + 1)}
    for detail_df in pools.values():
        if detail_df.empty:
            continue
        for i in range(1, HOLD_DAYS + 1):
            col = f'T{i}_cum'
            if col in detail_df.columns:
                vals = detail_df[col].dropna().tolist()
                all_cum[col].extend(vals)

    trajectory = {}
    for i in range(1, min(n_available, HOLD_DAYS) + 1):
        vals = all_cum[f'T{i}_cum']
        trajectory[f'T{i}均值'] = float(np.mean(vals)) if vals else 0.0
    return trajectory


def _write_excel_sheets(writer, pools, summary_list, suffix=""):
    """向 Excel writer 写入一套完整的 sheet（summary + 各阈值明细）。"""
    summary_df = pd.DataFrame(_format_summary_for_display(summary_list))
    sheet_title = f"整体回报总结{suffix}"
    summary_df.to_excel(writer, sheet_name=sheet_title, index=False)

    for name, pool_df in pools.items():
        sheet_key = f"{name}{suffix}"
        if not pool_df.empty:
            write_cols = [c for c in _OUTPUT_COLS if c in pool_df.columns]
            pool_df[write_cols].sort_values(by="今日指标", ascending=False).to_excel(
                writer, sheet_name=sheet_key, index=False)
        else:
            pd.DataFrame(columns=_OUTPUT_COLS).to_excel(
                writer, sheet_name=f"{sheet_key}(当日空仓)", index=False)


def generate_weekly_report(sheet_name, all_dates, current_idx):
    """为第 T 日生成前向礼拜攻势报告（双轨制：standard + cold_industry）。"""
    # ── 读取 T 日数据 ──
    df_T = db_service.read_market_sheet(sheet_name)
    if df_T is None:
        log.error(f"  读取 [{sheet_name}] 失败 — SQLite 无数据")
        return False
    df_T = _prepare_df(df_T)

    # 空行业每个标注为独立行业（对标 batch_backtest.split_empty_industries）
    df_T = df_T.copy()
    df_T['行业'] = df_T['行业'].fillna('').astype(str).str.strip()
    empty_mask = df_T['行业'].isin(['', '空'])
    n_empty = empty_mask.sum()
    if n_empty > 0:
        empty_idx = df_T[empty_mask].index
        for j, idx in enumerate(empty_idx):
            df_T.at[idx, '行业'] = f'空{j+1}'

    # ── 构建双轨池（all_pool 先建，用于检测热门行业） ──
    all_pool = df_T[df_T["准确率"] > 0.6]

    # ── 检测冷门行业（对标当日最新行业热度：指标>1.0 池中符合数==1） ──
    cold_mask, cold_industries, ind_counts = _split_cold_pool(df_T, all_pool)
    # cold_mask 的 index 对齐指标>1.0 的池，从中取冷门股票
    detect_pool = all_pool[all_pool["今日指标"] > 1.0]
    cold_pool = detect_pool[cold_mask]

    log.info(f"  [{sheet_name}] 冷门行业(单股票): {cold_industries}")

    # ── 预读未来收益（只读一次，双轨复用） ──
    all_codes = list(df_T["代码"])
    daily_map, n_available = _read_future_returns(all_dates, current_idx, all_codes)

    if n_available == 0:
        log.info(f"  [{sheet_name}] 无后续交易日，标记持有中")
    elif n_available < HOLD_DAYS:
        log.info(f"  [{sheet_name}] {sheet_name} 选股 → 仅 {n_available}/5 天可用")
    else:
        settle_date = all_dates[current_idx + HOLD_DAYS]
        log.info(f"  [{sheet_name}] {sheet_name} 选股 → {settle_date} 结仓 (5/5)")

    # ── 双轨计算 ──
    std_pools, std_summary = _build_detail_and_summary(all_pool, daily_map, n_available)

    # ── 前三行业分行业策略 ──
    top_ind_pools, top_ind_summary, selected_industries = _build_top_industry_weekly(
        all_pool, ind_counts, daily_map, n_available
    )
    log.info(f"  [{sheet_name}] 前三行业: {selected_industries}")

    cold_pools, cold_summary = _build_cold_industry_weekly(cold_pool, daily_map, n_available)
    cold_combined_traj = _compute_combined_trajectory(cold_pools, n_available)

    # ── 构建嵌套 JSON ──
    report = {
        "standard": {
            "summary": _format_summary_for_display(std_summary),
            "sheets": _build_strategy_sheets(std_pools),
        },
        "top_industries": {
            "summary": _format_summary_for_display(top_ind_summary),
            "sheets": _build_strategy_sheets(top_ind_pools),
            "meta": {
                "industries": selected_industries,
                "indicator_threshold": 1.0,
            },
        },
        "cold_industry": {
            "summary": _format_summary_for_display(cold_summary),
            "sheets": _build_strategy_sheets(cold_pools),
            "combined_trajectory": cold_combined_traj,
        },
        "meta": {
            "date": sheet_name,
            "cold_industries": cold_industries,
            "industry_distribution": {str(k): int(v) for k, v in ind_counts.items()},
            "n_available": n_available,
        },
    }

    # ── 写 JSON ──
    json_path = output_report(f"{sheet_name}的选股策略礼拜攻势.json")
    with open(json_path, 'w', encoding='utf-8') as jf:
        json.dump(report, jf, ensure_ascii=False, indent=2)

    # ── 写 Excel ──
    output_fn = output_report(f"{sheet_name}的选股策略礼拜攻势.xlsx")
    output_fn_tmp = output_report(f".{sheet_name}的选股策略礼拜攻势.tmp.xlsx")
    with pd.ExcelWriter(output_fn_tmp, engine="openpyxl") as writer:
        _write_excel_sheets(writer, std_pools, std_summary)
        _write_excel_sheets(writer, cold_pools, cold_summary, suffix="_冷门")
    os.replace(output_fn_tmp, output_fn)

    return True


def _build_weekly_trend_cache():
    """从所有礼拜攻势 JSON 中提取趋势数据，写入单个缓存文件。"""
    records = []
    for f in sorted(glob_reports("*的选股策略礼拜攻势.json")):
        base = os.path.basename(f)
        mmdd = base[:4]
        if not mmdd.isdigit():
            continue
        try:
            with open(f, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
        except Exception:
            continue

        if 'standard' not in data:
            continue
        std_summary = data.get('standard', {}).get('summary', [])
        if not std_summary:
            continue

        label = f"{mmdd[:2]}/{mmdd[2:]}"
        record = {"date": label, "date_raw": mmdd}
        for row in std_summary:
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

        # 冷门总回报
        cold_traj = data.get('cold_industry', {}).get('combined_trajectory', {})
        if cold_traj:
            t_vals = [cold_traj.get(f'T{i}均值', 0.0) for i in range(1, 6)]
            valid = [v for v in t_vals if v != 0.0]
            record['cold_combined_回报'] = valid[-1] if valid else 0.0

        records.append(record)

    if records:
        cache_path = os.path.join(PROJECT_ROOT, 'weekly_trend.json')
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)


def run_incremental_weekly(date_str):
    """Run weekly reports for a single date + refresh previous 5 days. Returns True on success."""
    if not re.match(r'^\d{4}$', date_str):
        log.error("Date must be MMDD format (e.g., 0511)")
        return False

    all_dates = db_service.get_market_dates()

    backtest_dates = set()
    for f in glob_reports("*量化复盘报告.xlsx"):
        d = os.path.basename(f)[:4]
        if d.isdigit():
            backtest_dates.add(d)
    dates = [d for d in all_dates if d in backtest_dates]

    if date_str not in dates:
        log.error(f"Date {date_str} has no backtest report or not in sheets")
        return False

    idx = dates.index(date_str)

    # Current date + previous 5 trading days (those with backtest reports)
    target_indices = [idx] + [i for i in range(max(0, idx - 5), idx)]
    target_dates = [dates[i] for i in sorted(set(target_indices))]

    log.info(f"Processing {len(target_dates)} weekly reports: {target_dates}")

    count = 0
    for d in target_dates:
        i = dates.index(d)
        log.info(f"  [{d}] 生成礼拜攻势...")
        try:
            ok = generate_weekly_report(d, dates, i)
            if ok:
                count += 1
        except Exception as e:
            log.error(f"  [{d}] failed: {e}")

    _build_weekly_trend_cache()
    log.info(f"Done: {count}/{len(target_dates)} weekly reports generated")
    return count > 0


def main():
    dates = db_service.get_market_dates()

    # 只对已有回测报告的日期生成礼拜攻势（过滤参考数据 sheet）
    backtest_dates = set()
    for f in glob_reports("*量化复盘报告.xlsx"):
        d = os.path.basename(f)[:4]
        if d.isdigit():
            backtest_dates.add(d)
    dates = [d for d in dates if d in backtest_dates]

    existing = set()
    for f in glob_reports("*的选股策略礼拜攻势.xlsx"):
        base = os.path.basename(f)
        d = base[:4]
        if d.isdigit():
            existing.add(d)

    log.info(f"回测报告共 {len(backtest_dates)} 个交易日")
    log.info(f"已有礼拜攻势报告: {sorted(existing)}")

    count = 0
    for i, d in enumerate(dates):
        json_path = resolve_report(f'{d}的选股策略礼拜攻势.json')

        # 检查已有报告是否需要更新（n_available < 5 表示新交易日到齐了）
        if d in existing and os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as jf:
                    old = json.load(jf)
                old_n = old.get('meta', {}).get('n_available', 0)
                new_n = min(HOLD_DAYS, len(dates) - i - 1)
                if old_n >= new_n:
                    log.info(f"  [{d}] 已存在（{old_n}/{HOLD_DAYS}），跳过")
                    continue
                log.info(f"  [{d}] 有新数据（{old_n}→{new_n}/5），重新生成...")
            except Exception:
                log.info(f"  [{d}] JSON 读取失败，重新生成...")

        log.info(f"  [{d}] 生成礼拜攻势...")
        ok = generate_weekly_report(d, dates, i)
        log.info("OK" if ok else "失败")
        if ok:
            count += 1

    # ── 重建趋势缓存 ──
    _build_weekly_trend_cache()

    log.info(f"完成！本次生成 {count} 个礼拜攻势报告")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--date":
        date_str = sys.argv[2]
        success = run_incremental_weekly(date_str)
        sys.exit(0 if success else 1)
    else:
        main()
