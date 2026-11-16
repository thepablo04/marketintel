import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import marketintel_reports as reports

UTC=timezone.utc
OPEN=datetime(2026,11,16,14,tzinfo=UTC)
CLOSE=datetime(2026,11,16,22,tzinfo=UTC)
SESSION={'date':'2026-11-16','open_at':'2026-11-16T14:30:00+00:00','close_at':'2026-11-16T21:00:00+00:00','previous_date':'2026-11-13','calendar_verified':True}


def chart(symbol='NVDA'):
    dates=[OPEN-timedelta(minutes=10),CLOSE-timedelta(minutes=10),CLOSE]
    return {'meta':{'symbol':symbol,'currency':'USD','previousClose':100,'regularMarketPrice':110,'regularMarketTime':(CLOSE-timedelta(hours=1)).timestamp(),
                    'currentTradingPeriod':{'regular':{'end':(CLOSE-timedelta(hours=1)).timestamp()}}},
            'timestamp':[date.timestamp() for date in dates],'indicators':{'quote':[{'close':[105,115,999]}]}}


class Offline:
    def get(self,*args,**kwargs):raise TimeoutError('Never expose provider keys or exception strings')


class ReportTests(unittest.TestCase):
    def setUp(self):reports._CACHE.clear()
    def test_calendar_holiday_and_clock_fail_closed(self):
        for now in [datetime(2026,11,15,22,tzinfo=UTC),datetime(2026,11,26,22,tzinfo=UTC)]:
            with self.assertRaisesRegex(ValueError,'no hay sesión'):
                reports.build_report('closing',[],requests_module=Offline(),now=now)
        with self.assertRaisesRegex(ValueError,'17:00'):
            reports.build_report('closing',[],requests_module=Offline(),now=CLOSE-timedelta(seconds=1))
        for hour in [3,10,17]:
            with self.assertRaisesRegex(ValueError,'premercado'):
                reports.build_report('opening',[],requests_module=Offline(),now=datetime(2026,11,16,hour+5,tzinfo=UTC))
        with self.assertRaisesRegex(ValueError,'zona'):
            reports.build_report('closing',[],requests_module=Offline(),now=datetime(2026,11,16,22))

    def test_closing_cutoff_uses_new_york_dst_not_fixed_utc(self):
        with patch.object(reports,'fetch_report_breadth',return_value=[]),patch.object(reports,'_chart',return_value={}),patch.object(reports,'_macro',return_value=[]):
            summer=reports.build_report('closing',[],requests_module=Offline(),now=datetime(2026,7,6,21,tzinfo=UTC))
            winter=reports.build_report('closing',[],requests_module=Offline(),now=CLOSE)
        self.assertEqual(summer['cutoff_at'],'2026-07-06T21:00:00+00:00')
        self.assertEqual(winter['cutoff_at'],'2026-11-16T22:00:00+00:00')

    def test_premarket_excludes_regular_quote_and_unfinished_future_candle(self):
        data=chart()
        q=reports._quote(data,'NVDA','Nvidia','opening',SESSION,OPEN)
        self.assertEqual(q['price'],105)
        self.assertEqual(q['change_pct'],5)
        self.assertEqual(q['as_of'],'2026-11-16T13:55:00+00:00')
        data['timestamp']=[(OPEN+timedelta(minutes=1)).timestamp()]
        data['indicators']['quote'][0]['close']=[999]
        self.assertIsNone(reports._quote(data,'NVDA','Nvidia','opening',SESSION,OPEN)['price'])

    def test_closing_keeps_regular_and_after_hours_separate_and_caps_at_17(self):
        q=reports._quote(chart(),'NVDA','Nvidia','closing',SESSION,CLOSE)
        self.assertEqual(q['price'],110)
        self.assertEqual(q['post_price'],115)
        self.assertEqual(q['post_as_of'],'2026-11-16T21:55:00+00:00')
        self.assertNotEqual(q['post_price'],999)

    def test_old_wrong_symbol_stale_future_and_invalid_baseline_are_unavailable(self):
        cases=[]
        old=chart();old['meta']['currentTradingPeriod']['regular']['end']-=86400;cases.append(old)
        wrong=chart('AAPL');cases.append(wrong)
        zero=chart();zero['meta']['previousClose']=0;cases.append(zero)
        stale=chart();stale['timestamp']=[(OPEN-timedelta(hours=1)).timestamp()];stale['indicators']['quote'][0]['close']=[100];cases.append(stale)
        for data in cases:
            self.assertEqual(reports._quote(data,'NVDA','Nvidia','opening',SESSION,OPEN)['status'],'unavailable')

    def test_source_failure_returns_partial_never_fabricated_prices(self):
        report=reports.build_report('closing',['NVDA'],requests_module=Offline(),now=CLOSE)
        self.assertEqual(report['status'],'partial')
        self.assertTrue(all(q['price'] is None for q in report['quotes']))
        self.assertTrue(all(row['valid']==0 for row in report['breadth']))
        self.assertEqual(report['watchlist_reports'][0]['status'],'unverified')
        self.assertFalse(report['macro'])
        self.assertNotIn('Never expose',str(report))

    def test_watchlist_filters_ticker_news_date_and_exact_cutoff(self):
        data={'news':[{'title':'Nvidia reports financial results','relatedTickers':['NVDA'],'providerPublishTime':(CLOSE-timedelta(minutes=30)).timestamp(),'link':'https://issuer.example/report','publisher':'Issuer'},
                       {'title':'Nvidia financial results','relatedTickers':['NVDA'],'providerPublishTime':(CLOSE+timedelta(minutes=1)).timestamp(),'link':'https://issuer.example/future'},
                       {'title':'Apple quarterly results','relatedTickers':['AAPL'],'providerPublishTime':CLOSE.timestamp(),'link':'https://issuer.example/other'},
                       {'title':'Nvidia earnings','relatedTickers':['NVDA'],'providerPublishTime':(CLOSE-timedelta(days=1)).timestamp(),'link':'https://issuer.example/old'}]}
        with patch.object(reports,'_fetch',return_value=data):result=reports._watchlist_reports(Offline(),['NVDA'],CLOSE,{})
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['source_url'],'https://issuer.example/report')
        self.assertEqual(result[0]['ticker'],'NVDA')
        self.assertIsNone(result[0]['actual'])

    def test_breadth_counts_only_verified_same_session_values(self):
        universe={'symbols':['NVDA','AAPL','MSFT','TSLA'],'source':'fixture'}
        known={symbol:{'status':'ok','price':value,'previous':100,'as_of':SESSION['close_at']} for symbol,value in [('NVDA',110),('AAPL',90),('MSFT',100)]}
        known['TSLA']={'status':'ok','price':999,'previous':100,'as_of':'2026-11-13T21:00:00+00:00'}
        row=reports._breadth(universe,{},known,'closing',SESSION,CLOSE,'S&P')
        self.assertEqual((row['up'],row['down'],row['unchanged'],row['valid'],row['missing']),(1,1,1,3,1))

    def test_pdf_contains_exact_snapshot_and_never_fetches(self):
        report=reports.build_report('closing',[],requests_module=Offline(),now=CLOSE)
        report['summary']=['<script>must be text, not executable</script>']
        data=reports.render_report_pdf(report)
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertGreater(len(data),2000)

    def test_bls_release_must_be_published_today_before_cutoff(self):
        page='<p>For release at 8:30 a.m. (ET) Monday November 16, 2026 CONSUMER PRICE INDEX - OCTOBER 2026 The Consumer Price Index for All Urban Consumers increased 0.2 percent in October on a seasonally adjusted basis.</p>'
        self.assertIsNotNone(reports._bls_release(page,CLOSE,'CPI'))
        self.assertIsNone(reports._bls_release(page.replace('November 16','November 15'),CLOSE,'CPI'))
        self.assertIsNone(reports._bls_release(page,OPEN-timedelta(hours=1),'CPI'))

    def test_watchlist_empty_never_uses_a_default_list(self):
        report=reports.build_report('closing',[],requests_module=Offline(),now=CLOSE)
        self.assertEqual(report['watchlist'],[])
        self.assertEqual(report['watchlist_reports'],[])
        self.assertTrue(any('vacía' in line for line in report['warnings']))

    def test_pdf_renders_the_exact_partial_snapshot_without_network_calls(self):
        report=reports.build_report('closing',[],requests_module=Offline(),now=CLOSE)
        report['quotes'][0]['label']='<script>Untrusted provider title</script>'
        document=reports.render_report_pdf(report)
        self.assertTrue(document.startswith(b'%PDF-'))
        self.assertGreater(len(document),3000)


if __name__=='__main__':unittest.main()
