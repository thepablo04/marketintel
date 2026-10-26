"""Public FRED transport must preserve the same observations and calculations."""

import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import marketintel_data as data


class October2026(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 5, tzinfo=tz or timezone.utc)


class PublicFredTests(unittest.TestCase):
    def setUp(self):
        data._REMOTE_CACHE.clear()
        data._MACRO_LAST_GOOD.clear()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(data, 'datetime', October2026))

    def fail_primary_sources(self):
        for source in ('fetch_bls_cpi_snapshot', 'fetch_bea_core_pce_snapshot',
                       'fetch_michigan_sentiment_snapshot', 'fetch_ism_snapshot'):
            self.stack.enter_context(patch.object(data, source, side_effect=ValueError('fixture unavailable')))

    @staticmethod
    def csv_response(_requests, url, **kwargs):
        query = parse_qs(urlparse(url).query)
        series_id = query['id'][0]
        return (f'observation_date,{series_id}\n'
                '2025-09-01,100\n2026-08-01,105\n2026-09-01,110\n')

    def test_public_csv_sorts_and_rejects_invalid_or_future_dates(self):
        csv = ('\ufeffobservation_date,UNRATE\n'
               '2026-08-01,4.2\n2026-02-30,90\n2026-9-1,99\n'
               '2026-09-01,4.1\n2026-10-01,.\n2099-01-01,1\n')
        with patch.object(data, '_cached_text', return_value=csv):
            result = data._fetch_fred_public_observations(object(), 'UNRATE')
        self.assertEqual(result['observations'], [
            {'date': '2026-10-01', 'value': '.'},
            {'date': '2026-09-01', 'value': '4.1'},
            {'date': '2026-08-01', 'value': '4.2'},
        ])

    def test_public_csv_requires_exact_series_and_numeric_observations(self):
        for csv in ('<html>Temporarily unavailable</html>',
                    'observation_date,OTHER\n2026-09-01,4\n',
                    'observation_date,UNRATE\n2026-09-01,NaN\n',
                    'observation_date,UNRATE\n2026-09-01,inf\n'):
            with self.subTest(csv=csv), patch.object(data, '_cached_text', return_value=csv):
                with self.assertRaises(ValueError):
                    data._fetch_fred_public_observations(object(), 'UNRATE')

    def test_no_key_macro_uses_official_csv_and_existing_calculations(self):
        self.fail_primary_sources()
        with patch.object(data, '_cached_text', side_effect=self.csv_response) as public, \
             patch.object(data, '_cached_json_retry') as api:
            result = data.fetch_fred_snapshot(object(), '')
        api.assert_not_called()
        self.assertEqual(public.call_count, 9)
        self.assertEqual(result['series']['payrolls']['display_value'], 5)
        for name in ('gdp', 'cpi', 'core_pce'):
            item = result['series'][name]
            self.assertEqual((item['date'], item['display_value'], item['display_unit']),
                             ('2026-09-01', 10, 'percent_yoy'))
        self.assertEqual(result['series']['pmi']['status'], 'unavailable')
        self.assertFalse(result['configured'])  # No API key, despite public data.
        for call in public.call_args_list:
            url = urlparse(call.args[1])
            self.assertEqual((url.netloc, url.path),
                             ('fred.stlouisfed.org', '/graph/fredgraph.csv'))
            self.assertEqual(set(parse_qs(url.query)), {'id', 'cosd'})

    def test_configured_api_remains_preferred(self):
        self.fail_primary_sources()
        with patch.object(data, '_fetch_fred_public_observations') as public, \
             patch.object(data, '_cached_json_retry', return_value={
                 'observations': [{'date': '2026-10-05', 'value': '4'}]
             }) as api:
            result = data.fetch_fred_snapshot(object(), 'fixture-key')
        public.assert_not_called()
        self.assertEqual(api.call_count, 9)
        self.assertEqual(result['series']['fed_upper']['display_value'], 4)

    def test_no_key_public_failure_stays_unavailable(self):
        self.fail_primary_sources()
        with patch.object(data, '_cached_text', side_effect=TimeoutError('fixture')):
            result = data.fetch_fred_snapshot(object(), '')
        self.assertEqual(result['status'], 'error')
        self.assertTrue(all(item['display_value'] is None for item in result['series'].values()))
        self.assertTrue(any('TimeoutError' in error for error in result['errors']))

    def test_no_key_credit_and_curve_history_remains_chronological(self):
        with patch.object(data, '_cached_text', side_effect=self.csv_response):
            result = data.fetch_fred_sentiment(object(), '')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(set(result['series']), {'credit_spread', 'yield_curve'})
        for item in result['series'].values():
            self.assertEqual((item['date'], item['value']), ('2026-09-01', 110))
            self.assertEqual([row['date'] for row in item['history']],
                             ['2025-09-01', '2026-08-01', '2026-09-01'])


if __name__ == '__main__':
    unittest.main()
