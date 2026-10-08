import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock
import pandas as pd
import servidor
from marketintel_pulse import PulseService, TICKERS, market_session, intraday_quote, daily_history, weighted
from marketintel_storage import LocalStore

NOW = datetime(2026, 9, 23, 14, 6, tzinfo=timezone.utc)


def frames(direction=1):
    daily_dates = pd.bdate_range(end='2026-09-22', periods=260)
    minute_dates = pd.date_range('2026-09-23 13:30', periods=36, freq='min', tz='UTC')
    daily, minute = {}, {}
    for ticker in TICKERS:
        base = 30 if ticker == '^VIX' else 100
        step = -direction*.03 if ticker == '^VIX' else direction*.04
        daily[('Close', ticker)] = [base] * 260
        values = [base + step*i for i in range(36)]
        for field, vals in [('Open', [base]+values[:-1]), ('Close',values), ('High',[x+.02 for x in values]), ('Low',[x-.02 for x in values]), ('Volume',[1000]*36)]:
            minute[(field,ticker)] = vals
    return pd.DataFrame(daily,index=daily_dates), pd.DataFrame(minute,index=minute_dates)


class MarketSentimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = LocalStore(self.tmp.name)

    def service(self, direction=1, minute=None, fred=None):
        daily, default_minute = frames(direction)
        download = Mock(side_effect=lambda *a, **kw: daily if kw['interval']=='1d' else (minute if minute is not None else default_minute))
        return PulseService(download, lambda: fred or {'series':{},'errors':[]}, servidor.build_market_context, self.store), download

    def test_bull_and_bear_are_distinct_continuous_readings(self):
        for direction, bound in [(1,60),(-1,40)]:
            svc,_=self.service(direction);result=svc.snapshot(now=NOW)
            self.assertEqual(result['status'],'ok')
            self.assertGreaterEqual(result['score'],bound) if direction==1 else self.assertLessEqual(result['score'],bound)
            self.assertEqual(sum(b['weight'] for b in result['intraday']['components']),100)
            self.assertNotIn('confidence',result['intraday'])

    def test_missing_data_never_becomes_neutral_50(self):
        svc,_=self.service(minute=pd.DataFrame());result=svc.snapshot(now=NOW)
        self.assertIsNone(result['score']);self.assertEqual(result['status'],'insufficient')
        self.assertEqual(result['intraday']['quality'],0)
        self.assertEqual(result['evaluation']['summary']['total'],0)

    def test_previous_session_and_stale_prices_are_excluded(self):
        _,minute=frames()
        for delta in (timedelta(days=1),timedelta(minutes=10)):
            old=minute.copy();old.index=old.index-delta
            svc,_=self.service(minute=old);result=svc.snapshot(now=NOW)
            self.assertIsNone(result['score']);self.assertFalse(result['quotes']['SPY']['usable'])

    def test_unknown_timezone_and_future_bars_are_not_current_data(self):
        _,minute=frames();naive=minute.copy();naive.index=naive.index.tz_localize(None)
        for frame in (naive,minute.set_axis(minute.index+pd.Timedelta(days=1))):
            svc,_=self.service(minute=frame);self.assertIsNone(svc.snapshot(now=NOW)['score'])

    def test_one_missing_sector_lowers_coverage(self):
        _,minute=frames();missing=minute.drop(columns='XLK',level=1)
        full,_=self.service();partial,_=self.service(minute=missing)
        self.assertLess(partial.snapshot(now=NOW)['intraday']['coverage'],full.snapshot(now=NOW)['intraday']['coverage'])

    def test_missing_spy_disables_direction(self):
        _,minute=frames();svc,_=self.service(minute=minute.drop(columns='SPY',level=1))
        self.assertIsNone(svc.snapshot(now=NOW)['score'])

    def test_unlabeled_single_asset_cannot_be_reused_as_all_tickers(self):
        _,minute=frames();svc,_=self.service(minute=minute.xs('SPY',axis=1,level=1))
        result=svc.snapshot(now=NOW)
        self.assertIsNone(result['score'])
        self.assertFalse(any(q['usable'] for q in result['quotes'].values()))

    def test_total_source_failure_backs_off_even_for_manual_refresh(self):
        svc,download=self.service(minute=pd.DataFrame());first=svc.snapshot(now=NOW)
        second=svc.snapshot(force=True,now=NOW+timedelta(seconds=20))
        self.assertEqual(download.call_count,2)
        self.assertTrue(second['cached']);self.assertEqual(first['updated_at'],second['updated_at'])

    def test_missing_opening_bar_is_not_labeled_open(self):
        _,minute=frames();quote=intraday_quote(minute.iloc[5:],'SPY',{'2026-09-22':100},market_session(NOW),NOW)
        self.assertIsNone(quote['ret_open']);self.assertIsNone(quote['distance_vwap'])

    def test_cache_preserves_query_time_and_cannot_cross_close(self):
        svc,download=self.service();first=svc.snapshot(now=NOW);second=svc.snapshot(now=NOW+timedelta(seconds=20))
        self.assertTrue(second['cached']);self.assertEqual(first['updated_at'],second['updated_at'])
        self.assertEqual(download.call_count,2)
        closed=svc.snapshot(now=NOW.replace(hour=21))
        self.assertIsNone(closed['score']);self.assertEqual(closed['status'],'closed')

    def test_expired_cached_prices_trigger_new_download(self):
        svc,download=self.service();svc.snapshot(now=NOW);result=svc.snapshot(now=NOW+timedelta(minutes=6))
        self.assertGreater(download.call_count,2);self.assertIsNone(result['score'])

    def test_no_browser_quote_can_override_download(self):
        svc,_=self.service()
        with patch.object(servidor,'pulse_service') as service:
            service.snapshot.side_effect=lambda force=False:svc.snapshot(force=force,now=NOW)
            response=servidor.app.test_client().post('/market-sentiment',json={'quotes':{'SPY':{'price':999999}}})
        self.assertEqual(response.status_code,200);self.assertLess(response.get_json()['quotes']['SPY']['price'],200)

    def test_context_vix_has_full_scale_and_curve_has_correct_units(self):
        history={t:[100]*260 for t in TICKERS};history['^VIX']=[30]*259+[10]
        result=servidor.build_market_context(history,{'series':{}},'2026-09-22',[])
        vix=next(b for b in result['components'] if b['key']=='volatility')
        self.assertGreater(vix['score'],90);self.assertEqual(weighted([(100,.7),(100,.3)]),100)
        self.assertEqual(servidor._percentile([7,7,7],7),50)
        fred={'series':{'yield_curve':{'value':.5,'history':[{'value':x} for x in (-1,0,.5,1,2)]}}}
        result=servidor.build_market_context(history,fred,'2026-09-22',[])
        macro=next(b for b in result['components'] if b['key']=='macro_risk')
        self.assertAlmostEqual(macro['score'],56.2,places=1)

    def test_calendar_handles_holiday_half_day_and_dst(self):
        self.assertFalse(market_session(datetime(2026,7,3,15,tzinfo=timezone.utc))['is_open'])
        short=market_session(datetime(2026,11,27,18,1,tzinfo=timezone.utc))
        self.assertFalse(short['is_open']);self.assertIn('18:00',short['close_at'])
        winter=market_session(datetime(2026,1,5,14,45,tzinfo=timezone.utc))
        self.assertTrue(winter['is_open']);self.assertIn('14:30',winter['open_at'])
        self.assertIn('13:30',market_session(NOW)['open_at'])

    def test_calendar_failure_does_not_guess_market_open(self):
        with patch('marketintel_pulse.calendar_for',side_effect=RuntimeError):state=market_session(NOW)
        self.assertFalse(state['is_open']);self.assertFalse(state['calendar_verified'])

    def test_partial_daily_bar_cannot_settle_today(self):
        daily,_=frames();daily.loc[pd.Timestamp('2026-09-23')]=999
        self.assertNotIn('2026-09-23',daily_history(daily,'SPY',market_session(NOW)))
        svc,_=self.service();result=svc.snapshot(now=NOW)
        self.assertEqual(result['evaluation']['summary']['evaluated'],0)
        self.store.settle_signals({'2026-09-23':103});journal=self.store.signal_history()
        self.assertEqual(journal['summary']['evaluated'],1);self.assertEqual(journal['summary']['hit_rate'],100)
        self.store.settle_signals({'2026-09-23':95})
        self.assertEqual(self.store.signal_history()['observations'][0]['close_price'],103)

    def test_record_deduplication_and_immutability(self):
        svc,_=self.service();result=svc.snapshot(now=NOW);self.store.record_signal(result)
        result['intraday']['score']=1;self.store.record_signal(result);history=self.store.signal_history()
        self.assertEqual(history['summary']['total'],1);self.assertGreater(history['observations'][0]['score'],60)


if __name__=='__main__': unittest.main()
