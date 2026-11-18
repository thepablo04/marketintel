"""Public breadth observations with explicit membership and quote coverage."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime, timedelta, timezone
from html.parser import HTMLParser
from io import StringIO
from zoneinfo import ZoneInfo
import csv
import math
import re
import threading
import time

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
_HEADERS = {'User-Agent': 'Mozilla/5.0 MarketIntel/1.0'}
_CACHE = {}
_LOCK = threading.RLock()
_SP500 = 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv'
_NDX = 'https://www.slickcharts.com/nasdaq100'
_SPARK = 'https://query1.finance.yahoo.com/v7/finance/spark'


def _timestamp(value):
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            if value > 1e12:
                value /= 1000
            return datetime.fromtimestamp(value, UTC)
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


def _symbol(value):
    symbol = str(value or '').strip().upper().replace('.', '-')
    return symbol if re.fullmatch(r'[A-Z][A-Z0-9-]{0,14}', symbol) else None


def _fetch(http, url, params=None, *, is_json=True, ttl=45):
    key = (id(http), url, tuple(sorted((params or {}).items())), is_json)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1]
    response = http.get(url, params=params, headers=_HEADERS, timeout=4)
    response.raise_for_status()
    value = response.json() if is_json else response.text
    with _LOCK:
        if len(_CACHE) >= 128:
            _CACHE.clear()
        _CACHE[key] = (time.monotonic(), value)
    return value


def _parallel(function, items, workers=6):
    def safe(item):
        try:
            return item, function(item)
        except Exception:
            return item, None
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(items)))) as executor:
        return dict(executor.map(safe, items))


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table = []
        elif tag == 'tr' and self.table is not None:
            self.row = []
        elif tag in ('th', 'td') and self.row is not None:
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('th', 'td') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def _members(http, index):
    url = _SP500 if index == 'sp500' else _NDX
    raw = _fetch(http, url, is_json=False, ttl=3600)
    if index == 'sp500':
        symbols = [_symbol(row.get('Symbol')) for row in csv.DictReader(StringIO(raw))]
    else:
        parser = _Tables()
        parser.feed(raw)
        symbols = []
        for table in parser.tables:
            if not table:
                continue
            header = [cell.lower() for cell in table[0]]
            if 'symbol' in header and 'company' in header:
                column = header.index('symbol')
                symbols = [_symbol(row[column]) for row in table[1:] if len(row) > column]
                break
    symbols = list(dict.fromkeys(symbol for symbol in symbols if symbol))
    lower, upper = (450, 525) if index == 'sp500' else (95, 110)
    if not lower <= len(symbols) <= upper:
        raise ValueError('No se pudo verificar la composición pública del índice.')
    return {'symbols': symbols, 'source_url': url,
            'source': 'datasets/s-and-p-500-companies' if index == 'sp500' else 'Slickcharts'}


def _batch(http, symbols):
    raw = _fetch(http, _SPARK, {'symbols': ','.join(symbols), 'range': '1d',
                              'interval': '1m', 'includePrePost': 'true'})
    payload = raw.get('spark') or {}
    if payload.get('error'):
        return {}
    wanted = set(symbols)
    output = {}
    for item in payload.get('result') or []:
        symbol = _symbol(item.get('symbol'))
        charts = item.get('response') or []
        if symbol in wanted and charts and isinstance(charts[0], dict):
            chart = charts[0]
            if _symbol((chart.get('meta') or {}).get('symbol')) == symbol:
                output[symbol] = chart
    return output


def _baseline(chart, session):
    meta = chart.get('meta') or {}
    if meta.get('currency') != 'USD' or meta.get('instrumentType') != 'EQUITY':
        return None
    opening = _timestamp(session.get('open_at'))
    if not opening:
        return None
    day = opening.astimezone(NY).date()
    period = ((meta.get('currentTradingPeriod') or {}).get('regular') or {})
    period_end = _timestamp(period.get('end'))
    if not period_end or period_end.astimezone(NY).date() != day:
        return None
    return _number(meta.get('previousClose'))


def _observation(chart, kind, session, cutoff):
    meta = chart.get('meta') or {}
    previous = _baseline(chart, session)
    if previous is None:
        return None
    closing = _timestamp(session.get('close_at'))
    opening = _timestamp(session.get('open_at'))
    if not closing or not opening:
        return None
    day = opening.astimezone(NY).date()
    if kind == 'closing':
        observed = _timestamp(meta.get('regularMarketTime'))
        price = _number(meta.get('regularMarketPrice'))
        if (not observed or observed.astimezone(NY).date() != day or
                not closing - timedelta(minutes=2) <= observed <= min(cutoff, closing + timedelta(minutes=2))):
            return None
    else:
        # Completed candles use their end; an irregular terminal quote has its
        # actual timestamp. Never make that quote appear one/five minutes newer.
        seconds = {'1m': 60, '5m': 300}.get(meta.get('dataGranularity', '5m'))
        if seconds is None:
            return None
        begin = datetime.combine(day, dtime(4), NY).astimezone(UTC)
        end = min(cutoff, opening)
        indicator = ((chart.get('indicators') or {}).get('quote') or [{}])[0]
        bars = []
        for raw_time, raw_price in zip(chart.get('timestamp') or [], indicator.get('close') or []):
            observed, price = _timestamp(raw_time), _number(raw_price)
            if observed and price is not None:
                completed = observed + timedelta(seconds=seconds) if observed.timestamp() % seconds == 0 else observed
                if begin <= observed and completed <= end:
                    bars.append((completed, price))
        if not bars:
            return None
        observed, price = max(bars)
        if cutoff - observed > timedelta(minutes=20):
            return None
    return (price, previous, observed) if price is not None else None


def _fmp_trades(http, symbols, key):
    if not key or not symbols:
        return {}
    raw = _fetch(http, 'https://financialmodelingprep.com/stable/batch-aftermarket-trade',
                 {'symbols': ','.join(symbols), 'apikey': key}, ttl=30)
    if not isinstance(raw, list):
        return {}
    wanted = set(symbols)
    return {symbol: row for row in raw if isinstance(row, dict)
            and (symbol := _symbol(row.get('symbol'))) in wanted}


def _fmp_observation(row, chart, session, cutoff):
    if not chart or _symbol(row.get('symbol')) != _symbol((chart.get('meta') or {}).get('symbol')):
        return None
    prior = _baseline(chart, session) if chart else None
    price = _number(row.get('price'))
    stamp = _timestamp(row.get('timestamp') or row.get('tradeTime'))
    opening = _timestamp(session.get('open_at'))
    if prior is None or price is None or stamp is None or opening is None:
        return None
    if row.get('currency') not in (None, 'USD'):
        return None
    begin = datetime.combine(opening.astimezone(NY).date(), dtime(4), NY).astimezone(UTC)
    if not begin <= stamp < opening or stamp > cutoff or cutoff-stamp > timedelta(minutes=20):
        return None
    return price, prior, stamp


def fetch_report_breadth(requests_module, kind, session, cutoff, now=None, *, fmp_key=''):
    """Return counts only for verified observations in the requested session window."""
    if kind not in ('opening', 'closing') or not isinstance(cutoff, datetime) or cutoff.tzinfo is None:
        raise ValueError('Ventana de amplitud inválida.')
    cutoff = cutoff.astimezone(UTC)
    universes = _parallel(lambda index: _members(requests_module, index), ['sp500', 'nasdaq100'], 2)
    symbols = sorted({symbol for universe in universes.values() if universe
                      for symbol in universe['symbols']})
    chunks = [tuple(symbols[i:i + 20]) for i in range(0, len(symbols), 20)]
    batches = _parallel(lambda chunk: _batch(requests_module, chunk), chunks)
    charts = {symbol: chart for batch in batches.values() if batch for symbol, chart in batch.items()}
    observations = {symbol: observed for symbol, chart in charts.items()
                    if (observed := _observation(chart, kind, session, cutoff))}
    # Retry only responses that were not delivered, not stocks with old/no
    # trades. A retry cannot manufacture a recent premarket observation.
    absent = [symbol for symbol in symbols if symbol not in charts]
    if absent:
        retry_chunks = [tuple(absent[i:i+20]) for i in range(0, len(absent), 20)]
        retried = _parallel(lambda chunk: _batch(requests_module, chunk), retry_chunks)
        for batch in retried.values():
            for symbol, chart in (batch or {}).items():
                charts[symbol] = chart
                observed = _observation(chart, kind, session, cutoff)
                if observed:
                    observations[symbol] = observed
    fmp_symbols = set()
    if kind == 'opening' and fmp_key:
        missing = [symbol for symbol in symbols if symbol not in observations]
        batches = _parallel(lambda chunk: _fmp_trades(requests_module, chunk, fmp_key),
                            [tuple(missing[i:i+80]) for i in range(0, len(missing), 80)])
        for batch in batches.values():
            for symbol, row in (batch or {}).items():
                observed = _fmp_observation(row, charts.get(symbol), session, cutoff)
                if observed:
                    observations[symbol] = observed
                    fmp_symbols.add(symbol)
    output = []
    for index, label in [('sp500', 'S&P 500'), ('nasdaq100', 'Nasdaq 100')]:
        universe = universes.get(index)
        members = universe['symbols'] if universe else []
        result = {'label': label, 'total': len(members) or None, 'valid': 0, 'up': 0,
                  'down': 0, 'unchanged': 0, 'missing': len(members) or None,
                  'status': 'unavailable', 'as_of': None, 'coverage_pct': None,
                  'source': 'Yahoo Finance Spark · composición: ' + universe['source'] if universe else 'Composición no disponible',
                  'source_url': _SPARK,
                  'membership_source_url': universe['source_url'] if universe else None,
                  'note': 'Composición pública consultada; las cotizaciones incluyen su hora. Los datos ausentes no se extrapolan al índice.'}
        stamps = []
        for symbol in members:
            observed = observations.get(symbol)
            if not observed:
                continue
            price, previous, stamp = observed
            result['valid'] += 1
            result['up' if price > previous else 'down' if price < previous else 'unchanged'] += 1
            stamps.append(stamp)
        if members:
            result['missing'] = len(members) - result['valid']
            result['coverage_pct'] = round(result['valid'] * 100 / len(members), 2)
            result['status'] = 'ok' if result['valid'] == len(members) else 'partial' if result['valid'] else 'unavailable'
        if stamps:
            result['as_of'] = min(stamps).isoformat()
            result['latest_as_of'] = max(stamps).isoformat()
        result['alternative_valid'] = sum(symbol in fmp_symbols for symbol in members)
        if result['alternative_valid']:
            result['source'] += ' + FMP · operaciones de premercado'
        result['missing_reasons'] = {
            'no_response': sum(symbol not in charts for symbol in members if symbol not in observations),
            'no_recent_verified_price': sum(symbol in charts for symbol in members if symbol not in observations),
        }
        output.append(result)
    return output


def _calendar_time(value):
    """A calendar date or an ambiguous local clock is not a publication time."""
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})', value.strip()):
        return None
    return _timestamp(value.strip())


def _calendar_actual(row):
    # Zero and negative EPS are valid observations. Their accounting basis is
    # not documented by this endpoint, so these values are never presented.
    for name in ('epsActual', 'revenueActual'):
        value = row.get(name)
        if value is None or isinstance(value, bool):
            continue
        try:
            if math.isfinite(float(value)):
                return True
        except (ValueError, TypeError):
            continue
    return False


def fetch_watchlist_calendar(requests_module, tickers, cutoff, fmp_key=''):
    """Read one day's agenda; date-only entries cannot confirm publication.

    Empty results indicate no verified events were returned, including when
    credentials or the provider are unavailable. They never prove absence.
    """
    if not fmp_key or not isinstance(cutoff, datetime) or cutoff.tzinfo is None:
        return []
    wanted = list(dict.fromkeys(symbol for value in (tickers or []) if (symbol := _symbol(value))))
    if not wanted:
        return []
    day = cutoff.astimezone(NY).date()
    url = 'https://financialmodelingprep.com/stable/earnings-calendar'
    try:
        rows = _fetch(requests_module, url, {'from': day.isoformat(), 'to': day.isoformat(), 'apikey': fmp_key})
        if not isinstance(rows, list):
            return []
        events = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker = _symbol(row.get('symbol'))
            if ticker not in wanted:
                continue
            raw_date = row.get('date')
            scheduled = _calendar_time(raw_date)
            if scheduled:
                event_day = scheduled.astimezone(NY).date()
            elif isinstance(raw_date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_date.strip()):
                try:
                    event_day = datetime.strptime(raw_date.strip(), '%Y-%m-%d').date()
                except ValueError:
                    continue
            else:
                continue
            if event_day != day:
                continue
            # lastUpdated is deliberately excluded: record maintenance is not
            # evidence of when a company released earnings.
            publication = None
            for field in ('publishedAt', 'published_at', 'publicationTime', 'publicationDateTime'):
                publication = _calendar_time(row.get(field))
                if publication:
                    break
            if publication is None and scheduled is not None:
                publication = scheduled
            published = bool(publication and publication.astimezone(NY).date() == day
                             and publication <= cutoff and _calendar_actual(row))
            event = {'ticker': ticker, 'title': 'Resultados publicados' if published else 'Resultados en agenda',
                     'status': 'published' if published else 'pending',
                     'published_at': publication.isoformat() if published else None,
                     'scheduled_date': day.isoformat(),
                     'scheduled_at': scheduled.isoformat() if scheduled else None,
                     'actual': None, 'consensus': None, 'previous': None,
                     'source': 'FMP · calendario de resultados', 'source_url': url,
                     'publication_kind': 'earnings_calendar',
                     'summary': ('La fuente incluye un dato realizado y una fecha y hora verificables hasta el corte. '
                                 'No se muestran cifras ni sorpresa porque la base contable del EPS no está documentada.'
                                 if published else
                                 'Fecha en agenda, sin hora verificada; no se confirma publicación.'
                                 if not publication else
                                 'Fecha en agenda; no se confirma publicación al corte. '
                                 'Una hora programada o un dato realizado sin publicación verificable no confirman el resultado.')}
            existing = events.get(ticker)
            # A duplicate calendar row cannot downgrade a verified release.
            if existing is None or (published and existing['status'] != 'published'):
                events[ticker] = event
        return [events[ticker] for ticker in wanted if ticker in events]
    except Exception:
        return []
