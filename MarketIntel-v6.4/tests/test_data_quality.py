import unittest
import time
from unittest.mock import patch
import marketintel_data
from datetime import datetime, timezone

from marketintel_data import (
    build_cross_source_checks,
    build_identity_checks,
    calculate_operating_expense_runway,
    fetch_fred_snapshot,
    fetch_fred_sentiment,
    fetch_ism_snapshot,
    fetch_market_news,
    normalize_debt_to_equity,
    normalize_dividend_yield,
)


class FinancialDataTests(unittest.TestCase):
    def setUp(self):
        marketintel_data._REMOTE_CACHE.clear()
        marketintel_data._MACRO_LAST_GOOD.clear()

    def test_dividend_yield_accepts_decimal_and_percent(self):
        self.assertEqual(normalize_dividend_yield(0.0167), 1.67)
        self.assertEqual(normalize_dividend_yield(1.67), 1.67)

    def test_debt_to_equity_is_displayed_as_ratio(self):
        self.assertEqual(normalize_debt_to_equity(388.9), 3.889)
        self.assertEqual(normalize_debt_to_equity(1.25), 1.25)

    def test_original_runway_formula_is_preserved(self):
        monthly, months = calculate_operating_expense_runway(
            12_000_000, 24_000_000
        )
        self.assertEqual(monthly, 2_000_000)
        self.assertEqual(months, 6.0)

    def test_financial_identities(self):
        checks = build_identity_checks({
            'price': 100,
            'shares_outstanding': 10,
            'market_cap': 1_000,
            'eps': 5,
            'pe': 20,
            'revenue_ttm': 200,
            'revenue_ttm_calculated': 200,
            'revenue_quarters_count': 4,
            'net_income_ttm': 40,
            'profit_margin': 20,
        })
        self.assertTrue(all(check['status'] == 'pass' for check in checks))

    def test_cross_source_review_is_explicit(self):
        checks = build_cross_source_checks(
            {'revenue_ttm': 100},
            {'revenue_ttm': 130},
            {},
        )
        self.assertEqual(checks[0]['status'], 'review')
        self.assertEqual(checks[0]['id'], 'fmp_revenue')

    def test_fred_series_are_loaded_in_parallel(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'observations': [
                        {'date': marketintel_data._shift_month(datetime.now(timezone.utc).date().isoformat(), -index), 'value': str(120 - index)}
                        for index in range(13)
                    ]
                }

        class SlowRequests:
            def __init__(self):
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                time.sleep(0.05)
                return Response()

        requests_module = SlowRequests()
        started = time.perf_counter()
        result = fetch_fred_snapshot(requests_module, 'test-key')
        elapsed = time.perf_counter() - started

        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['series']), 10)
        # This fixture deliberately supplies no ISM report: partial is correct.
        self.assertLessEqual(requests_module.calls, 16)
        self.assertTrue(result['series']['cpi']['history'])
        self.assertLess(elapsed, 0.30)

    def test_fred_skips_empty_latest_observation(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'observations': [
                        {'date': '2026-09-01', 'value': '.'},
                        {'date': '2026-08-01', 'value': '4.25'},
                    ]
                }

        class Requests:
            def get(self, *args, **kwargs):
                return Response()

        result = fetch_fred_snapshot(Requests(), 'test-key-empty-latest')
        self.assertEqual(result['series']['fed_upper']['value'], 4.25)
        self.assertEqual(result['series']['fed_upper']['date'], '2026-08-01')

    def test_cpi_prefers_bls_release_shape(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                data = [{'year': '2026', 'period': 'M08', 'value': '334.980'}]
                data.extend({'year': '2026', 'period': f'M{month:02d}', 'value': str(334.0 - month)} for month in range(7, 0, -1))
                data.extend({'year': '2025', 'period': f'M{month:02d}', 'value': '323.980' if month == 8 else str(323.0 - month / 10)} for month in range(12, 7, -1))
                return {
                    'status': 'REQUEST_SUCCEEDED',
                    'Results': {'series': [{'data': data}]},
                }

        class Requests:
            def get(self, *args, **kwargs):
                return Response()

        result = fetch_fred_snapshot(Requests(), 'test-key-bls')
        self.assertEqual(result['series']['cpi']['source'], 'BLS')
        self.assertEqual(result['series']['cpi']['display_value'], 3.4)

    def test_ism_official_report_is_parsed(self):
        class Response:
            now = datetime.now(timezone.utc)
            prior = marketintel_data._shift_month(now.date().isoformat(), -1)
            month = datetime.fromisoformat(prior).strftime('%B %Y')
            text = '<h1>Manufacturing PMI® at 54.6%</h1><h1>'+month+' ISM® Manufacturing PMI® Report</h1>'

            def raise_for_status(self):
                return None

        class Requests:
            def get(self, *args, **kwargs):
                return Response()

        result = fetch_ism_snapshot(Requests())
        self.assertEqual(result['source'], 'ISM')
        self.assertEqual(result['display_value'], 54.6)

    def test_market_news_are_normalized(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {'news': [{
                    'uuid': 'news-1',
                    'title': 'Market update',
                    'publisher': 'Example',
                    'link': 'https://example.com/market',
                    'providerPublishTime': 1_700_000_000,
                    'relatedTickers': ['SPY'],
                }]}

        class Requests:
            def get(self, *args, **kwargs):
                return Response()

        result = fetch_market_news(Requests())
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['articles'][0]['title'], 'Market update')
        self.assertEqual(result['articles'][0]['related_tickers'], ['SPY'])

    def test_fred_sentiment_loads_credit_and_curve(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'observations': [
                        {'date': f'2026-{month:02d}-01', 'value': str(month / 10)}
                        for month in range(12, 0, -1)
                    ]
                }

        class Requests:
            def __init__(self):
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                return Response()

        result = fetch_fred_sentiment(Requests(), 'test-key')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(set(result['series']), {'credit_spread', 'yield_curve'})
        self.assertTrue(result['series']['credit_spread']['history'])

    def test_market_news_uses_rss_fallback_when_yahoo_is_empty(self):
        class Response:
            text = (
                '<rss><channel><item>'
                '<title>Fallback market update</title>'
                '<link>https://example.com/fallback</link>'
                '<pubDate>Tue, 01 Jan 2030 00:00:00 GMT</pubDate>'
                '<source>Example News</source>'
                '</item></channel></rss>'
            )

            def raise_for_status(self):
                return None

            def json(self):
                return {'news': []}

        class Requests:
            def get(self, url, *args, **kwargs):
                return Response()

        result = fetch_market_news(Requests(), query='stocks', count=1)
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(result.get('fallback'))
        self.assertEqual(result['articles'][0]['publisher'], 'Example News')

    def test_monthly_yoy_uses_exact_period_when_a_month_is_missing(self):
        observations = [{'date': '2026-08-01', 'value': '110'},
                        {'date': '2025-08-01', 'value': '100'},
                        {'date': '2025-07-01', 'value': '70'}]
        with patch.object(marketintel_data, '_cached_json_retry', return_value={'observations': observations}), patch.object(marketintel_data, 'fetch_bls_cpi_snapshot', side_effect=ValueError), patch.object(marketintel_data, 'fetch_ism_snapshot', side_effect=ValueError):
            result = fetch_fred_snapshot(object(), 'fixture-key')
        self.assertEqual(result['series']['cpi']['display_value'], 10)
        self.assertEqual(result['series']['core_pce']['display_value'], 10)
        self.assertIsNone(result['series']['payrolls']['display_value'])
        self.assertIn('BLS', result['series']['cpi']['warning'])

    def test_real_gdp_uses_real_levels_and_the_matching_quarter_last_year(self):
        observations = {'observations': [
            {'date': '2026-04-01', 'value': '24269.613'},
            {'date': '2025-04-01', 'value': '23770.976'},
        ]}
        with patch.object(marketintel_data, '_cached_json_retry', return_value=observations), \
             patch.object(marketintel_data, 'fetch_bls_cpi_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_ism_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_bea_core_pce_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_michigan_sentiment_snapshot', side_effect=ValueError):
            result = fetch_fred_snapshot(object(), 'fixture-key')
        item = result['series']['gdp']
        self.assertEqual((item['id'], item['display_value'], item['display_unit']),
                         ('GDPC1', 2.1, 'percent_yoy'))

    def test_last_published_second_quarter_gdp_is_not_discarded_in_early_october(self):
        class OnOctoberFifth(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 5, tzinfo=tz or timezone.utc)

        class InDecember(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 12, 1, tzinfo=tz or timezone.utc)

        observations = {'observations': [
            {'date': '2026-04-01', 'value': '24269.613'},
            {'date': '2025-04-01', 'value': '23770.976'},
        ]}
        with patch.object(marketintel_data, '_cached_json_retry', return_value=observations), \
             patch.object(marketintel_data, 'fetch_bls_cpi_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_ism_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_bea_core_pce_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_michigan_sentiment_snapshot', side_effect=ValueError):
            with patch.object(marketintel_data, 'datetime', OnOctoberFifth):
                current = fetch_fred_snapshot(object(), 'fixture-key')['series']['gdp']
            with patch.object(marketintel_data, 'datetime', InDecember):
                old = fetch_fred_snapshot(object(), 'fixture-key')['series']['gdp']
        self.assertEqual(current['status'], 'ok')
        self.assertNotIn('period_warning', current)
        self.assertIn('period_warning', old)

    def test_newer_michigan_period_wins_over_stale_official_page(self):
        official = {'source': 'U. Michigan', 'date': '2026-08-01', 'display_value': 51.7}
        observations = {'observations': [{'date': '2026-09-01', 'value': '47.8'}]}
        with patch.object(marketintel_data, '_cached_json_retry', return_value=observations), \
             patch.object(marketintel_data, 'fetch_michigan_sentiment_snapshot', return_value=official), \
             patch.object(marketintel_data, 'fetch_bls_cpi_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_ism_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_bea_core_pce_snapshot', side_effect=ValueError):
            result = fetch_fred_snapshot(object(), 'fixture-key')
        item = result['series']['consumer_sentiment']
        self.assertEqual((item['date'], item['display_value'], item['source']),
                         ('2026-09-01', 47.8, 'FRED'))

    def test_newer_bea_period_wins_while_fred_keeps_precision_for_same_month(self):
        bea = {'source': 'BEA', 'date': '2026-07-01', 'display_value': 3.3,
               'display_unit': 'percent_yoy', 'warning': 'Dato publicado por BEA.'}
        older_fred = {'observations': [
            {'date': '2026-06-01', 'value': '130'},
            {'date': '2025-06-01', 'value': '126'},
        ]}
        same_fred = {'observations': [
            {'date': '2026-07-01', 'value': '130.658'},
            {'date': '2025-07-01', 'value': '126.430'},
        ]}
        with patch.object(marketintel_data, 'fetch_bea_core_pce_snapshot', return_value=bea), \
             patch.object(marketintel_data, 'fetch_bls_cpi_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_ism_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_michigan_sentiment_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, '_cached_json_retry', return_value=older_fred):
            newer = fetch_fred_snapshot(object(), 'fixture-key')['series']['core_pce']
        self.assertEqual((newer['date'], newer['source'], newer['display_value']),
                         ('2026-07-01', 'BEA', 3.3))
        marketintel_data._MACRO_LAST_GOOD.clear()
        with patch.object(marketintel_data, 'fetch_bea_core_pce_snapshot', return_value=bea), \
             patch.object(marketintel_data, 'fetch_bls_cpi_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_ism_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, 'fetch_michigan_sentiment_snapshot', side_effect=ValueError), \
             patch.object(marketintel_data, '_cached_json_retry', return_value=same_fred):
            precise = fetch_fred_snapshot(object(), 'fixture-key')['series']['core_pce']
        self.assertEqual((precise['source'], precise['display_value']), ('FRED', 3.34))

    def test_a_new_failed_refresh_does_not_replace_a_newer_final_release(self):
        final = {'source': 'U. Michigan', 'date': '2026-09-01', 'display_value': 48.1,
                 'revision': 'final', 'fetched_at': '2026-09-25T14:00:00Z'}
        older = {**final, 'date': '2026-08-01', 'display_value': 51.7}
        preliminary = {**final, 'revision': 'preliminary', 'display_value': 47.8}
        with patch.object(marketintel_data, 'fetch_michigan_sentiment_snapshot',
                          side_effect=[final, older, preliminary]):
            first = fetch_fred_snapshot(object(), '')
            second = fetch_fred_snapshot(object(), '')
            third = fetch_fred_snapshot(object(), '')
        self.assertEqual(first['series']['consumer_sentiment']['status'], 'ok')
        for snapshot in (second, third):
            item = snapshot['series']['consumer_sentiment']
            self.assertEqual((item['date'], item['display_value'], item['status']),
                             ('2026-09-01', 48.1, 'stale'))

    def test_ism_reused_url_cannot_relabel_last_year(self):
        now = datetime.now(timezone.utc)
        prior = datetime.fromisoformat(marketintel_data._shift_month(now.date().isoformat(), -1))
        text = f'<h1>Manufacturing PMI® at 54.6%</h1><h1>{prior.strftime("%B")} {prior.year-1} ISM® Manufacturing PMI® Report</h1>'
        with patch.object(marketintel_data, '_cached_text', return_value=text):
            with self.assertRaises(ValueError):fetch_ism_snapshot(object())

    def test_public_bls_and_ism_do_not_require_fred_key(self):
        cpi={'source':'BLS','display_value':2.0,'date':'2026-08-01'}
        pmi={'source':'ISM','display_value':51.0,'date':'2026-08-01'}
        with patch.object(marketintel_data,'fetch_bls_cpi_snapshot',return_value=cpi), patch.object(marketintel_data,'fetch_ism_snapshot',return_value=pmi):
            result=fetch_fred_snapshot(object(),'')
        self.assertEqual(result['series']['cpi']['source'],'BLS')
        self.assertEqual(result['status'],'partial')
        self.assertEqual(len(result['series']),10)

    def test_official_fallbacks_return_periods_sources_and_preliminary_status(self):
        now=datetime.now(timezone.utc)
        latest_ism=datetime.fromisoformat(marketintel_data._shift_month(now.date().isoformat(),-1))
        latest_bea=datetime.fromisoformat(marketintel_data._shift_month(now.date().isoformat(),-2))
        ism_month=latest_ism.strftime('%B %Y')
        bea_month=latest_bea.strftime('%B %Y')
        html={
            'ismworld.org':f'<h1>Manufacturing PMI® at 54.6%</h1><h1>{ism_month} ISM® Manufacturing PMI® Report</h1>',
            'bea.gov':f'<h1>Personal Consumption Expenditures Price Index, Excluding Food and Energy</h1><table><tr><td>{bea_month}</td><td>+3.30%</td></tr></table>',
            'sca.isr.umich.edu':f'<h1>Preliminary Results for {ism_month}</h1><table><tr><td>Index of Consumer Sentiment</td><td>47.8</td></tr></table>',
        }
        def official(_requests,url,**kwargs):
            return next(page for host,page in html.items() if host in url)
        with patch.object(marketintel_data,'_cached_text',side_effect=official), patch.object(marketintel_data,'fetch_bls_cpi_snapshot',side_effect=ValueError('sin datos')):
            result=fetch_fred_snapshot(object(),'')
        self.assertEqual(result['series']['pmi']['display_value'],54.6)
        self.assertEqual(result['series']['core_pce']['display_value'],3.3)
        self.assertEqual(result['series']['core_pce']['display_unit'],'percent_yoy')
        self.assertEqual(result['series']['core_pce']['source'],'BEA')
        self.assertEqual(result['series']['consumer_sentiment']['source'],'U. Michigan')
        self.assertIn('preliminar',result['series']['consumer_sentiment']['warning'])
        self.assertEqual(result['series']['consumer_sentiment']['date'],latest_ism.strftime('%Y-%m-01'))

    def test_fred_timeout_falls_back_to_bea_without_inventing_index(self):
        now=datetime.now(timezone.utc)
        month=datetime.fromisoformat(marketintel_data._shift_month(now.date().isoformat(),-2)).strftime('%B %Y')
        page=f'<h1>Personal Consumption Expenditures Price Index, Excluding Food and Energy</h1>{month} +3.3%'
        with patch.object(marketintel_data,'_cached_text',return_value=page), patch.object(marketintel_data,'_cached_json_retry',side_effect=TimeoutError('fixture')), patch.object(marketintel_data,'fetch_bls_cpi_snapshot',side_effect=ValueError), patch.object(marketintel_data,'fetch_ism_snapshot',side_effect=ValueError):
            result=fetch_fred_snapshot(object(),'fixture-key')
        item=result['series']['core_pce']
        self.assertEqual((item['source'],item['display_value'],item['value']),('BEA',3.3,None))
        self.assertEqual(item['status'],'ok')

    def test_monthly_observation_not_aged_before_next_expected_publication(self):
        class September(datetime):
            @classmethod
            def now(cls,tz=None):return datetime(2026,9,25,tzinfo=tz or timezone.utc)
        observations={'observations':[{'date':'2026-07-01','value':'130.658'},{'date':'2025-07-01','value':'126.5'}]}
        with patch.object(marketintel_data,'datetime',September), patch.object(marketintel_data,'_cached_json_retry',return_value=observations), patch.object(marketintel_data,'fetch_bls_cpi_snapshot',side_effect=ValueError), patch.object(marketintel_data,'fetch_ism_snapshot',side_effect=ValueError), patch.object(marketintel_data,'fetch_michigan_sentiment_snapshot',side_effect=TimeoutError):
            result=fetch_fred_snapshot(object(),'fixture-key')
        for key in ('core_pce','consumer_sentiment'):
            self.assertEqual(result['series'][key]['date'],'2026-07-01')
            self.assertNotIn('period_warning',result['series'][key])

    def test_michigan_wrong_or_future_period_is_not_used(self):
        old='<h1>Final Results for January 2025</h1><div>Index of Consumer Sentiment 95.0</div>'
        future='<h1>Preliminary Results for December 2099</h1><div>Index of Consumer Sentiment 95.0</div>'
        with patch.object(marketintel_data,'_cached_text',side_effect=[old,future]):
            with self.assertRaises(ValueError):marketintel_data.fetch_michigan_sentiment_snapshot(object())
            with self.assertRaises(ValueError):marketintel_data.fetch_michigan_sentiment_snapshot(object())

    def test_failed_refresh_keeps_old_timestamp_and_explicit_stale_state(self):
        marketintel_data._MACRO_LAST_GOOD['fed_upper']={'source':'FRED','value':4,'display_value':4,'date':'2026-09-22','fetched_at':'2026-09-22T16:00:00Z','status':'ok'}
        with patch.object(marketintel_data,'_cached_json_retry',side_effect=ValueError), patch.object(marketintel_data,'fetch_ism_snapshot',side_effect=ValueError):
            result=fetch_fred_snapshot(object(),'fixture-key')
        self.assertEqual(result['status'],'error')
        item=result['series']['fed_upper']
        self.assertEqual(item['status'],'stale')
        self.assertEqual(item['fetched_at'],'2026-09-22T16:00:00Z')
        self.assertIsNone(result['series']['cpi']['display_value'])


if __name__ == '__main__':
    unittest.main()
