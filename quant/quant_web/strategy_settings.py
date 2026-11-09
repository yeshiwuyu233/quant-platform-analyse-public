"""Validated, versioned strategy parameters shared by all web workers."""
import copy
import fcntl
import hashlib
import json
import math
import os
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SETTINGS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'strategy_settings.json'
_ACTIVE = ContextVar('active_strategy_settings', default=None)
_ACCOUNT = ContextVar('strategy_settings_account', default=None)
STATE_NAMES = ('超跌反弹模式', '超涨回调模式', '系统性暴跌模式', '下行模式', '振荡模式', '上行模式')
INITIAL_SETTINGS = {
    'thresholds': {'rebound_below': 22.0, 'down_below': 45.0, 'range_ceiling': 55.0, 'pullback_above': 78.0},
    'systemic_count': 60,
    'daily_leverage': 6.0,
    'states': {str(i): {'direction': 1 if i in (1, 5, 6) else -1, 'allocation_pct': 80.0 if i <= 3 else 50.0} for i in range(1, 7)},
}
DEFAULT_SETTINGS = copy.deepcopy(INITIAL_SETTINGS)


def initial_settings():
    """Return the original approved rules, independent of saved system defaults."""
    return copy.deepcopy(INITIAL_SETTINGS)


class SettingsError(ValueError):
    pass


class SettingsConflict(SettingsError):
    pass


def _number(value, label, low, high):
    if isinstance(value, bool):
        raise SettingsError(f'{label}必须是数字')
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise SettingsError(f'{label}必须是数字')
    if not math.isfinite(value) or not low <= value <= high:
        raise SettingsError(f'{label}请填写{low:g}～{high:g}之间的数字')
    return value


def validate_settings(raw):
    try:
        t = raw['thresholds']
        thresholds = {key: _number(t[key], label, 0, 100) for key, label in (
            ('rebound_below', '超跌反弹阈值'), ('down_below', '下行阈值'),
            ('range_ceiling', '振荡上限'), ('pullback_above', '超涨回调阈值'))}
        values = list(thresholds.values())
        if not 0 < values[0] < values[1] < values[2] < values[3] < 100:
            raise SettingsError('四个概率值请从小到大填写：超跌反弹、下行、振荡上限、超涨回调，且都要大于0、小于100。')
        count = _number(raw['systemic_count'], '系统性暴跌股票数门槛', 1, 10000)
        if not count.is_integer():
            raise SettingsError('股票数门槛必须是整数')
        leverage = _number(raw['daily_leverage'], '日频杠杆', 1, 20)
        states = {}
        for i, name in enumerate(STATE_NAMES, 1):
            state = raw['states'][str(i)]
            direction = _number(state['direction'], f'{name}方向', -1, 1)
            if direction not in (-1, 0, 1):
                raise SettingsError('方向只能选择做多、做空或空仓')
            allocation = _number(state['allocation_pct'], f'{name}仓位', 0, 100)
            states[str(i)] = {'direction': int(direction), 'allocation_pct': allocation}
        return {'thresholds': thresholds, 'systemic_count': int(count), 'daily_leverage': leverage, 'states': states}
    except (KeyError, TypeError) as exc:
        raise SettingsError('设置没有填全，请检查后再保存') from exc


def _settings_path():
    account = _ACCOUNT.get()
    if account is None:
        return SETTINGS_PATH
    key = hashlib.sha256(str(account).encode('utf-8')).hexdigest()
    return SETTINGS_PATH.parent / 'strategy_settings_users' / (key + '.json')


@contextmanager
def using_account(account):
    token = _ACCOUNT.set(account)
    try:
        yield
    finally:
        _ACCOUNT.reset(token)


def _read_document(path):
    if not path.exists():
        return {'schema_version': 1, 'version': 0, 'updated_at': '初始配置', 'updated_by': '系统默认',
                'config': copy.deepcopy(DEFAULT_SETTINGS), 'history': []}
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc['config'] = validate_settings(doc['config'])
        if doc.get('schema_version') != 1 or not isinstance(doc.get('version'), int) or not isinstance(doc.get('history'), list):
            raise SettingsError('保存的策略设置格式有误，请联系管理员')
        return doc
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SettingsError('暂时无法读取策略设置，请联系管理员检查') from exc


def load_document():
    path = _settings_path()
    if _ACCOUNT.get() is None:
        return {**_read_document(path), 'source': 'system'}
    if path.exists():
        return {**_read_document(path), 'source': 'personal'}
    defaults = _read_document(SETTINGS_PATH)
    return {'schema_version': 1, 'version': 0, 'updated_at': defaults['updated_at'],
            'updated_by': '系统默认', 'config': defaults['config'], 'history': [],
            'source': 'default', 'default_version': defaults['version']}


def get_settings():
    active = _ACTIVE.get()
    return active if active is not None else load_document()['config']


@contextmanager
def using_settings(config):
    token = _ACTIVE.set(config)
    try:
        yield config
    finally:
        _ACTIVE.reset(token)


def save_settings(raw, *, actor, expected_version, restore=False):
    proposed = validate_settings(raw) if not restore else None
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = load_document()
        if current['version'] != expected_version:
            raise SettingsConflict('设置已在其他页面更新，请刷新后再修改')
        if restore:
            if not current['history']:
                raise SettingsError('还没有上一版设置')
            proposed = validate_settings(current['history'][-1]['config'])
        snapshot = {key: current[key] for key in ('version', 'updated_at', 'updated_by', 'config')}
        doc = {'schema_version': 1, 'version': current['version'] + 1,
               'updated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
               'updated_by': str(actor), 'config': proposed,
               'history': (current['history'] + [snapshot])[-50:]}
        handle, temp = tempfile.mkstemp(prefix='.strategy-', suffix='.json', dir=path.parent)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump(doc, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return doc


def parse_form(form):
    return validate_settings({
        'thresholds': {key: form.get(key) for key in DEFAULT_SETTINGS['thresholds']},
        'systemic_count': form.get('systemic_count'), 'daily_leverage': form.get('daily_leverage'),
        'states': {str(i): {'direction': form.get(f'direction_{i}'), 'allocation_pct': form.get(f'allocation_{i}')} for i in range(1, 7)},
    })


def rule_rows(config):
    t = config['thresholds']
    conditions = (f"概率 <{t['rebound_below']:g}%", f"概率 >{t['pullback_above']:g}%",
                  f"合格股票数 <{config['systemic_count']}只",
                  f"{t['rebound_below']:g}% ≤ 概率 <{t['down_below']:g}%",
                  f"{t['down_below']:g}% ≤ 概率 ≤{t['range_ceiling']:g}%",
                  f"{t['range_ceiling']:g}% < 概率 ≤{t['pullback_above']:g}%")
    rows = []
    for i, (name, condition) in enumerate(zip(STATE_NAMES, conditions), 1):
        state = config['states'][str(i)]
        direction = state['direction'] if state['allocation_pct'] else 0
        label = ('做多' if direction > 0 else '做空') + f"{state['allocation_pct']:g}%" if direction else '空仓'
        rows.append({'id': i, 'name': name, 'condition': condition, 'direction': direction,
                     'position': label, 'allocation_pct': state['allocation_pct'],
                     'exposure': direction * state['allocation_pct'] / 100 * config['daily_leverage']})
    return rows
