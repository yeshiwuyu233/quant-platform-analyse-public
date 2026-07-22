"""
批量回测：为 Whole Market.xlsx 中每对连续交易日生成复盘报告
用法:  python quant_web/batch_backtest.py
"""
import json
import logging
import os
import sys
import pandas as pd
import numpy as np
import re

from data_service import df_to_table, parse_pct, parse_ratio, native_type
from report_paths import glob_reports, output_report
try:
    from . import db_service
except ImportError:
    import db_service

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER_FILE = os.path.join(PROJECT_ROOT, "Whole Market.xlsx")


def extract_ret(s):
    if pd.isna(s) or str(s).strip() == '':
        return np.nan
    matches = re.findall(r'\(([-+]?[0-9]*\.?[0-9]+)%\)', str(s))
    return float(matches[-1]) if matches else np.nan


def _valid_return_mask(df):
    return df['今日收益率'].notna()


def _success_mask(df):
    return _valid_return_mask(df) & (df['今日收益率'] >= 0)


def _format_win_rate(success_n, valid_n):
    return f"{(success_n / valid_n):.2%}" if valid_n > 0 else "0.00%"


def _format_success_ratio(df):
    valid_n = int(_valid_return_mask(df).sum()) if not df.empty else 0
    success_n = int(_success_mask(df).sum()) if valid_n > 0 else 0
    return f"{success_n / valid_n:.2%}({success_n}/{valid_n})" if valid_n > 0 else "0.00%(0/0)"


def split_empty_industries(df):
    df = df.copy()
    df['行业'] = df['行业'].fillna('')
    mask = df['行业'].astype(str).str.strip().isin(['', '空'])
    n_empty = mask.sum()
    if n_empty > 0:
        df.loc[mask, '行业'] = [f"空{i}" for i in range(1, n_empty + 1)]
    return df


def run_backtest(sheet_yesterday, sheet_today):
    df_yest = db_service.read_market_sheet(sheet_yesterday)
    df_today = db_service.read_market_sheet(sheet_today)
    if df_yest is None or df_today is None:
        raise ValueError(f"市场数据缺失: yest={sheet_yesterday}, today={sheet_today}")

    df_yest = split_empty_industries(df_yest)
    df_today = split_empty_industries(df_today)
    df_yest = df_yest.dropna(subset=['代码', '今日指标'])
    df_today = df_today.dropna(subset=['代码'])

    df_today['今日收益率'] = df_today['指标历史'].apply(extract_ret) / 100
    df_today['收益有效'] = df_today['今日收益率'].notna()
    df_today_subset = df_today[['代码', '指标历史', '今日收益率', '准确率', '今日指标']].copy()

    # 三阶胜率
    win_rate_rows = []
    for t in [0.8, 1.0, 1.2]:
        temp_pool = df_yest[(df_yest['准确率'] > 0.6) & (df_yest['今日指标'] > t)]
        temp_merged = pd.merge(temp_pool, df_today_subset, on='代码', how='left')
        total_n = len(temp_pool)
        valid_n = int(_valid_return_mask(temp_merged).sum()) if total_n > 0 else 0
        success_n = int(_success_mask(temp_merged).sum()) if valid_n > 0 else 0
        missing_n = total_n - valid_n
        win_rate_rows.append({
            '策略条件': f'准确率>0.6 & 指标>{t}',
            '总入选股数': total_n,
            '有效收益数': valid_n,
            '缺失收益数': missing_n,
            '成功数(收益>=0)': success_n,
            '失败数(收益<0)': valid_n - success_n,
            '覆盖率': f"{(valid_n / total_n):.2%}" if total_n > 0 else "0.00%",
            '策略胜率': _format_win_rate(success_n, valid_n)
        })
    win_rate_df = pd.DataFrame(win_rate_rows)

    # 回测明细
    cond_main = (df_yest['准确率'] > 0.6) & (df_yest['今日指标'] > 1.0)
    target_pool = df_yest[cond_main][['代码', '全称', '行业', '准确率', '今日指标']].copy()
    target_pool.rename(columns={'准确率': '昨日准确率', '今日指标': '昨日指标'}, inplace=True)
    backtest_df = pd.merge(target_pool, df_today_subset[['代码', '指标历史', '今日收益率']], on='代码', how='left')
    backtest_df['收益状态'] = np.where(backtest_df['今日收益率'].notna(), '有效', '缺失')
    backtest_df['回测结果'] = np.select(
        [backtest_df['今日收益率'].isna(), backtest_df['今日收益率'] >= 0],
        ['收益缺失', '成功'],
        default='失败'
    )

    # 行业分布
    ind_counts = backtest_df['行业'].value_counts().reset_index()
    ind_counts.columns = ['行业名称', '入选数量']
    ind_returns = backtest_df.groupby('行业')['今日收益率'].mean().reset_index()
    ind_valid = backtest_df.groupby('行业')['今日收益率'].count().reset_index(name='有效收益数')
    bt_stock_lists = backtest_df.groupby('行业')['全称'].apply(lambda x: '、'.join(x)).reset_index(name='包含股票名单')
    ind_stat = pd.merge(ind_counts, ind_returns, left_on='行业名称', right_on='行业').drop(columns='行业')
    ind_stat = pd.merge(ind_stat, ind_valid, left_on='行业名称', right_on='行业').drop(columns='行业')
    ind_stat = pd.merge(ind_stat, bt_stock_lists, left_on='行业名称', right_on='行业').drop(columns='行业')
    ind_stat = ind_stat.sort_values('入选数量', ascending=False)

    # 当日策略分布
    ext_rows = []
    for t in [0.8, 1.0, 1.2]:
        comp = (df_today['准确率'] > 0.6) & (df_today['今日指标'] > t)
        fit_n = comp.sum()
        ext_rows.append({'条件': f'准确率>0.6 & 指标>{t}', '符合数量': fit_n, '不符合数量': len(df_today) - fit_n})
    ext_stat_df = pd.DataFrame(ext_rows)

    # 当日行业热度
    cond_today = (df_today['准确率'] > 0.6) & (df_today['今日指标'] > 1.0)
    today_fit_df = df_today[cond_today].copy()
    today_ind_stat = today_fit_df['行业'].value_counts().reset_index()
    today_ind_stat.columns = ['当日热门行业', '今日符合数']
    today_stock_lists = today_fit_df.groupby('行业')['全称'].apply(lambda x: '、'.join(x)).reset_index(name='入选股票名单')
    if not today_ind_stat.empty:
        today_ind_stat = pd.merge(today_ind_stat, today_stock_lists, left_on='当日热门行业', right_on='行业').drop(columns='行业')

    # ── 热门拆分：按入选数层级取前 N 个行业（边界并列穿透）──
    summary_rows = []
    if not ind_stat.empty:
        real_ind = ind_stat
        if not real_ind.empty:
            total_ret = backtest_df['今日收益率'].mean() if not backtest_df.empty else 0.0

            # 按入选数分组，从高到低逐层取行业
            grouped = real_ind.groupby('入选数量')['行业名称'].apply(
                lambda x: sorted(x.tolist())
            ).reset_index()
            grouped = grouped.sort_values('入选数量', ascending=False)

            selected = []  # 选中的行业名列表
            for _, grp in grouped.iterrows():
                level_inds = grp['行业名称']
                if len(selected) >= 3:
                    break
                if len(selected) + len(level_inds) <= 3:
                    selected.extend(level_inds)
                else:
                    selected.extend(level_inds)  # 边界并列穿透
                    break

            # 为每个选中行业建一行
            for ind_name in selected:
                bh = backtest_df[backtest_df['行业'] == ind_name]
                bc = backtest_df[backtest_df['行业'] != ind_name]
                ind_count = int(real_ind[real_ind['行业名称'] == ind_name]['入选数量'].iloc[0])
                summary_rows.append({
                    '分析情形': ind_name,
                    '所属行业': ind_name,
                    '入选数量': ind_count,
                    '总收益': total_ret,
                    '该行业收益': bh['今日收益率'].mean() if not bh.empty else 0.0,
                    '其余收益': bc['今日收益率'].mean() if not bc.empty else 0.0,
                })

            # 第 N+1 行：入选数 == 1 的所有行业合并为一行
            single_inds = real_ind[real_ind['入选数量'] == 1]['行业名称'].tolist()
            single_backtest = backtest_df[backtest_df['行业'].isin(single_inds)] if single_inds else pd.DataFrame()
            single_bt_count = len(single_backtest)
            summary_rows.append({
                '分析情形': '单股行业合计',
                '所属行业': '、'.join(single_inds) if single_inds else '(无)',
                '入选数量': single_bt_count,
                '总收益': total_ret,
                '该行业收益': single_backtest['今日收益率'].mean() if single_bt_count > 0 else 0.0,
                '其余收益': backtest_df[~backtest_df['行业'].isin(single_inds)]['今日收益率'].mean()
                           if single_bt_count > 0 and not backtest_df[backtest_df['行业'].isin(single_inds)].empty
                           else 0.0,
            })
    summary_df = pd.DataFrame(summary_rows)

    # 追踪总表
    col_map = {}
    for t in [0.8, 1.0, 1.2]:
        row = next((r for r in win_rate_rows if str(t) in r['策略条件']), None)
        col_map[t] = f"{row['策略胜率']}({row['成功数(收益>=0)']}/{row['有效收益数']})" if row and row['有效收益数'] > 0 else ""

    if not ind_stat.empty:
        not_cold_df = ind_stat[ind_stat['入选数量'] > 1]
        not_cold_inds = not_cold_df['行业名称'].tolist()
        not_cold_count = not_cold_df['入选数量'].sum()
        top_3_vals = ind_stat['入选数量'].drop_duplicates().nlargest(3)
        top_3_df = ind_stat[ind_stat['入选数量'].isin(top_3_vals)]
        top_3_inds = top_3_df['行业名称'].tolist()
        top3_count = top_3_df['入选数量'].sum()
    else:
        not_cold_inds = []; top_3_inds = []; not_cold_count = 0; top3_count = 0

    nc_df = backtest_df[backtest_df['行业'].isin(not_cold_inds)]
    nc_str = _format_success_ratio(nc_df)

    t3_df = backtest_df[backtest_df['行业'].isin(top_3_inds)]
    t3_str = _format_success_ratio(t3_df)

    # 新代码：预测60% = 单股行业（入选数==1）的平均收益率
    pool_ind_counts = backtest_df['行业'].value_counts()
    single_stock_inds = pool_ind_counts[pool_ind_counts == 1].index.tolist()
    pred_60_ret = backtest_df[backtest_df['行业'].isin(single_stock_inds)]['今日收益率'].mean()

    headers = pd.MultiIndex.from_tuples([
        ('', '日期'),
        ('全样本预测正确率 （追踪天数=90）', '准确率>0.6指标>0.8'),
        ('全样本预测正确率 （追踪天数=90）', '准确率>0.6指标>1.2'),
        ('准确率>0.6指标>1', 'all'),
        ('准确率>0.6指标>1', '剔除冷门行业（一只股票）'),
        ('准确率>0.6指标>1', '前三行业（包含并列）'),
        ('全市场Alpha和行业', '预测60%'),
        ('全市场Alpha和行业', '全市场剔除冷门行业股票个数'),
        ('全市场Alpha和行业', '全市场前三行业股票个数'),
        ('下一日预测达标数', '准确率>0.6指标>0.8'),
        ('下一日预测达标数', '准确率>0.6指标>1'),
        ('下一日预测达标数', '准确率>0.6指标>1.2')
    ])
    cold_alpha_str = f"{pred_60_ret:.2%}" if not pd.isna(pred_60_ret) else ""
    data_row = [[f"2026{sheet_today}", col_map[0.8], col_map[1.2], col_map[1.0],
                 nc_str, t3_str, cold_alpha_str, not_cold_count, top3_count,
                 ext_rows[0]['符合数量'], ext_rows[1]['符合数量'], ext_rows[2]['符合数量']]]
    tracking_df = pd.DataFrame(data_row, columns=headers)

    # ── JSON 输出 ──
    tracking_dict = {
        "date_raw": f"2026{sheet_today}",
        "prev_date": sheet_yesterday,
        "date": f"{sheet_today[:2]}/{sheet_today[2:]}",
        "acc_08_raw": col_map[0.8],
        "acc_12_raw": col_map[1.2],
        "all_raw": col_map[1.0],
        "nc_raw": nc_str,
        "t3_raw": t3_str,
        "cold_alpha_raw": f"{pred_60_ret:.2%}" if not pd.isna(pred_60_ret) else "",
        "cold_stock_count": native_type(not_cold_count),
        "top3_stock_count": native_type(top3_count),
        "next_08": native_type(ext_rows[0]['符合数量']),
        "next_10": native_type(ext_rows[1]['符合数量']),
        "next_12": native_type(ext_rows[2]['符合数量']),
    }

    sheets_dict = {
        "backtest": df_to_table(backtest_df),
        "win_rates": df_to_table(win_rate_df),
        "industry_dist": df_to_table(ind_stat),
        "hot_split": df_to_table(summary_df),
        "today_dist": df_to_table(ext_stat_df),
        "today_industry": df_to_table(today_ind_stat),
    }

    # Parsed values for history
    all_temp = col_map[1.0]
    all_pct = parse_pct(all_temp)
    all_s, all_t = parse_ratio(all_temp)
    history_entry = {
        "date": f"{sheet_today[:2]}/{sheet_today[2:]}",
        "date_raw": f"2026{sheet_today}",
        "prev_date": sheet_yesterday,
        "acc_08": parse_pct(col_map[0.8]),
        "acc_12": parse_pct(col_map[1.2]),
        "all_pct": all_pct,
        "all_success": all_s,
        "all_total": all_t,
        "cold_alpha": parse_pct(f"{pred_60_ret:.2%}" if not pd.isna(pred_60_ret) else ""),
        "next_10": native_type(ext_rows[1]['符合数量']),
    }

    return {
        'tracking': tracking_df, 'backtest': backtest_df, 'win_rates': win_rate_df,
        'industry': ind_stat, 'hot_split': summary_df, 'today_dist': ext_stat_df,
        'today_industry': today_ind_stat,
        'tracking_dict': tracking_dict, 'sheets_dict': sheets_dict,
        'history_entry': history_entry,
    }


def _rebuild_history():
    """Rebuild history.json from all 量化复盘报告 JSON files."""
    history = []
    for jf in sorted(glob_reports('*量化复盘报告.json')):
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                report = json.load(f)
            entry = report.get('history_entry') or report.get('tracking')
            if entry:
                history.append(entry)
        except Exception:
            pass
    history.sort(key=lambda r: r.get('date_raw', ''))
    seen = set()
    deduped = []
    for r in history:
        dr = r.get('date_raw', '')
        if dr not in seen:
            seen.add(dr)
            deduped.append(r)
    if deduped:
        history_path = os.path.join(PROJECT_ROOT, 'history.json')
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(deduped, f, ensure_ascii=False, indent=2)



def _fix_stale_reports():
    """检查并修复因上传顺序错误导致的 stale 回测报告。

    当日期上传顺序错误时（先上传后面的日期），
    已生成的回测报告可能使用了错误的“前一天”。
    本函数扫描所有报告，匹配当前排序，
    自动重新生成不匹配的报告。
    """
    import glob, json, os

    all_dates = db_service.get_market_dates()

    fixed = []
    for jf in sorted(glob_reports("*量化复盘报告.json")):
        curr = os.path.basename(jf)[:4]
        if not curr.isdigit() or curr not in all_dates:
            continue

        idx = all_dates.index(curr)
        if idx == 0:
            continue
        expected_prev = all_dates[idx - 1]

        try:
            with open(jf, "r", encoding="utf-8") as f:
                report = json.load(f)
            stored_prev = report.get("tracking", {}).get("prev_date")
        except Exception:
            continue

        if stored_prev == expected_prev:
            continue

        log.warning(f"  [{curr}] 发现 stale 回测: prev={stored_prev}, 应为 {expected_prev}，重新生成...")
        try:
            run_single_backtest(curr, fix_stale=False)
            fixed.append(curr)
        except Exception as e:
            log.error(f"  修复 [{curr}] 失败: {e}")

    if fixed:
        log.info(f"已修复 {len(fixed)} 个 stale 回测报告: {fixed}")
    return fixed

def run_single_backtest(date_str, fix_stale=True):
    """Run backtest for a single date (MMDD format). Returns True on success."""
    if not re.match(r'^\d{4}$', date_str):
        log.error("Date must be MMDD format (e.g., 0511)")
        return False

    dates = db_service.get_market_dates()

    if date_str not in dates:
        log.error(f"Sheet {date_str} not found in Whole Market.xlsx")
        return False

    idx = dates.index(date_str)
    if idx == 0:
        log.warning(f"No previous date for {date_str}, skipping backtest")
        return False

    prev = dates[idx - 1]
    curr = date_str

    log.info(f"[{curr}] 回测 {prev} -> {curr} ...")
    try:
        result = run_backtest(prev, curr)
    except Exception as e:
        log.error(f"Backtest failed for {curr}: {e}")
        return False

    fn_final = output_report(f'{curr}量化复盘报告.xlsx')
    fn_tmp = output_report(f'.{curr}量化复盘报告.tmp.xlsx')
    with pd.ExcelWriter(fn_tmp, engine='openpyxl') as writer:
        result['tracking'].to_excel(writer, sheet_name='0.每日追踪总表')
        result['backtest'].to_excel(writer, sheet_name='1.回测明细(跨日合并)', index=False)
        result['win_rates'].to_excel(writer, sheet_name='2.三阶胜率全景对比', index=False)
        result['industry'].to_excel(writer, sheet_name='3.回测行业分布(含名单)', index=False)
        if not result['hot_split'].empty:
            result['hot_split'].to_excel(writer, sheet_name='4.并列热门拆分对比', index=False)
        result['today_dist'].to_excel(writer, sheet_name='5.当日最新策略分布', index=False)
        if not result['today_industry'].empty:
            result['today_industry'].to_excel(writer, sheet_name='6.当日最新行业热度', index=False)
    os.replace(fn_tmp, fn_final)
    log.info(f"[OK] {curr}量化复盘报告.xlsx")

    json_path = output_report(f'{curr}量化复盘报告.json')
    with open(json_path, 'w', encoding='utf-8') as jf:
        json.dump({
            "tracking": result['tracking_dict'],
            "sheets": result['sheets_dict'],
            "history_entry": result['history_entry'],
        }, jf, ensure_ascii=False, indent=2)

    _rebuild_history()
    if fix_stale:
        _fix_stale_reports()
    return True


def main():
    dates = db_service.get_market_dates()

    existing_reports = set()
    for f in glob_reports('*量化复盘报告*.xlsx'):
        d = os.path.basename(f)[:4]
        if d.isdigit():
            existing_reports.add(d)

    log.info(f"Whole Market 共 {len(dates)} 个交易日")
    log.info(f"已有复盘报告: {sorted(existing_reports)}")

    count = 0
    for i in range(1, len(dates)):
        prev, curr = dates[i - 1], dates[i]
        if curr in existing_reports:
            json_path = output_report(f'{curr}量化复盘报告.json')
            legacy_json_path = os.path.join(PROJECT_ROOT, f'{curr}量化复盘报告.json')
            if os.path.exists(json_path) or os.path.exists(legacy_json_path):
                log.info(f"  [{curr}] 已存在，跳过")
                continue
            log.info(f"  [{curr}] xlsx 存在但缺少 JSON，重新生成...")
        log.info(f"  [{curr}] 回测 {prev}→{curr} ...")
        try:
            result = run_backtest(prev, curr)
        except Exception as e:
            log.error(f"❌ {e}")
            continue
        fn_final = output_report(f'{curr}量化复盘报告.xlsx')
        fn_tmp = output_report(f'.{curr}量化复盘报告.tmp.xlsx')
        with pd.ExcelWriter(fn_tmp, engine='openpyxl') as writer:
            result['tracking'].to_excel(writer, sheet_name='0.每日追踪总表')
            result['backtest'].to_excel(writer, sheet_name='1.回测明细(跨日合并)', index=False)
            result['win_rates'].to_excel(writer, sheet_name='2.三阶胜率全景对比', index=False)
            result['industry'].to_excel(writer, sheet_name='3.回测行业分布(含名单)', index=False)
            if not result['hot_split'].empty:
                result['hot_split'].to_excel(writer, sheet_name='4.并列热门拆分对比', index=False)
            result['today_dist'].to_excel(writer, sheet_name='5.当日最新策略分布', index=False)
            if not result['today_industry'].empty:
                result['today_industry'].to_excel(writer, sheet_name='6.当日最新行业热度', index=False)
        os.replace(fn_tmp, fn_final)
        log.info(f"  [OK] {curr}量化复盘报告.xlsx")
        # ── 同时写 JSON ──
        json_path = output_report(f'{curr}量化复盘报告.json')
        with open(json_path, 'w', encoding='utf-8') as jf:
            json.dump({
                "tracking": result['tracking_dict'],
                "sheets": result['sheets_dict'],
                "history_entry": result['history_entry'],
            }, jf, ensure_ascii=False, indent=2)
        count += 1

    # ── 重建全局 history.json ──
    _rebuild_history()
    _fix_stale_reports()
    log.info(f"完成！本次生成 {count} 个复盘报告")



if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--date":
        date_str = sys.argv[2]
        success = run_single_backtest(date_str)
        sys.exit(0 if success else 1)
    else:
        main()
