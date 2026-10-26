"""Serverless persistence boundaries and verified browser settlement inputs."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from marketintel_pulse import PulseService, completed_closes, market_session
from marketintel_storage import LocalStore, MODEL_VERSION


NOW = datetime(2026, 7, 6, 15, 0, tzinfo=timezone.utc)


def daily_fixture():
    # Includes a holiday, weekend, invalid values, and an unfinished daily bar.
    return pd.DataFrame({('Close', 'SPY'): [float('inf'), -1, 101, 102, 103, 104, 105, 106]},
                        index=pd.to_datetime(['2026-06-29', '2026-06-30', '2026-07-01',
                                              '2026-07-02', '2026-07-03', '2026-07-04',
                                              '2026-07-06', '2026-07-07']))


def service(store=None):
    download = Mock(side_effect=lambda *args, **kw: daily_fixture() if kw['interval'] == '1d' else pd.DataFrame())
    pulse = PulseService(download, lambda: {'series': {}, 'errors': []},
                         lambda history, fred, date, errors: {'last_history_date': date}, store)
    return pulse, download


class VercelRuntimeTests(unittest.TestCase):
    def test_browser_evaluation_contract_reuses_the_daily_download(self):
        pulse, download = service()
        result = pulse.snapshot(now=NOW)
        evaluation = result['evaluation']
        self.assertEqual(evaluation['storage'], 'browser')
        self.assertEqual(evaluation['model'], MODEL_VERSION)
        self.assertEqual(evaluation['completed_closes'], {'2026-07-01': 101, '2026-07-02': 102})
        self.assertNotIn('error', evaluation)
        self.assertNotIn('summary', evaluation)
        self.assertEqual(download.call_count, 2)

    def test_local_summary_and_method_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(directory)
            pulse, _ = service(store)
            evaluation = pulse.snapshot(now=NOW)['evaluation']
            journal = store.signal_history()
            self.assertEqual(evaluation['storage'], 'local')
            self.assertEqual(evaluation['summary'], journal['summary'])
            self.assertEqual(evaluation['method'], journal['method'])
            browser, _ = service()
            self.assertEqual(browser.snapshot(now=NOW)['evaluation']['method'], journal['method'])

    def test_local_settlement_receives_only_verified_completed_sessions(self):
        store = Mock()
        store.signal_history.return_value = {'summary': {'total': 0}, 'method': 'Fixture method'}
        pulse, _ = service(store)
        pulse.snapshot(now=NOW)
        store.settle_signals.assert_called_once_with({'2026-07-01': 101, '2026-07-02': 102})
        store.record_signal.assert_called_once()

    def test_no_closes_when_the_calendar_is_unverified(self):
        with patch('marketintel_pulse.calendar_for', side_effect=RuntimeError('calendar unavailable')):
            pulse, _ = service()
            result = pulse.snapshot(now=NOW)
        self.assertFalse(result['session']['calendar_verified'])
        self.assertEqual(result['evaluation']['completed_closes'], {})

    def test_each_session_must_be_verified_and_closed(self):
        session = market_session(NOW)
        calendar = Mock()
        calendar.is_session.return_value = True
        calendar.session_close.return_value = pd.Timestamp(NOW) + pd.Timedelta(minutes=1)
        with patch('marketintel_pulse.calendar_for', return_value=calendar):
            self.assertEqual(completed_closes({'2026-07-02': 100}, session, NOW), {})
        with patch('marketintel_pulse.calendar_for', side_effect=RuntimeError):
            self.assertEqual(completed_closes({'2026-07-02': 100}, session, NOW), {})

    def test_completed_half_day_is_allowed_but_thanksgiving_is_not(self):
        now = datetime(2026, 11, 28, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(completed_closes({'2026-11-26': 100, '2026-11-27': 101},
                                         market_session(now), now), {'2026-11-27': 101})

    def test_cloud_initialization_writes_only_disposable_cache_and_denies_local_routes(self):
        # A fresh interpreter exercises import-time environment selection. It
        # rejects writes to HOME rather than relying on chmod under root.
        script = r'''
import json, os, pathlib, sys, tempfile
protected_home = pathlib.Path.home().resolve()
attempted_home_writes = []
def guard(event, args):
    target = None
    if event == 'open' and isinstance(args[0], (str, bytes)):
        if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            target = args[0]
    elif event in ('os.mkdir', 'sqlite3.connect') and isinstance(args[0], (str, bytes)):
        target = args[0]
    if target and pathlib.Path(os.fsdecode(target)).resolve().is_relative_to(protected_home):
        attempted_home_writes.append(str(target))
        raise PermissionError('Deployment HOME is read-only')
sys.addaudithook(guard)
import servidor
assert servidor.IS_VERCEL
assert servidor.local_store is None and servidor.pulse_service.store is None
cache = servidor.yf.cache
cache.get_tz_cache().store('TEST-CACHE', 'America/New_York')
assert cache.get_tz_cache().lookup('TEST-CACHE') == 'America/New_York'
cache.get_cookie_cache().store('test-runtime', {'fixture': True})
assert cache.get_cookie_cache().lookup('test-runtime')['cookie'] == {'fixture': True}
cache_directory = pathlib.Path(cache._TzDBManager.get_location()).resolve()
assert cache_directory == pathlib.Path(tempfile.gettempdir()) / 'marketintel' / 'yfinance'
client = servidor.app.test_client()
assert client.get('/health').status_code == 200
assert client.get('/').status_code == 200
for host, address in [('localhost', '127.0.0.1'), ('127.0.0.1', '127.0.0.1'), ('marketintel.vercel.app', '10.0.0.1')]:
    for path, method in [('/local-state', 'GET'), ('/local-backups', 'GET'), ('/local-backups', 'POST'), ('/local-backups/1', 'GET'), ('/signal-history', 'GET')]:
        response = client.open(path, method=method, headers={'Host': host, 'X-MarketIntel-Token': servidor.LOCAL_TOKEN}, environ_overrides={'REMOTE_ADDR': address})
        assert response.status_code == 403, (path, host, response.status_code)
        assert 'token' not in response.get_json()
assert not attempted_home_writes, attempted_home_writes
print(json.dumps({'stateless': True, 'local_routes_blocked': True, 'home_writes': 0}))
'''
        with tempfile.TemporaryDirectory() as directory:
            forbidden_data_directory = str(Path.home() / '.marketintel-test-forbidden-data')
            environment = dict(os.environ, VERCEL='1',
                               MARKETINTEL_DATA_DIR=forbidden_data_directory, TMPDIR=directory,
                               PYTHONDONTWRITEBYTECODE='1')
            completed = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                                       env=environment, text=True, capture_output=True, timeout=45)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(completed.stdout)['home_writes'], 0)


if __name__ == '__main__':
    unittest.main()
