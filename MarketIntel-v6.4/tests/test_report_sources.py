"""Breadth must not mix premarket, regular close, or future observations."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from unittest.mock import Mock

import marketintel_report_sources as sources

UTC = timezone.utc


class ReportSourceTests(unittest.TestCase):
    def setUp(self):
        self.session = {'open_at': '2026-11-16T14:30:00+00:00',
                        'close_at': '2026-11-16T21:00:00+00:00'}
        self.close_cutoff = datetime(2026, 11, 16, 22, tzinfo=UTC)
        self.pre_cutoff = datetime(2026, 11, 16, 14, 29, tzinfo=UTC)
        self.chart = {'meta': {'symbol': 'NVDA', 'currency': 'USD', 'instrumentType': 'EQUITY',
                               'previousClose': 100, 'regularMarketPrice': 102,
                               'regularMarketTime': datetime(2026, 11, 16, 21, tzinfo=UTC).timestamp(),
                               'currentTradingPeriod': {'regular': {'end': datetime(2026, 11, 16, 21, tzinfo=UTC).timestamp()}}},
                      'timestamp': [datetime(2026, 11, 16, 14, 20, tzinfo=UTC).timestamp(),
                                    datetime(2026, 11, 16, 14, 25, tzinfo=UTC).timestamp()],
                      'indicators': {'quote': [{'close': [99, 150]}]}}

    def test_close_uses_regular_quote_and_rejects_intraday_quote(self):
        observed = sources._observation(self.chart, 'closing', self.session, self.close_cutoff)
        self.assertEqual(observed[:2], (102, 100))
        self.chart['meta']['regularMarketTime'] -= 15 * 60
        self.assertIsNone(sources._observation(self.chart, 'closing', self.session, self.close_cutoff))

    def test_premarket_uses_last_completed_bar_without_future_leakage(self):
        observed = sources._observation(self.chart, 'opening', self.session, self.pre_cutoff)
        self.assertEqual(observed, (99, 100, datetime(2026, 11, 16, 14, 25, tzinfo=UTC)))

    def test_old_premarket_print_is_missing(self):
        self.chart['timestamp'] = [datetime(2026, 11, 16, 14, tzinfo=UTC).timestamp()]
        self.assertIsNone(sources._observation(self.chart, 'opening', self.session, self.pre_cutoff))

    def test_baseline_is_never_taken_from_first_day_of_chart(self):
        del self.chart['meta']['previousClose']
        self.chart['meta']['chartPreviousClose'] = 90
        self.assertIsNone(sources._observation(self.chart, 'closing', self.session, self.close_cutoff))

    def test_baseline_for_a_different_session_is_rejected(self):
        self.chart['meta']['currentTradingPeriod']['regular']['end'] -= 24 * 3600
        self.assertIsNone(sources._observation(self.chart, 'closing', self.session, self.close_cutoff))

    def test_nonfinite_or_wrong_currency_is_rejected(self):
        self.chart['meta']['regularMarketPrice'] = float('nan')
        self.assertIsNone(sources._observation(self.chart, 'closing', self.session, self.close_cutoff))
        self.chart['meta']['regularMarketPrice'] = 102
        self.chart['meta']['currency'] = 'EUR'
        self.assertIsNone(sources._observation(self.chart, 'closing', self.session, self.close_cutoff))

    def test_partial_coverage_counts_only_observed_members(self):
        def members(http, index):
            return {'symbols': ['NVDA', 'MISSING'], 'source': 'fixture', 'source_url': 'https://example.com/members'}

        with patch.object(sources, '_members', side_effect=members), \
                patch.object(sources, '_batch', return_value={'NVDA': deepcopy(self.chart)}):
            rows = sources.fetch_report_breadth(object(), 'closing', self.session, self.close_cutoff)
        for row in rows:
            self.assertEqual((row['total'], row['valid'], row['up'], row['down'], row['missing']), (2, 1, 1, 0, 1))
            self.assertEqual(row['status'], 'partial')
            self.assertEqual(row['coverage_pct'], 50)
            self.assertEqual(row['as_of'], '2026-11-16T21:00:00+00:00')


class WatchlistCalendarTests(unittest.TestCase):
    def setUp(self):
        sources._CACHE.clear()
        self.http = Mock()
        self.cutoff = datetime(2026, 11, 16, 22, tzinfo=UTC)

    def fetch(self, rows, tickers=None):
        self.http.get.return_value.json.return_value = rows
        return sources.fetch_watchlist_calendar(self.http, tickers or ['NVDA'], self.cutoff, 'fixture-key')

    def test_missing_credentials_do_not_request_or_imply_absence(self):
        self.assertEqual(sources.fetch_watchlist_calendar(self.http, ['NVDA'], self.cutoff), [])
        self.http.get.assert_not_called()

    def test_date_only_and_last_updated_never_confirm_publication(self):
        rows = self.fetch([{'symbol': 'NVDA', 'date': '2026-11-16', 'epsActual': 0,
                            'epsEstimated': 1, 'lastUpdated': '2026-11-16T21:30:00Z'}])
        self.assertEqual(rows[0]['status'], 'pending')
        self.assertIsNone(rows[0]['published_at'])
        self.assertIn('sin hora verificada', rows[0]['summary'])
        self.assertIsNone(rows[0]['actual'])
        self.assertIsNone(rows[0]['consensus'])

    def test_timezone_publication_before_cutoff_with_realized_value(self):
        rows = self.fetch([{'symbol': 'NVDA', 'date': '2026-11-16', 'epsActual': -0.2,
                            'publishedAt': '2026-11-16T16:30:00-05:00'}])
        self.assertEqual(rows[0]['status'], 'published')
        self.assertEqual(rows[0]['published_at'], '2026-11-16T21:30:00+00:00')
        self.assertIsNone(rows[0]['actual'])

    def test_release_after_17_ny_remains_pending(self):
        rows = self.fetch([{'symbol': 'NVDA', 'date': '2026-11-16T17:30:00-05:00', 'epsActual': 1}])
        self.assertEqual(rows[0]['status'], 'pending')
        self.assertIsNone(rows[0]['published_at'])

    def test_naive_publication_and_wrong_new_york_day_are_not_published(self):
        rows = self.fetch([{'symbol': 'NVDA', 'date': '2026-11-16', 'epsActual': 1,
                            'publishedAt': '2026-11-16T16:30:00'},
                           {'symbol': 'AAPL', 'date': '2026-11-17T04:30:00-05:00', 'epsActual': 1}],
                          ['NVDA', 'AAPL'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'pending')

    def test_all_watchlist_members_are_checked_and_duplicates_do_not_downgrade(self):
        tickers = ['A' + chr(65 + i) for i in range(20)]
        rows = [{'symbol': ticker, 'date': '2026-11-16'} for ticker in tickers]
        rows += [{'symbol': tickers[-1], 'date': '2026-11-16', 'epsActual': 1,
                  'publishedAt': '2026-11-16T21:30:00Z'},
                 {'symbol': tickers[-1], 'date': '2026-11-16'}]
        result = self.fetch(rows, tickers)
        self.assertEqual(len(result), 20)
        self.assertEqual(result[-1]['status'], 'published')
        params = self.http.get.call_args.kwargs['params']
        self.assertEqual((params['from'], params['to']), ('2026-11-16', '2026-11-16'))

    def test_provider_failure_is_unverified_empty_result(self):
        self.http.get.side_effect = RuntimeError('fixture failure')
        self.assertEqual(sources.fetch_watchlist_calendar(self.http, ['NVDA'], self.cutoff, 'fixture-key'), [])


if __name__ == '__main__':
    unittest.main()
