import functools
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
from flask import Flask, jsonify, session

sys.path.insert(0, str(Path(__file__).resolve().parent))
import today_update as jobs


class TodayUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.status = jobs.starting_status('20261118', 'today_button', self.root)

    def run_job(self, results=None, index_date='20261118', dates=None):
        completed = SimpleNamespace(returncode=0, stdout='', stderr='')
        index = SimpleNamespace(
            fetch_index_history_robust=Mock(return_value=[{'date': index_date}]),
            write_cache=Mock())
        database = SimpleNamespace(get_market_dates=lambda: dates or ['1117', '1118'])
        with patch.dict(sys.modules, {'db_service': database, 'index_service': index}), \
             patch.object(jobs.subprocess, 'run', side_effect=results, return_value=completed) as run:
            ok = jobs.run_today('20261118', self.root)
        return ok, run, index

    def test_success_runs_reports_and_indexes_after_fresh_data(self):
        ok, run, index = self.run_job()
        self.assertTrue(ok)
        self.assertEqual([Path(call.args[0][1]).name for call in run.call_args_list],
                         ['daily_spider.py', 'refresh_market_cache.py', 'batch_backtest.py', 'batch_weekly.py'])
        self.assertEqual(run.call_args_list[0].args[0][-2:], ['--date', '20261118'])
        self.assertEqual(run.call_args_list[2].args[0][-2:], ['--date', '1118'])
        self.assertEqual(index.write_cache.call_count, 2)
        status = jobs.read_status(self.root)
        self.assertFalse(status['running'])
        self.assertEqual(status['stage'], 'done')
        self.assertEqual(status['history'][0]['status'], 'success')

    def test_failed_crawl_never_reuses_existing_data_for_reports(self):
        failed = SimpleNamespace(returncode=1, stdout='not published', stderr='')
        ok, run, index = self.run_job([failed, failed])
        self.assertFalse(ok)
        self.assertEqual(run.call_count, 2)
        index.fetch_index_history_robust.assert_not_called()
        self.assertIn('尚未发布', jobs.read_status(self.root)['error'])

    def test_direct_timeout_falls_back_and_full_dates_are_preserved(self):
        done = SimpleNamespace(returncode=0, stdout='', stderr='')
        ok, run, _ = self.run_job([subprocess.TimeoutExpired('crawl', 90), done, done, done, done],
                                  dates=['20261117', '20261118'])
        self.assertTrue(ok)
        self.assertEqual(run.call_args_list[1].kwargs['env']['CRAWL_METHOD'], 'chrome')
        self.assertEqual(run.call_args_list[3].args[0][-1], '20261118')

    def test_cache_or_report_failure_stops_later_jobs(self):
        done = SimpleNamespace(returncode=0, stdout='', stderr='')
        failed = SimpleNamespace(returncode=1, stdout='', stderr='broken')
        for results, count in (([done, failed], 2), ([done, done, failed], 3)):
            with self.subTest(count=count):
                jobs.starting_status('20261118', 'today_button', self.root)
                ok, run, index = self.run_job(results)
                self.assertFalse(ok)
                self.assertEqual(run.call_count, count)
                index.write_cache.assert_not_called()
                self.assertEqual(jobs.read_status(self.root)['stage'], 'failed')

    def test_stale_index_is_failure_and_does_not_overwrite_cache(self):
        ok, _, index = self.run_job(index_date='20261117')
        self.assertFalse(ok)
        index.write_cache.assert_not_called()
        self.assertIn('指数行情', jobs.read_status(self.root)['error'])

    def test_lock_excludes_other_processes_and_recovers_after_release(self):
        with jobs.acquire_lock(self.root):
            with self.assertRaises(jobs.PipelineBusy):
                jobs.acquire_lock(self.root)
            result = subprocess.run([sys.executable, '-c',
                'import fcntl,sys; f=open(sys.argv[1],"a+"); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)',
                str(self.root / '.locks/pipeline.lock')], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(jobs.pipeline_status(self.root)['running'])
        status = jobs.pipeline_status(self.root)
        self.assertFalse(status['running'])
        self.assertIn('已中断', status['error'])

    def test_upload_reserves_lock_before_thread_and_releases_on_completion(self):
        runner = Mock()
        with patch.object(jobs.threading, 'Thread') as thread:
            jobs.submit_upload('20261118', pd.DataFrame({'a': [1]}), runner, self.root)
            with self.assertRaises(jobs.PipelineBusy):
                jobs.submit_today(self.root)
            target = thread.call_args.kwargs['target']
            target()
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0], '20261118')
        self.assertFalse(Path(runner.call_args.args[1]).exists())
        with jobs.acquire_lock(self.root):
            pass

    def test_spawn_failure_is_visible_and_releases_lock(self):
        with patch.object(jobs.subprocess, 'Popen', side_effect=OSError('cannot spawn')):
            with self.assertRaises(OSError):
                jobs.submit_today(self.root)
        self.assertEqual(jobs.read_status(self.root)['stage'], 'failed')
        with jobs.acquire_lock(self.root):
            pass


class TodayRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'test-only'

        def admin_required(function):
            @functools.wraps(function)
            def wrapped():
                if session.get('role') != 'admin':
                    return jsonify(error='forbidden'), 403
                return function()
            return wrapped

        jobs.register_today_update(self.app, admin_required, lambda token: token == 'form-token')
        self.client = self.app.test_client()

    def login(self, role='admin'):
        with self.client.session_transaction() as state:
            state['role'] = role

    def test_no_job_without_admin_and_csrf(self):
        with patch.object(jobs, 'submit_today') as submit:
            self.assertEqual(self.client.post('/admin/update-today').status_code, 403)
            self.login('user')
            self.assertEqual(self.client.post('/admin/update-today', data={'csrf_token': 'form-token'}).status_code, 403)
            self.login()
            self.assertEqual(self.client.post('/admin/update-today').status_code, 403)
            submit.assert_not_called()

    def test_route_ignores_supplied_date_and_returns_background_acceptance(self):
        self.login()
        with patch.object(jobs, 'submit_today', return_value='20261118') as submit:
            response = self.client.post('/admin/update-today', data={'csrf_token': 'form-token', 'date': '20200101'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()['date'], '20261118')
        submit.assert_called_once_with()

    def test_busy_returns_conflict(self):
        self.login()
        with patch.object(jobs, 'submit_today', side_effect=jobs.PipelineBusy('已有任务')):
            self.assertEqual(self.client.post('/admin/update-today', data={'csrf_token': 'form-token'}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
