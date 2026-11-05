"""Macro examples must retain measurement units, periods and source uncertainty."""
import copy
from contextlib import ExitStack
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import marketintel_data as data


class November2026(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 5, 15, tzinfo=tz or timezone.utc)


def item(date='2026-09-01', value=120, unit='change_thousands', **extra):
    return dict(id='PAYEMS', date=date, display_value=value, display_unit=unit,
                status='ok', fetched_at='2026-11-05T15:00:00+00:00', history=[], **extra)


class MacroContextTests(unittest.TestCase):
    def setUp(self):
        data._REMOTE_CACHE.clear()
        data._MACRO_LAST_GOOD.clear()

    def test_distinct_monthly_yearly_and_annualized_measurements(self):
        levels = {'2025-07-01': 100, '2026-04-01': 102, '2026-07-01': 103}
        value, unit = data._macro_measure('gdp', 103, '2026-07-01', levels, 'billions')
        self.assertAlmostEqual(value, 3)
        self.assertEqual(unit, 'percent_yoy')
        metrics = data._macro_metrics('gdp', '2026-07-01', levels)
        self.assertEqual(metrics['yoy'], 3)
        self.assertEqual(metrics['qoq_annualized'], round(((103 / 102) ** 4 - 1) * 100, 2))
        self.assertNotIn('mom', metrics)

        monthly = {'2025-09-01': 100, '2026-08-01': 110, '2026-09-01': 112}
        self.assertEqual(data._macro_measure('payrolls', 112, '2026-09-01', monthly, 'thousands'),
                         (2, 'change_thousands'))
        change, unit = data._macro_measure('retail_sales', 112, '2026-09-01', monthly, 'millions')
        self.assertEqual(unit, 'percent_mom')
        self.assertAlmostEqual(change, (112 / 110 - 1) * 100)
        self.assertIn('mom', data._macro_metrics('pce', '2026-09-01', monthly))
        self.assertNotIn('mom', data._macro_metrics('cpi', '2026-09-01', monthly))
        self.assertNotIn('mom', data._macro_metrics('core_cpi', '2026-09-01', monthly))

    def test_missing_reference_period_is_not_approximated(self):
        levels = {'2026-07-01': 100, '2026-09-01': 112}
        self.assertIsNone(data._macro_measure('payrolls', 112, '2026-09-01', levels, 'thousands')[0])
        self.assertIsNone(data._macro_measure('retail_sales', 112, '2026-09-01', levels, 'millions')[0])
        self.assertIsNone(data._macro_measure('wages', 112, '2026-09-01', levels, 'dollars_per_hour')[0])
        current = item()
        current['history'] = [item(date='2026-07-01', value=50)]
        data._enrich_macro_item('payrolls', current)
        self.assertIsNone(current['previous'])

    def test_release_and_consensus_are_not_inferred_from_observation_date(self):
        current = item()
        current['history'] = [item(date='2026-08-01', value=100)]
        data._enrich_macro_item('payrolls', current)
        self.assertEqual(current['period'], '2026-09-01')
        self.assertEqual(current['frequency'], 'monthly')
        self.assertIsNone(current['published_at'])
        self.assertEqual(current['publication_date_status'], 'unavailable')
        self.assertIsNone(current['consensus'])
        self.assertIsNone(current['market_reaction'])
        self.assertEqual(current['previous']['display_value'], 100)
        self.assertEqual(current['release_url'], 'https://www.bls.gov/news.release/empsit.htm')

    def test_weekly_comparison_requires_exact_previous_week(self):
        current = item(date='2026-10-31', value=220000, unit='persons')
        current['history'] = [item(date='2026-10-17', value=200000, unit='persons')]
        data._enrich_macro_item('initial_claims', current)
        self.assertEqual(current['frequency'], 'weekly')
        self.assertIsNone(current['previous'])
        current['history'].append(item(date='2026-10-24', value=210000, unit='persons'))
        data._enrich_macro_item('initial_claims', current)
        self.assertEqual(current['previous']['display_value'], 210000)

    def test_invalid_stale_and_old_values_cannot_be_used_for_context(self):
        for overrides in ({'date': None}, {'date': 'not-a-date'}, {'display_value': None},
                          {'display_value': float('inf')}, {'status': 'stale'},
                          {'status': 'unavailable'}, {'period_warning': 'old period'}):
            with self.subTest(overrides=overrides):
                current = item()
                current.update(overrides)
                data._enrich_macro_item('payrolls', current)
                self.assertFalse(current['context_usable'])

    def test_observed_revisions_keep_original_values_without_repeating(self):
        baseline = item(value=120)
        baseline['history'] = [item(date='2026-08-01', value=100)]
        data._enrich_macro_item('payrolls', baseline)
        changed = item(value=110)
        changed['history'] = [item(date='2026-08-01', value=90)]
        data._enrich_macro_item('payrolls', changed, baseline)
        self.assertEqual(changed['revision_basis'], 'observed_snapshots')
        self.assertEqual([(row['date'], row['previous_value'], row['value']) for row in changed['revisions']],
                         [('2026-08-01', 100, 90), ('2026-09-01', 120, 110)])
        self.assertIn('no equivale a la revisión oficial', changed['revision_note'])
        repeated = copy.deepcopy(changed)
        data._enrich_macro_item('payrolls', repeated, changed)
        self.assertEqual(repeated['revisions'], changed['revisions'])
        different_source = item(value=90)
        different_source['id'] = 'another-series'
        data._enrich_macro_item('payrolls', different_source, changed)
        self.assertEqual(different_source['revision_basis'], 'unavailable')
        self.assertEqual(different_source['revisions'], [])

    def test_snapshot_failure_and_period_regression_retain_marked_old_value(self):
        records = {'observations': [{'date': '2026-09-01', 'value': '1000'},
                                    {'date': '2026-08-01', 'value': '900'},
                                    {'date': '2026-07-01', 'value': '800'}]}
        with ExitStack() as stack:
            stack.enter_context(patch.object(data, 'datetime', November2026))
            stack.enter_context(patch.object(data, 'FRED_SERIES', {'payrolls': data.FRED_SERIES['payrolls']}))
            fetch = stack.enter_context(patch.object(data, '_cached_json_retry', return_value=records))
            initial = data.fetch_fred_snapshot(object(), 'fixture-key')['series']['payrolls']
            self.assertTrue(initial['context_usable'])
            fetch.side_effect = TimeoutError('fixture')
            failed = data.fetch_fred_snapshot(object(), 'fixture-key')['series']['payrolls']
            self.assertEqual((failed['date'], failed['display_value'], failed['status']),
                             ('2026-09-01', 100, 'stale'))
            self.assertFalse(failed['context_usable'])
            fetch.side_effect = None
            fetch.return_value = {'observations': records['observations'][1:]}
            regressed = data.fetch_fred_snapshot(object(), 'fixture-key')['series']['payrolls']
            self.assertEqual(regressed['date'], '2026-09-01')
            self.assertFalse(regressed['context_usable'])

    def test_services_report_must_verify_sector_month_and_year(self):
        good = '<h1>October 2026 ISM Services PMI Report</h1><p>The Services PMI registered 53.2 percent</p>'
        with patch.object(data, 'datetime', November2026), patch.object(data, '_cached_text', return_value=good):
            result = data.fetch_ism_snapshot(object(), services=True)
        self.assertEqual((result['date'], result['display_value'], result['id']),
                         ('2026-10-01', 53.2, 'ISM-SERVICES'))
        for wrong in (good.replace('2026', '2025'), good.replace('Services', 'Manufacturing')):
            with patch.object(data, 'datetime', November2026), patch.object(data, '_cached_text', return_value=wrong):
                with self.assertRaises(ValueError):
                    data.fetch_ism_snapshot(object(), services=True)


if __name__ == '__main__':
    unittest.main()
