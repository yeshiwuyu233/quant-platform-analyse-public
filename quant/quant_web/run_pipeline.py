"""每日量化流水线 —— 供 Docker 定时任务调用。

运行顺序:
  1. daily_spider.py  爬取今日数据（URL 自动按日期构造）
  2. batch_backtest.py  批量回测所有新日期
  3. batch_weekly.py    批量生成所有新礼拜攻势
  4. 刷新中证1000指数缓存（供历史收益图使用）

用法:
  docker exec quant-web python /app/quant_web/run_pipeline.py
"""
import datetime
import logging
import smtplib
import subprocess
import sys
import os
import json
import glob
import re
from email.mime.text import MIMEText

try:
    from .report_paths import glob_reports, resolve_report
except Exception:
    from report_paths import glob_reports, resolve_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_trading_day() -> bool:
    import pandas as pd
    import akshare as ak

    today = datetime.datetime.now().date()
    try:
        log.info(">>> 核对A股交易日历...")
        calendar_df = ak.tool_trade_date_hist_sina()
        trade_dates = pd.to_datetime(calendar_df["trade_date"]).dt.date.tolist()
        return today in trade_dates
    except Exception as e:
        log.warning(f"[!] 获取交易日历失败: {e}，按工作日判断")
        return today.weekday() < 5


def crawl_today() -> str:
    """爬取今日数据。

    Returns:
        'ok' — Chrome 抓取成功
        'degraded' — Chrome 失败，Direct-IP 兜底成功
        （异常时 raise，由调用方处理）
    """
    log.info(">>> 爬取今日数据...")
    crawler = os.path.join(PROJECT_ROOT, "quant_web", "daily_spider.py")
    env = os.environ.copy()
    env['PYTHONPATH'] = os.path.join(PROJECT_ROOT, 'quant_web')
    result = subprocess.run(
        [sys.executable, crawler],
        capture_output=True, text=True,
        cwd=PROJECT_ROOT, env=env,
    )
    # 输出到日志
    for line in (result.stdout + result.stderr).split('\n'):
        line = line.strip()
        if line:
            log.info(f"[爬虫] {line}")
    if result.returncode != 0:
        raise RuntimeError(f"爬虫退出码 {result.returncode}")
    if "降级" in result.stdout:
        log.warning("爬虫降级至 Direct-IP 兜底")
        return "degraded"
    return "ok"


def run_backtest():
    log.info(">>> 批量回测...")
    script = os.path.join(PROJECT_ROOT, "quant_web", "batch_backtest.py")
    env = os.environ.copy()
    env['PYTHONPATH'] = os.path.join(PROJECT_ROOT, 'quant_web')
    subprocess.run([sys.executable, script], check=True, cwd=PROJECT_ROOT, env=env)


def run_weekly():
    log.info(">>> 批量礼拜攻势...")
    script = os.path.join(PROJECT_ROOT, "quant_web", "batch_weekly.py")
    env = os.environ.copy()
    env['PYTHONPATH'] = os.path.join(PROJECT_ROOT, 'quant_web')
    subprocess.run([sys.executable, script], check=True, cwd=PROJECT_ROOT, env=env)


def refresh_market_cache(full_date: str) -> bool:
    """Best-effort refresh of the SQLite market cache after market data changes."""
    try:
        try:
            from .market_store import get_storage_mode
            from .refresh_market_cache import refresh_market_cache as refresh
        except Exception:
            from market_store import get_storage_mode
            from refresh_market_cache import refresh_market_cache as refresh
        mode = get_storage_mode().value
        rows = refresh(full_date)
        log.info(">>> SQLite market cache refreshed: mode=%s date=%s rows=%s", mode, full_date, rows)
        return True
    except Exception as e:
        log.warning("[!] SQLite market cache refresh failed: %s", e)
        return False


def refresh_index_cache() -> bool:
    """Best-effort refresh of CSI1000 index data used by history charts."""
    try:
        try:
            from . import index_service
        except Exception:
            import index_service
        counts = index_service.update_index_cache(symbols=["sh000852"])
        count = counts.get("sh000852", 0)
        log.info(">>> 中证1000指数缓存已刷新: %s rows", count)
        return True
    except Exception as e:
        log.warning("[!] 中证1000指数缓存刷新失败: %s", e)
        return False


# ═══════════════════════════════════════════════
# 邮件通知系统（自媒体风格标题 + 极简正文）
# ═══════════════════════════════════════════════

def _gather_email_data() -> dict:
    """收集当日回测 + 礼拜攻势数据，用于邮件排版。"""
    today_mmdd = datetime.datetime.now().strftime("%m%d")
    data: dict = {"today_mmdd": today_mmdd}

    # ── 回测数据 ──
    bt_files = sorted(glob_reports("*量化复盘报告.json"))
    if bt_files:
        try:
            with open(bt_files[-1], 'r', encoding='utf-8') as f:
                bt = json.load(f)
            data['bt'] = bt.get('tracking', {})
            data['bt_sheets'] = bt.get('sheets', {})
        except Exception:
            data['bt'] = {}
            data['bt_sheets'] = {}

        # 前一日（用于趋势对比）
        if len(bt_files) >= 2:
            try:
                with open(bt_files[-2], 'r', encoding='utf-8') as f:
                    data['bt_prev'] = json.load(f).get('tracking', {})
            except Exception:
                data['bt_prev'] = {}
        else:
            data['bt_prev'] = {}
    else:
        data['bt'] = data['bt_prev'] = data['bt_sheets'] = {}

    # ── 礼拜攻势数据 ──
    wk_files = sorted(glob_reports("*选股策略礼拜攻势.json"))
    if wk_files:
        try:
            with open(wk_files[-1], 'r', encoding='utf-8') as f:
                data['wk'] = json.load(f)
        except Exception:
            data['wk'] = {}
        data['wk_settle'] = _find_settle_weekly(bt_files, wk_files, today_mmdd)
    else:
        data['wk'] = data['wk_settle'] = {}

    return data


def _find_settle_weekly(bt_files: list, wk_files: list, today_mmdd: str) -> dict:
    """查找 5 交易日前（结仓日）的礼拜攻势报告。"""
    bt_dates = [os.path.basename(f)[:4] for f in bt_files]
    if today_mmdd in bt_dates:
        idx = bt_dates.index(today_mmdd)
        settle_idx = idx - 5
        if settle_idx >= 0:
            settle_date = bt_dates[settle_idx]
            settle_path = resolve_report(f"{settle_date}的选股策略礼拜攻势.json")
            try:
                with open(settle_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def _pct_str(value) -> str:
    """将百分比值转为显示字符串，如 +2.1%。"""
    try:
        v = float(value)
        return f"{v:+.1f}%" if v != 0 else "0.0%"
    except (ValueError, TypeError):
        return str(value) if value else "?"


def _extract_num(s) -> float:
    """从 '45.57%(72/158)' 或 '0.24%' 或 111 中提取数值。"""
    if s is None:
        return 0.0
    try:
        return float(s)  # 已经是数字
    except (ValueError, TypeError):
        pass
    s = str(s).strip()
    m = re.match(r'([+-]?\d+\.?\d*)', s)
    return float(m.group(1)) if m else 0.0


def _pct_from_str(s: str) -> float:
    """从 '3.20%' 或 '0.24%' 字符串提取浮点数。"""
    return _extract_num(s)


def _trend_str_bt(data, field) -> str:
    """回测指标趋势简写，如 ↑1.2。"""
    cur = data.get('bt', {}).get(field)
    prev = data.get('bt_prev', {}).get(field)
    cur_n = _extract_num(cur)
    prev_n = _extract_num(prev)
    diff = cur_n - prev_n
    if abs(diff) < 0.005:
        return ""
    return f"↑{diff:.1f}" if diff > 0 else f"↓{abs(diff):.1f}"


def _build_subject(data: dict, status_emoji: str, error_type: str = "") -> str:
    """动态生成自媒体风格邮件标题。"""
    bt = data.get('bt', {})
    wk = data.get('wk', {})
    wk_settle = data.get('wk_settle', {})

    # 流水线失败 — 带上具体失败原因
    if status_emoji == '❌':
        if error_type:
            return f'❌ {error_type}'
        return '❌ 流水线异常 — 正在排查问题'

    win_rate = bt.get('all_raw')
    cold_alpha = bt.get('cold_alpha_raw')
    next_10 = bt.get('next_10', 0)

    # 结仓综合收益率
    settle_ret = _avg_settle_return(wk_settle)

    # 亮点行业（当日收益率最高）
    highlight_industry, highlight_ret = _find_highlight_industry(data)

    # ── 情绪判断（提取数字对比）──
    wr = _extract_num(win_rate)
    ca = _extract_num(cold_alpha)

    if highlight_industry and highlight_ret and highlight_ret > 4.0:
        title = f"✅ {highlight_industry}板块异军突起 +{highlight_ret:.1f}%，发生了什么？"
    elif ca > 3.0:
        title = f"✅ 偷偷赚钱！冷门Alpha +{ca:.1f}%再创新高"
    elif wr > 58 and settle_ret and settle_ret > 2.0:
        ind_name = highlight_industry or "多板块"
        title = f"✅ 全线飘红！胜率飙至 {wr:.1f}%，{ind_name}怒涨 +{settle_ret:.1f}%"
    elif wr < 55 or (settle_ret and settle_ret < 0):
        ca_s = f"{ca:.1f}" if ca else "?"
        title = f"✅ 信号转弱！胜率跌破 {wr:.1f}%，冷门Alpha收窄至 +{ca_s}%"
    else:
        title = f"✅ 平稳收关 | 胜率 {wr:.1f}%，明日{next_10}只待验证"

    return f"{status_emoji} {title[1:].strip()}"


def _avg_settle_return(wk_settle: dict):
    """计算结仓日的综合平均回报（百分比）。"""
    std = (wk_settle.get('standard') or {}).get('summary', [])
    rets = []
    for s in std:
        ret = s.get('平均持仓回报', '')
        p = _pct_from_str(ret)
        if p:
            rets.append(p)
    return (sum(rets) / len(rets)) if rets else None


def _find_highlight_industry(data: dict):
    """找出当日收益率最高的行业。"""
    rows = data.get('bt_sheets', {}).get('industry_dist', {}).get('rows', [])
    if not rows:
        return None, None
    best = max(rows, key=lambda r: float(r.get('今日收益率', 0) or 0))
    name = best.get('行业名称', '')
    try:
        ret = float(best.get('今日收益率', 0)) * 100  # 转百分比
    except (ValueError, TypeError):
        ret = 0
    return name, ret


def _build_body(data: dict, elapsed: float, status_emoji: str, degraded: bool, error_type: str = "") -> str:
    """排版邮件正文。"""
    bt = data.get('bt', {})
    wk = data.get('wk', {})
    wk_settle = data.get('wk_settle', {})
    today_mmdd = data.get('today_mmdd', '????')
    date_label = f"{today_mmdd[:2]}/{today_mmdd[2:]}"

    lines = []

    # ── 标题行（wr 原始格式如 "45.57%(72/158)"，直接展示）──
    wr = bt.get('all_raw', '?')
    cold = bt.get('cold_alpha_raw', '?')
    settle_ret = _avg_settle_return(wk_settle)
    settle_str = f"{settle_ret:+.1f}%" if settle_ret else "?"
    wr_trend = _trend_str_bt(data, 'all_raw')
    lines.append(f"📊 量化日报 {date_label} {status_emoji} {elapsed:.0f}s  |  胜率 {wr} {wr_trend}  |  结仓 {settle_str}")
    lines.append("─" * 85)
    lines.append("")

    # ── 流水线失败时显示诊断信息 ──
    if status_emoji == '❌' and error_type:
        lines.append(f"🔍 诊断报告")
        lines.append(f"  问题: {error_type}")
        lines.append(f"  耗时: {elapsed:.0f}s")
        lines.append(f"  建议: 查看 /var/log/quant/pipeline.log 获取详细日志")
        lines.append(f"  排查: 'tail -30 /var/log/quant/pipeline.log'")
        lines.append("")
        lines.append("─" * 85)
        lines.append("")

    # ── 核心指标 ──
    wr_t = _trend_str_bt(data, 'all_raw')
    ca_t = _trend_str_bt(data, 'cold_alpha_raw')
    wr_s = f"{wr}  {wr_t}" if wr != '?' else "?"
    ca_s = f"+{cold}  {ca_t}" if cold != '?' else "?"
    nt = bt.get('next_10', '?')
    nt_t = _trend_str_bt(data, 'next_10')
    nt_s = f"{nt}只 {nt_t}" if nt != '?' else "?"

    lines.append(f"  胜率      {wr_s:<28}追踪天数   5日")
    lines.append(f"  冷门Alpha {ca_s:<28}明日达标   {nt_s}")
    lines.append("")

    # ── 结仓 ──
    if wk_settle:
        lines.append(f"💰 结仓 (D-5 → 今日)                                 合计 {settle_str}")

        std = (wk_settle.get('standard') or {}).get('summary', [])
        total_stocks = sum(s.get('入选股票数', 0) for s in std)
        wrs = [_pct_from_str(s.get('策略胜率(>0%)', '')) for s in std if s.get('策略胜率(>0%)')]
        avg_wr = f"{sum(wrs)/len(wrs):.0f}%" if wrs else "?"
        lines.append(f"  全市场    {total_stocks}只  胜率 {avg_wr}")

        top = (wk_settle.get('top_industries') or {}).get('summary', [])
        top_parts = [f"{s['策略分组']} {_pct_str(s.get('平均持仓回报', 0))}" for s in top[:3]]
        if top_parts:
            lines.append(f"  前三行业  {'  |  '.join(top_parts)}")

        cold = (wk_settle.get('cold_industry') or {}).get('summary', [])
        cold_parts = [f"{s['策略分组']} {_pct_str(s.get('平均持仓回报', 0))}" for s in cold[:3]]
        if cold_parts:
            lines.append(f"  冷门行业  {'  |  '.join(cold_parts)}")
        lines.append("")

    # ── 新建仓 ──
    if wk:
        n_avail = (wk.get('meta') or {}).get('n_available', 0)
        lines.append(f"🆕 新建仓 ({n_avail}/5天可用)")
        std_new = (wk.get('standard') or {}).get('summary', [])
        parts = [f"{s['策略分组']} {s['入选股票数']}只" for s in std_new if s.get('入选股票数', 0) > 0]
        if parts:
            lines.append(f"  {'  |  '.join(parts)}")
        lines.append("")

    # ── 行业热度 ──
    rows_industry = data.get('bt_sheets', {}).get('industry_dist', {}).get('rows', [])
    if rows_industry:
        lines.append("🏭 行业热度 TOP5")
        sorted_ind = sorted(rows_industry, key=lambda r: float(r.get('今日收益率', 0) or 0), reverse=True)
        max_count = max(float(r.get('入选数量', 1) or 1) for r in sorted_ind[:5])
        for row in sorted_ind[:5]:
            name = row.get('行业名称', '?')
            count = int(float(row.get('入选数量', 0)))
            ret = float(row.get('今日收益率', 0)) * 100
            bar_len = max(1, int(count / max_count * 8)) if max_count and count > 0 else 0
            lines.append(f"  {name:<8} {count:3d}只  {ret:+.1f}%  {'█' * bar_len}")
        lines.append("")

    # ── 底栏 ──
    lines.append("─" * 85)

    notes = []
    if degraded:
        notes.append("* 爬虫降级至 Direct-IP 兜底（Chrome 未获取完整数据）")
    if elapsed > 300:
        notes.append(f"* 耗时 {elapsed:.0f}s，建议关注流水线性能")

    for n in notes:
        lines.append(n)
    lines.append(f"量化分析系统 · {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(lines)


def send_notification(success: bool, degraded: bool, data: dict, elapsed: float, error_type: str = ""):
    """流水线结束后发送邮件通知。"""
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))

    if not smtp_user or not smtp_pass:
        log.info("[通知] SMTP 未配置，跳过邮件通知")
        return

    notify_to = os.environ.get("NOTIFY_EMAIL", smtp_user)

    # 确定状态 emoji
    if not success:
        status_emoji = '❌'
    elif degraded:
        status_emoji = '⚠️'
    else:
        status_emoji = '✅'

    subject = _build_subject(data, status_emoji, error_type)
    body = _build_body(data, elapsed, status_emoji, degraded, error_type)

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = notify_to
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as s:
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        log.info(f"[通知] 邮件已发送至 {notify_to}")
        log.info(f"[通知] 标题: {subject}")
    except Exception as e:
        log.warning(f"[通知] 邮件发送失败: {e}")


def main():
    if not is_trading_day():
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        log.info(f"[{date_str}] 非交易日，跳过。")
        return

    start = datetime.datetime.now()
    log.info(f"\n[{start.strftime('%Y-%m-%d %H:%M:%S')}] 开始量化流水线\n")

    success = True
    degraded = False
    error_type = None

    try:
        crawl_status = crawl_today()
        degraded = (crawl_status == "degraded")
        full_date = datetime.datetime.now().strftime("%Y%m%d")
    except Exception as e:
        error_msg = str(e)
        log.error(f"爬取失败: {error_msg}")
        success = False
        error_type = f"爬取失败 — {error_msg}"

    if success and not refresh_market_cache(full_date):
        log.error("SQLite market cache refresh failed; reports not started")
        success = False
        error_type = "SQLite market cache refresh failed"

    if success:
        try:
            run_backtest()
        except Exception as e:
            error_msg = str(e)
            log.error(f"回测失败: {error_msg}")
            success = False
            error_type = f"回测失败 — {error_msg}"

    if success:
        try:
            run_weekly()
        except Exception as e:
            error_msg = str(e)
            log.error(f"礼拜攻势失败: {error_msg}")
            success = False
            error_type = f"礼拜攻势失败 — {error_msg}"

    if success:
        refresh_index_cache()

    elapsed = (datetime.datetime.now() - start).total_seconds()
    data = _gather_email_data()

    log.info(f"\n流水线{'完成' if success else '异常'}！耗时 {elapsed:.0f}s")
    send_notification(success, degraded, data, elapsed, error_type or "")
    return 0 if success else 1  # 返回码供调用方（pipeline_wrapper）判断


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
