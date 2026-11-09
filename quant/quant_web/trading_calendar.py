"""Exchange sessions, available independently of today's market snapshot."""
import importlib
import json
import os
import re
import tempfile
from pathlib import Path

CALENDAR_PATH = Path(__file__).resolve().parent.parent / 'index_cache' / 'trading_calendar.json'
SOURCE_URL = 'https://finance.sina.com.cn/realstock/company/klc_td_sh.txt'


def _fetch_sessions():
    import akshare as ak
    import pandas as pd
    import requests
    from py_mini_racer import py_mini_racer

    response = requests.get(SOURCE_URL, timeout=10)
    response.raise_for_status()
    decoder = py_mini_racer.MiniRacer()
    decoder.eval(importlib.import_module(ak.tool_trade_date_hist_sina.__module__).hk_js_decode)
    encoded = response.text.split('=', 1)[1].split(';', 1)[0].replace('"', '')
    sessions = sorted(set(pd.to_datetime(decoder.call('d', encoded)).strftime('%Y%m%d').tolist()))
    if len(sessions) < 1000:
        raise ValueError('Exchange calendar response is incomplete')
    return sessions


def load_sessions(today):
    cached = []
    try:
        data = json.loads(CALENDAR_PATH.read_text(encoding='utf-8'))
        cached = sorted(set(data['dates']))
        if not cached or any(not re.fullmatch(r'20\d{6}|19\d{6}', d) for d in cached):
            cached = []
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if cached and cached[-1] >= today:
        return cached
    try:
        sessions = _fetch_sessions()
        CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(prefix='.calendar-', dir=CALENDAR_PATH.parent)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump({'source': SOURCE_URL, 'dates': sessions}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, CALENDAR_PATH)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return sessions
    except Exception:
        if cached:
            return cached
        raise
