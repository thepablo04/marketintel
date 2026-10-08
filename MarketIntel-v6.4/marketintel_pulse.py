"""Timestamped intraday market observations. Heuristic, not a probability model."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
import math
import statistics
import threading
import time
from zoneinfo import ZoneInfo

import pandas as pd

CORE = ('SPY', 'QQQ', 'IWM', 'HYG', '^VIX')
SECTORS = ('XLK', 'XLF', 'XLE', 'XLI', 'XLY', 'XLP', 'XLV', 'XLC', 'XLU', 'XLRE', 'XLB')
TICKERS = CORE + SECTORS
NY = ZoneInfo('America/New_York')


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def weighted(values):
    valid = [(number(value), weight) for value, weight in values if number(value) is not None and weight > 0]
    return sum(value * weight for value, weight in valid) / sum(weight for _, weight in valid) if valid else None


def signal(value, scale):
    value = number(value)
    return max(0, min(100, 50 + 50 * value / scale)) if value is not None else None


@lru_cache(maxsize=8)
def calendar_for(year):
    import exchange_calendars as calendars
    return calendars.get_calendar('XNYS', start=f'{year-2}-01-01', end=f'{year+2}-12-31')


def market_session(now=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(NY)
    day = local.date().isoformat()
    info = {'date': day, 'now': now.isoformat(), 'timezone': 'America/New_York',
            'is_open': False, 'calendar_verified': False, 'state': 'unknown',
            'label': 'Horario no verificado; sin señal intradía'}
    try:
        cal = calendar_for(local.year)
        today = pd.Timestamp(day)
        trading = cal.is_session(today)
        session = today if trading else cal.date_to_session(today, direction='previous')
        previous = cal.previous_session(session) if trading else session
        info.update(calendar_verified=True, previous_date=previous.date().isoformat())
        if not trading:
            info.update(state='closed', label='Mercado cerrado · festivo o fin de semana')
            return info
        opening, closing = cal.session_open(session), cal.session_close(session)
        stamp = pd.Timestamp(now)
        opened = opening <= stamp < closing
        state = 'regular' if opened else 'premarket' if stamp < opening else 'closed'
        info.update(is_open=bool(opened), state=state,
                    open_at=opening.isoformat(), close_at=closing.isoformat(),
                    elapsed_minutes=(stamp-opening).total_seconds()/60,
                    remaining_minutes=(closing-stamp).total_seconds()/60,
                    label=('Mercado abierto' if opened else 'Antes de la apertura' if state == 'premarket' else 'Mercado cerrado') + ' · Nueva York')
    except Exception:
        # No UTC-as-New-York fallback and no guessed holidays.
        pass
    return info


def ticker_frame(frame, ticker):
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        for level in range(frame.columns.nlevels):
            if ticker in frame.columns.get_level_values(level):
                return frame.xs(ticker, level=level, axis=1).copy()
        return pd.DataFrame()
    # Every request is for multiple assets. A flat response cannot identify
    # which asset it belongs to, so never reuse it as all sixteen tickers.
    return pd.DataFrame()


def daily_history(frame, ticker, session):
    rows = ticker_frame(frame, ticker)
    if rows.empty or 'Close' not in rows:
        return {}
    output = {}
    # Always omit today's daily candle; its closing price is not final yet.
    for stamp, value in rows['Close'].items():
        value = number(value)
        day = pd.Timestamp(stamp).date().isoformat()
        if day < session['date'] and value is not None and value > 0:
            output[day] = value
    return dict(sorted(output.items()))


def intraday_quote(frame, ticker, history, session, now):
    base = {'ticker': ticker, 'source': 'Yahoo Finance · velas 1m', 'price': None,
            'data_at': None, 'queried_at': now.isoformat(), 'usable': False,
            'status': 'unavailable', 'reason': 'Sin velas intradía verificables.'}
    rows = ticker_frame(frame, ticker)
    if rows.empty or 'Close' not in rows:
        return base
    index = pd.DatetimeIndex(rows.index)
    if index.tz is None:
        base['reason'] = 'La fuente no incluyó zona horaria.'
        return base
    rows.index = index.tz_convert('UTC')
    rows = rows.sort_index()
    rows = rows[~rows.index.duplicated(keep='last')]
    rows = rows[pd.to_numeric(rows['Close'], errors='coerce').gt(0)]
    rows = rows[rows.index <= pd.Timestamp(now)]
    if rows.empty:
        return base
    last = rows.iloc[-1]
    at = rows.index[-1]
    price = number(last['Close'])
    age = max(0, (pd.Timestamp(now)-at).total_seconds())
    day = at.tz_convert(NY).date().isoformat()
    base.update(price=price, data_at=at.isoformat(), age_seconds=round(age),
                session_date=day, status='recent' if age <= 300 else 'delayed',
                reason='Hora de inicio de la última vela de 1 minuto; no cotización tick a tick.')
    if not session.get('is_open'):
        base.update(status='closed', reason='Última sesión disponible; no es una señal para un mercado abierto.')
        return base
    today = rows[(rows.index >= pd.Timestamp(session['open_at'])) & (rows.index < pd.Timestamp(session['close_at']))]
    if today.empty or day != session['date'] or age > 300:
        base.update(status='stale', reason='Datos antiguos o de otra sesión; excluidos del sesgo intradía.')
        return base
    # A missing opening bar must not be relabeled as the exchange opening price.
    first_at = today.index[0]
    open_value = number(today.iloc[0].get('Open')) if (first_at-pd.Timestamp(session['open_at'])).total_seconds() < 60 else None
    prior = history.get(session.get('previous_date'))
    base.update(usable=True, status='recent',
                ret_open=(price/open_value-1) if open_value and price else None,
                ret_day=(price/prior-1) if prior and price else None,
                change_pct=(price/prior-1)*100 if prior and price else None)
    before = today[today.index <= at-pd.Timedelta(minutes=30)]
    base['ret_30m'] = price/float(before['Close'].iloc[-1])-1 if not before.empty and (at-before.index[-1]).total_seconds() <= 32*60 else None
    # VWAP is only included with positive volume and a complete opening history.
    base['distance_vwap'] = None
    if open_value and 'Volume' in today:
        volume = pd.to_numeric(today['Volume'], errors='coerce').fillna(0).clip(lower=0)
        if volume.sum() > 0 and {'High', 'Low'} <= set(today.columns):
            typical = (today['High']+today['Low']+today['Close'])/3
            usable_volume = volume.where(typical.notna(), 0)
            vwap = number((typical*usable_volume).sum()/usable_volume.sum()) if usable_volume.sum() > 0 else None
            if vwap and vwap > 0:
                base.update(vwap=round(vwap, 4), distance_vwap=price/vwap-1)
    return base


def component(key, label, weight, scores, expected, detail):
    values = [number(x) for x in scores if number(x) is not None]
    score = sum(values)/len(values) if values else None
    coverage = min(1, len(values)/expected) if expected else 0
    return {'key': key, 'label': label, 'weight': weight, 'score': round(score, 1) if score is not None else None,
            'available': score is not None, 'coverage': round(coverage, 3), 'sample': len(values),
            'state': 'bullish' if score is not None and score >= 60 else 'bearish' if score is not None and score <= 40 else 'neutral', 'detail': detail}


def intraday_score(quotes, session):
    valid = {t: q for t,q in quotes.items() if q.get('usable')}
    index_signals = []
    for ticker in ('SPY', 'QQQ', 'IWM'):
        q = valid.get(ticker, {})
        index_signals.extend([signal(q.get('ret_open'), .008), signal(q.get('ret_day'), .012), signal(q.get('ret_30m'), .005), signal(q.get('distance_vwap'), .004)])
    breadth = []
    for ticker in SECTORS:
        q = valid.get(ticker, {})
        for field in ('ret_open', 'distance_vwap'):
            value = q.get(field)
            breadth.append(100 if value > .0002 else 0 if value < -.0002 else 50) if value is not None else breadth.append(None)
    vix = valid.get('^VIX', {})
    vix_signals = [signal(-vix[k], .05) if vix.get(k) is not None else None for k in ('ret_day', 'ret_open')]
    spy, iwm, hyg = (valid.get(t, {}) for t in ('SPY', 'IWM', 'HYG'))
    relative = iwm['ret_open']-spy['ret_open'] if iwm.get('ret_open') is not None and spy.get('ret_open') is not None else None
    blocks = [
        component('indices', 'Índices durante la sesión', 45, index_signals, 12, 'SPY, QQQ e IWM: apertura, cierre previo, últimos 30 min y VWAP.'),
        component('sectors', 'Participación sectorial', 25, breadth, 22, 'Proxy de 11 ETFs sectoriales; no cuenta todas las acciones del mercado.'),
        component('vix', 'Volatilidad intradía', 20, vix_signals, 2, 'Variación del VIX desde el cierre previo y la apertura; invertida.'),
        component('risk', 'Riesgo intradía', 10, [signal(relative, .005), signal(hyg.get('ret_day'), .005)], 2, 'IWM frente a SPY y cambio diario de HYG; proxies, no flujo de órdenes.')]
    effective = sum(b['weight']*b['coverage'] for b in blocks)
    score = weighted([(b['score'], b['weight']*b['coverage']) for b in blocks])
    required = 'SPY' in valid and any(t in valid for t in ('QQQ', 'IWM'))
    usable = session.get('is_open') and required and effective >= 45
    if not usable:
        score = None
    elif score is not None:
        score = round(score, 1)
    scores = [b['score'] for b in blocks if b['available']]
    agreement = max(0, 100-2*statistics.pstdev(scores)) if scores else 0
    quality = round(effective*(.5+.5*agreement/100)) if usable else 0
    status = 'ok' if usable else 'closed' if session['state'] in ('closed', 'premarket') else 'insufficient'
    label = 'Sesgo alcista' if score is not None and score >= 60 else 'Sesgo bajista' if score is not None and score <= 40 else 'Mixto / indeciso' if score is not None else 'Sin lectura intradía'
    return {'score': score, 'label': label, 'status': status, 'quality': quality,
            'coverage': round(effective), 'components': blocks,
            'provisional': bool(usable and session.get('elapsed_minutes', 0) < 15),
            'quality_note': 'Calidad = cobertura y acuerdo de señales. No es probabilidad de acertar.',
            'reason': '' if usable else 'Se necesitan SPY y QQQ o IWM de la sesión actual, datos de menos de 5 min y cobertura suficiente. Antes de la apertura no se presenta el cierre anterior como señal de hoy.'}


class PulseService:
    def __init__(self, download, fetch_fred, build_context, store):
        self.download, self.fetch_fred, self.build_context, self.store = download, fetch_fred, build_context, store
        self.lock = threading.Lock()
        self.daily = None
        self.daily_at = 0
        self.result = None
        self.result_at = 0

    def _download(self, interval, period):
        try:
            frame = self.download(' '.join(TICKERS), interval=interval, period=period,
                                  auto_adjust=False, prepost=False, progress=False,
                                  threads=4, group_by='column', timeout=8)
            if frame is None or frame.empty:
                return pd.DataFrame(), ['Yahoo: respuesta vacía ('+interval+').']
            return frame, []
        except Exception as exc:
            return pd.DataFrame(), ['Yahoo '+interval+': '+type(exc).__name__]

    def snapshot(self, force=False, now=None):
        fixed_now = now
        with self.lock:
            now = fixed_now or datetime.now(timezone.utc)
            session = market_session(now)
            elapsed = time.monotonic()-self.result_at
            cache_valid = self.result is not None and self.result['session']['state'] == session['state'] and self.result['session']['date'] == session['date']
            if cache_valid and session['is_open']:
                cache_valid = all((pd.Timestamp(now)-pd.Timestamp(q['data_at'])).total_seconds() <= 300 for q in self.result['quotes'].values() if q.get('usable'))
            retry_delay = 300 if self.result and not any(q.get('price') for q in self.result['quotes'].values()) else (15 if force else 60)
            if cache_valid and elapsed < retry_delay:
                # Cached timestamps remain unchanged, never stamped as a fresh query.
                return dict(self.result, cached=True)
            errors = []
            with ThreadPoolExecutor(max_workers=3) as pool:
                minute_future = pool.submit(self._download, '1m', '5d')
                fred_future = pool.submit(self.fetch_fred)
                minute, errs = minute_future.result()
                errors.extend(errs)
                if self.daily is None or time.monotonic()-self.daily_at > 900:
                    downloaded, errs = self._download('1d', '1y')
                    errors.extend(errs)
                    if not downloaded.empty:
                        self.daily, self.daily_at = downloaded, time.monotonic()
                try:
                    fred = fred_future.result()
                except Exception as exc:
                    fred = {'series': {}, 'errors': ['FRED: '+type(exc).__name__]}
            if fixed_now is None:
                now = datetime.now(timezone.utc)
                session = market_session(now)
            histories = {t: daily_history(self.daily, t, session) for t in TICKERS}
            quotes = {t: intraday_quote(minute, t, histories[t], session, now) for t in TICKERS}
            history_dates = {t: max(h) if h else None for t,h in histories.items()}
            # An old asset is omitted instead of borrowing another asset's latest date.
            expected = session.get('previous_date')
            clean_histories = {t: list(h.values()) for t,h in histories.items() if h and expected and max(h) == expected}
            dates = [history_dates[t] for t in clean_histories]
            for key, series in list((fred.get('series') or {}).items()):
                try:
                    age = (now.date()-datetime.fromisoformat(series['date']).date()).days
                    if age > 10 or age < 0:
                        fred['series'].pop(key)
                        errors.append('FRED '+key+': período fuera de vigencia; excluido.')
                except (ValueError, KeyError, TypeError):
                    fred['series'].pop(key)
                    errors.append('FRED '+key+': fecha no verificable; excluido.')
            context = self.build_context(clean_histories, fred, min(dates) if dates else None, errors)
            intra = intraday_score(quotes, session)
            result = {'version': '6.2', 'status': intra['status'], 'score': intra['score'],
                      'label': intra['label'], 'session': session, 'intraday': intra,
                      'context': context, 'quotes': quotes, 'history_dates': history_dates,
                      'updated_at': now.isoformat(), 'cached': False,
                      'errors': errors + list(fred.get('errors') or []),
                      'retry_after_seconds': 300 if minute.empty else 60,
                      'disclaimer': 'Indicador heurístico experimental; no predice con certeza el cierre ni recomienda operaciones.'}
            try:
                self.store.settle_signals(histories.get('SPY', {}))
                self.store.record_signal(result)
                journal = self.store.signal_history()
                result['evaluation'] = {'summary': journal['summary'], 'method': journal['method']}
            except Exception as exc:
                result['evaluation'] = {'error': 'No se pudo guardar el seguimiento local: '+type(exc).__name__}
            self.result, self.result_at = result, time.monotonic()
            return result
