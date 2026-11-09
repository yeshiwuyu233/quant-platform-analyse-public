"""Daily IM marks from the exchange, keyed by the session being traded."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, InvalidOperation
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

try:
    from . import trading_calendar
except ImportError:
    import trading_calendar


CACHE_PATH = Path(__file__).resolve().parent.parent / 'index_cache' / 'im_daily.json'
MULTIPLIER = 200


def parse_daily_quote(payload, date):
    """Choose among the day's listed contracts by previous-session open interest."""
    contracts = []
    for row in ElementTree.fromstring(payload).findall('dailydata'):
        code = row.findtext('instrumentid', '')
        if re.fullmatch(r'IM\d{4}', code):
            if row.findtext('tradingday') != date:
                raise ValueError(f'{date}: wrong trading day in {code} quote')
            contracts.append((int(row.findtext('preopeninterest')), code, row))
    if not contracts:
        raise ValueError(f'{date}: no IM contracts in exchange data')
    previous_interest, contract, row = max(contracts, key=lambda item: (item[0], item[1]))
    opening = Decimal(row.findtext('openprice'))
    closing = Decimal(row.findtext('closeprice'))
    if (previous_interest <= 0 or int(row.findtext('volume')) <= 0
            or any(not price.is_finite() or price <= 0 for price in (opening, closing))):
        raise ValueError(f'{date}: missing valid open or close for {contract}')
    return {'contract': contract, 'open': str(opening), 'close': str(closing),
            'previous_open_interest': previous_interest}


def _fetch_quote(date):
    url = f'http://www.cffex.com.cn/sj/hqsj/rtj/{date[:6]}/{date[6:]}/index.xml'
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=8) as response:
        return parse_daily_quote(response.read(), date)


def load_quotes(path=None):
    try:
        quotes = json.loads(Path(path or CACHE_PATH).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    if not isinstance(quotes, dict):
        raise ValueError('Invalid IM quote cache')
    return quotes


def refresh_quotes(dates, path=None):
    """Fetch missing sessions, publishing a merged cache with one atomic replace."""
    target = Path(path or CACHE_PATH)
    cached = load_quotes(target)
    missing = sorted(set(dates) - cached.keys())
    quotes, failures = {}, {}

    def fetch(date):
        try:
            return date, _fetch_quote(date), None
        except (OSError, TypeError, ValueError, InvalidOperation, ElementTree.ParseError) as exc:
            return date, None, str(exc)

    with ThreadPoolExecutor(max_workers=4) as executor:
        for date, quote, error in executor.map(fetch, missing):
            if quote is None:
                failures[date] = error
            else:
                quotes[date] = quote

    if quotes:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            merged = load_quotes(target)
            merged.update(quotes)
            fd, name = tempfile.mkstemp(prefix='.im-daily-', dir=target.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(merged, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, target)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
    return len(quotes), failures


def refresh_recent():
    today = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
    sessions = [date for date in trading_calendar.load_sessions(today) if date <= today]
    return refresh_quotes(sessions[-5:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--output', type=Path, default=CACHE_PATH)
    args = parser.parse_args()
    for date in (args.start, args.end):
        if datetime.strptime(date, '%Y%m%d').strftime('%Y%m%d') != date:
            parser.error('dates must use YYYYMMDD')
    sessions = [date for date in trading_calendar.load_sessions(args.end) if args.start <= date <= args.end]
    if not sessions:
        parser.error('no exchange sessions in the requested range')
    added, failures = refresh_quotes(sessions, args.output)
    print(json.dumps({'sessions': len(sessions), 'added': added, 'failures': failures}, ensure_ascii=False))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
