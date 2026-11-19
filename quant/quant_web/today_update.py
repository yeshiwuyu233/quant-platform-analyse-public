"""One-click daily refresh, serialized with uploads and the scheduled pipeline."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import jsonify, request

ROOT = Path(__file__).resolve().parent.parent
ZONE = ZoneInfo('Asia/Shanghai')


class PipelineBusy(Exception):
    pass


def now():
    return datetime.now(ZONE)


def acquire_lock(root=ROOT):
    path = Path(root) / '.locks' / 'pipeline.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise PipelineBusy('已有数据更新任务正在运行，请等待完成。')
    return handle


def read_status(root=ROOT):
    try:
        return json.loads((Path(root) / 'pipeline_status.json').read_text())
    except (OSError, ValueError):
        return {'running': False, 'history': []}


def write_status(status, root=ROOT):
    fd, temp = tempfile.mkstemp(prefix='.pipeline-status-', dir=root)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(status, stream, ensure_ascii=False, indent=2)
        os.replace(temp, Path(root) / 'pipeline_status.json')
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def starting_status(date, source, root=ROOT):
    status = {'history': read_status(root).get('history', []),
              'running': True, 'date': date, 'source': source, 'stage': 'starting',
              'started_at': now().strftime('%Y-%m-%d %H:%M:%S')}
    write_status(status, root)
    return status


def finish_status(status, error=None, root=ROOT):
    status.update(running=False, stage='failed' if error else 'done',
                  finished_at=now().strftime('%Y-%m-%d %H:%M:%S'), error=error or '')
    status['history'] = [{'date': status['date'], 'source': status['source'],
                          'status': 'fail' if error else 'success',
                          'time': status['started_at'], 'elapsed': status.get('elapsed', 0)}
                         ] + status.get('history', [])[:19]
    write_status(status, root)


def pipeline_status(root=ROOT):
    status = read_status(root)
    if status.get('running'):
        try:
            handle = acquire_lock(root)
        except PipelineBusy:
            return status
        try:
            # No job owns the lock: a restart interrupted the previous task.
            status.setdefault('source', 'upload')
            finish_status(status, '上次更新任务已中断，请重新更新。', root)
        finally:
            handle.close()
    return status


def submit_upload(date, frame, runner, root=ROOT):
    """Reserve before saving a file or starting a thread, across web workers."""
    handle = acquire_lock(root)
    temp = None
    status = None
    try:
        fd, temp = tempfile.mkstemp(prefix='.upload_temp_', suffix='.csv', dir=root)
        os.close(fd)
        frame.to_csv(temp, index=False)
        status = starting_status(date, 'upload', root)

        def run():
            try:
                runner(date, temp)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
                handle.close()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
    except Exception:
        if temp and os.path.exists(temp):
            os.unlink(temp)
        if status:
            finish_status(status, '无法启动上传任务，请重试。', root)
        handle.close()
        raise


def submit_today(root=ROOT):
    handle = acquire_lock(root)
    status = None
    try:
        date = now().strftime('%Y%m%d')
        status = starting_status(date, 'today_button', root)
        log_dir = Path(root) / 'logs'
        log_dir.mkdir(exist_ok=True)
        with (log_dir / 'today-update.log').open('a') as log:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), '--date', date,
                 '--lock-fd', str(handle.fileno())],
                cwd=Path(__file__).resolve().parent,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, pass_fds=(handle.fileno(),),
            )
        return date
    except Exception:
        if status:
            finish_status(status, '无法启动今日更新，请重试。', root)
        raise
    finally:
        # The detached child retains the same locked open file description.
        handle.close()


def register_today_update(app, admin_required, validate_csrf):
    @app.route('/admin/update-today', methods=['POST'])
    @admin_required
    def update_today():
        if not validate_csrf(request.form.get('csrf_token', '')):
            return jsonify(error='页面验证已失效，请刷新页面后重试。'), 403
        try:
            date = submit_today()
        except PipelineBusy as exc:
            return jsonify(error=str(exc)), 409
        except Exception:
            app.logger.exception('Unable to start today update')
            return jsonify(error='无法启动今日更新，请稍后重试。'), 500
        return jsonify(ok=True, date=date, message='已开始更新今日数据，可在下方查看进度。'), 202


def report_date(date, dates):
    if date in dates:
        return date
    if date.startswith('2026') and date[4:] in dates:
        return date[4:]
    raise RuntimeError('今日数据未写入数据库，已停止生成报告。')


def run_today(date, root=ROOT):
    status = read_status(root)
    start = time.monotonic()
    work = Path(root) / 'quant_web'

    def stage(name):
        status['stage'] = name
        write_status(status, root)

    def command(script, args=(), timeout=300, env=None):
        result = subprocess.run([sys.executable, str(work / script), *args],
                                cwd=work, env=env, capture_output=True, text=True,
                                timeout=timeout)
        print(result.stdout or '', flush=True)
        print(result.stderr or '', flush=True)
        return result.returncode == 0

    error = None
    try:
        stage('crawl')
        fetched = False
        for method, timeout in (('direct_ip', 90), ('chrome', 270)):
            env = dict(os.environ, CRAWL_METHOD=method, CRAWLER_DIRECT_IP_RETRIES='1',
                       CRAWLER_DIRECT_IP_TIMEOUT='60', CRAWLER_CHROME_RETRIES='1',
                       CRAWLER_SERVICE_TIMEOUT='180')
            try:
                fetched = command('daily_spider.py', ['--date', date], timeout, env)
            except subprocess.TimeoutExpired:
                print('Crawl timed out: ' + method, flush=True)
            if fetched:
                break
        if not fetched:
            raise RuntimeError('今日数据尚未发布或数据源连接失败，请稍后点击重试。')

        stage('refresh_market_cache')
        if not command('refresh_market_cache.py', ['--date', date]):
            raise RuntimeError('行情数据导入失败，请重试。')
        import db_service
        date_arg = report_date(date, db_service.get_market_dates())
        for script, name, label in (('batch_backtest.py', 'backtest', '日回测'),
                                    ('batch_weekly.py', 'weekly', '礼拜攻势')):
            stage(name)
            if not command(script, ['--date', date_arg]):
                raise RuntimeError(label + '生成失败，请重试。')
            status[name + '_ok'] = True

        stage('refresh_index_cache')
        import index_service
        for symbol in ('sh000905', 'sh000852'):
            rows = index_service.fetch_index_history_robust(symbol)
            if not rows or rows[-1]['date'] != date:
                raise RuntimeError('今日指数行情暂未更新，请稍后重试。')
            index_service.write_cache(symbol, rows)
        status['index_ok'] = True
    except Exception as exc:
        print('Today update failed: ' + repr(exc), flush=True)
        error = str(exc) if isinstance(exc, RuntimeError) else '更新任务异常或超时，请稍后重试。'
    finally:
        status['elapsed'] = int(time.monotonic() - start)
        finish_status(status, error, root)
    return error is None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    parser.add_argument('--lock-fd', type=int, required=True)
    args = parser.parse_args()
    # Keep the inherited lock alive until all pipeline writes finish.
    with os.fdopen(args.lock_fd, 'a'):
        raise SystemExit(0 if run_today(args.date) else 1)
