"""
每日数据爬虫 — 从 data.example.com 抓取股票准确率数据。

使用宿主机 Chrome 渲染服务（crawler_service.py :14431）获取完整 HTML：
- 支持 JS 渲染（指标历史列需要）
- 无需在 Docker 内装浏览器
- 回退到 Direct-IP

被 run_pipeline.py 调用，数据写入 Whole Market.xlsx。
"""

import io
import argparse
import base64
import json
import os
import re
import ssl
import sys
import urllib.request
import pandas as pd
import time
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

try:
    from .market_writer import persist_market_dataframe
except ImportError:
    from market_writer import persist_market_dataframe


def env_or_default(name: str, default: str) -> str:
    return os.environ.get(name) or default


# ================= 基础配置 =================
DEFAULT_DATE = env_or_default("CRAWL_DATE", datetime.now().strftime("%Y%m%d"))

USERNAME = env_or_default("CRAWLER_USER", "user")
PASSWORD = env_or_default("CRAWLER_PASS", "change-me")
MIN_MARKET_ROWS = int(env_or_default("CRAWLER_MIN_ROWS", "4000"))
DIRECT_IP = env_or_default("CRAWLER_DIRECT_IP", "203.0.113.10")
DIRECT_HOST = env_or_default("CRAWLER_DIRECT_HOST", "data.example.com")

# 宿主机 Chrome 渲染服务（Docker 网关地址）
CRAWLER_SERVICE = "http://172.18.0.1:14431/fetch"

# 目标汇总文件（与 batch_backtest / batch_weekly 共用）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER_FILE = os.path.join(PROJECT_ROOT, "Whole Market.xlsx")
# ============================================


def build_target_url(target_date: str) -> str:
    """Build the standard quant-win URL for YYYYMMDD."""
    return f"https://data.example.com/{target_date}/accuracy_markov_lyz_x.html"


def validate_target_date(target_date: str) -> str:
    if not re.match(r"^\d{8}$", target_date or ""):
        raise ValueError("date must be YYYYMMDD, e.g. 20260701")
    return target_date


def extract_date(url: str) -> str:
    """从 URL 中提取月日作为 Sheet 名称 (如 0622)"""
    match = re.search(r'/(\d{4})(\d{4})/', url)
    return match.group(2) if match else "未知日期"


def validate_market_dataframe(df: pd.DataFrame):
    """Validate that the scraped table is a complete market snapshot."""
    required = {"代码", "准确率", "今日指标"}
    missing = required - set(df.columns)
    if missing:
        print(f"[-] 表格缺少关键列: {missing}")
        print(f"[-] 实际列: {list(df.columns)}")
        sys.exit(1)

    if len(df) < MIN_MARKET_ROWS:
        print(f"[-] 表格数据不完整: {len(df)} 行，低于最小阈值 {MIN_MARKET_ROWS} 行")
        sys.exit(1)


def count_market_rows_from_html(html: str) -> int:
    if not html:
        return 0
    rows = re.findall(r"<tr\b[^>]*>.*?</tr>", html, flags=re.IGNORECASE | re.DOTALL)
    return sum(1 for row in rows if re.search(r"<td\b", row, flags=re.IGNORECASE))


def build_direct_ip_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, DIRECT_IP, parts.path, parts.query, parts.fragment))


def fetch_via_chrome(url: str) -> str | None:
    """通过宿主机 Chrome 渲染服务获取完整 HTML（含 JS 渲染内容）。"""
    attempts = int(os.environ.get("CRAWLER_CHROME_RETRIES", "3"))
    retry_delay = float(os.environ.get("CRAWLER_CHROME_RETRY_DELAY", "3"))
    last_error = None

    for attempt in range(1, attempts + 1):
        payload = json.dumps({"url": url, "username": USERNAME, "password": PASSWORD}).encode()
        req = urllib.request.Request(
            CRAWLER_SERVICE,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            service_timeout = int(os.environ.get("CRAWLER_SERVICE_TIMEOUT", "420"))
            with urllib.request.urlopen(req, timeout=service_timeout) as resp:
                result = json.loads(resp.read().decode())
            if "html" in result:
                html = result["html"]
                row_count = result.get("row_count")
                if row_count is None:
                    row_count = count_market_rows_from_html(html)
                has_market_table = (
                    html
                    and "<table" in html.lower()
                    and "代码" in html
                    and "准确率" in html
                    and "今日指标" in html
                )
                if html and len(html) > 1000 and has_market_table and row_count >= MIN_MARKET_ROWS:
                    print(
                        f"[*] Chrome 服务返回 {len(html)} bytes, "
                        f"rows={row_count}, title={result.get('title')!r}, final_url={result.get('url')!r}"
                    )
                    return html
                last_error = (
                    f"Chrome 服务返回无效 HTML: {len(html or '')} bytes, "
                    f"rows={row_count}, "
                    f"title={result.get('title')!r}, final_url={result.get('url')!r}"
                )
            else:
                last_error = f"Chrome 服务返回错误: {result.get('error', 'unknown')}"
        except Exception as e:
            last_error = f"Chrome 服务请求失败: {e}"

        if attempt < attempts:
            print(f"[-] {last_error}，重试 {attempt + 1}/{attempts} ...")
            time.sleep(retry_delay)

    print(f"[-] {last_error}")
    return None


def fetch_via_direct_ip(url: str) -> str | None:
    """使用源站 IP + Host 头抓取，绕开域名 SNI 被 reset 的路径。"""
    attempts = int(os.environ.get("CRAWLER_DIRECT_IP_RETRIES", "3"))
    retry_delay = float(os.environ.get("CRAWLER_DIRECT_IP_RETRY_DELAY", "2"))
    timeout = int(os.environ.get("CRAWLER_DIRECT_IP_TIMEOUT", "90"))
    direct_url = build_direct_ip_url(url)
    auth = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    context = ssl._create_unverified_context()
    last_error = None

    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            direct_url,
            headers={
                "Host": DIRECT_HOST,
                "Authorization": f"Basic {auth}",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                body = resp.read()
            html = body.decode("utf-8", errors="replace")
            row_count = count_market_rows_from_html(html)
            has_market_table = (
                html
                and "<table" in html.lower()
                and "代码" in html
                and "准确率" in html
                and "今日指标" in html
            )
            if has_market_table and row_count >= MIN_MARKET_ROWS:
                print(f"[*] Direct-IP 返回 {len(html)} bytes, rows={row_count}, url={direct_url}")
                return html
            last_error = f"Direct-IP 返回数据不完整: {len(html)} bytes, rows={row_count}"
        except Exception as e:
            last_error = f"Direct-IP 请求失败: {e}"

        if attempt < attempts:
            print(f"[-] {last_error}，重试 {attempt + 1}/{attempts} ...")
            time.sleep(retry_delay)

    print(f"[-] {last_error}")
    return None


def parse_table_from_html(html: str, sheet_name: str) -> pd.DataFrame:
    """从 HTML 中解析表格，返回 DataFrame。"""
    if isinstance(html, bytes):
        html = html.decode('utf-8')
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError as e:
        print(f"[-] HTML 中未找到表格数据: {e}")
        sys.exit(1)
    if not tables:
        print("[-] HTML 中未找到表格数据，可能该日期网页不存在。")
        sys.exit(1)

    df = tables[0]
    # 标准化列名：去掉多余空格
    df.columns = [str(c).strip() for c in df.columns]

    print(f"[*] 表头: {list(df.columns)}")
    print(f"[*] 获取到 {len(df)} 条数据")
    validate_market_dataframe(df)

    # 检查指标历史是否为空
    if '指标历史' in df.columns:
        empty_hist = df['指标历史'].isna().sum() + (df['指标历史'] == '').sum()
        if empty_hist == len(df):
            print("[!] 警告：指标历史列全部为空（可能 JS 未渲染）")
    return df


def fetch_and_sync_data(target_date: str | None = None, dry_run: bool = False):
    """抓取数据并同步到 Whole Market.xlsx

    支持 CRAWL_METHOD 环境变量（由 pipeline_wrapper.sh 的降级系统控制）:
      - chrome        → 使用宿主机 Chrome 渲染服务（默认）
      - direct_ip     → 使用源站 IP + Host 头直连，绕开域名 SNI reset
    """
    target_date = validate_target_date(target_date or DEFAULT_DATE)
    target_url = build_target_url(target_date)
    sheet_name = extract_date(target_url)
    method = os.environ.get("CRAWL_METHOD", "chrome")

    html = None

    if method == "chrome":
        print(f"[*] [Chrome服务] 正在抓取 {target_url} ...")
        html = fetch_via_chrome(target_url)
        if html is None:
            print(f"[*] [Direct-IP兜底] Chrome 未获取完整数据，改用源站 IP 抓取 {target_url} ...")
            html = fetch_via_direct_ip(target_url)
    elif method == "direct_ip":
        print(f"[*] [Direct-IP] 正在抓取 {target_url} ...")
        html = fetch_via_direct_ip(target_url)
    else:
        print(f"[-] 未知 CRAWL_METHOD: {method}")
        sys.exit(1)

    if html is None:
        print("[-] 所有爬取方式均失败")
        sys.exit(1)

    print(f"[*] 页面加载完成 ({len(html) // 1024} KB)")

    # 3. 解析表格
    df = parse_table_from_html(html, sheet_name)

    if dry_run:
        print(f"[+] DRY_RUN 完成：{target_date} / Sheet {sheet_name}，解析 {len(df)} 行，不写入 {MASTER_FILE}")
        return df

    # 4. 保存
    write_result = persist_market_dataframe(target_date, df)
    mode = write_result["mode"]
    print(f"[*] MARKET_STORAGE_MODE={mode}")
    if mode == "shadow":
        if write_result["shadow_ok"]:
            print(f"[+] SHADOW_CSV_OK rows={write_result['csv_rows']}")
        else:
            print(f"[!] SHADOW_CSV_FAILED: {write_result['shadow_error']}")
    print(f"[+] 任务完成！当日 {target_date} 数据已按 {mode} 模式保存")
    return df


if __name__ == "__main__":
    """
    单独测试（不经过 run_pipeline.py）：
      docker exec quant-web python /app/quant_web/daily_spider.py
    """
    parser = argparse.ArgumentParser(description="Fetch quant-win daily market data")
    parser.add_argument("--date", default=None, help="target date in YYYYMMDD, default: today or CRAWL_DATE")
    parser.add_argument("--dry-run", action="store_true", help="fetch and parse only, do not write Whole Market.xlsx")
    args = parser.parse_args()
    fetch_and_sync_data(target_date=args.date, dry_run=args.dry_run)
