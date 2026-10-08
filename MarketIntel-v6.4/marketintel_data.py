"""Utilidades financieras e integraciones opcionales de MarketIntel.

Este módulo no depende de Flask ni de yfinance para que sus cálculos puedan
probarse por separado. Yahoo Finance sigue siendo la fuente base de la app;
FMP, SEC EDGAR y FRED se usan únicamente cuando están configurados.
"""

import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from xml.etree import ElementTree


_REMOTE_CACHE = {}
_MACRO_LAST_GOOD = {}


def _source_fetched_at(url, params=None):
    cached = _REMOTE_CACHE.get((url, tuple(sorted((params or {}).items()))))
    return datetime.fromtimestamp(cached[0], timezone.utc).isoformat() if cached else None


def _safe_error(exc):
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    return type(exc).__name__ + (f' HTTP {status}' if isinstance(status, int) else '')


def _shift_month(date_string, months):
    value = datetime.fromisoformat(date_string)
    index = value.year * 12 + value.month - 1 + months
    return f'{index // 12:04d}-{index % 12 + 1:02d}-01'


def _valid_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def first_number(mapping, *keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = _valid_number(mapping.get(key))
        if value is not None:
            return value
    return None


def normalize_dividend_yield(value):
    """Normaliza el dividend yield de Yahoo a porcentaje.

    Según la versión/campo, Yahoo puede entregar 0.0167 o 1.67 para 1.67%.
    """
    number = _valid_number(value)
    if number is None or number < 0:
        return None
    percent = number * 100 if number <= 1 else number
    return round(percent, 2)


def normalize_debt_to_equity(value):
    """Convierte el D/E de Yahoo (frecuentemente 388.9) a ratio 3.889x."""
    number = _valid_number(value)
    if number is None:
        return None
    ratio = number / 100 if abs(number) > 20 else number
    return round(ratio, 3)


def calculate_operating_expense_runway(total_cash, annual_operating_expenses):
    """Cash total ÷ (Operating Expenses anuales ÷ 12)."""
    cash = _valid_number(total_cash)
    expenses = _valid_number(annual_operating_expenses)
    if cash is None or expenses is None:
        return None, None
    monthly = abs(expenses) / 12
    if monthly <= 0:
        return None, None
    return round(monthly, 2), round(cash / monthly, 1)


def relative_difference(actual, expected):
    actual_number = _valid_number(actual)
    expected_number = _valid_number(expected)
    if actual_number is None or expected_number in (None, 0):
        return None
    return abs(actual_number - expected_number) / abs(expected_number) * 100


def build_identity_checks(data):
    """Comprueba identidades contables sin inventar valores faltantes."""
    checks = []

    def add(check_id, label, actual, expected, tolerance=5):
        difference = relative_difference(actual, expected)
        if difference is None:
            checks.append({
                'id': check_id, 'label': label, 'status': 'unavailable',
                'detail': 'No hay datos suficientes para verificarla.',
                'actual_value': _valid_number(actual),
                'expected_value': _valid_number(expected),
            })
            return
        checks.append({
            'id': check_id,
            'label': label,
            'status': 'pass' if difference <= tolerance else 'review',
            'difference_pct': round(difference, 2),
            'actual_value': _valid_number(actual),
            'expected_value': _valid_number(expected),
            'detail': (
                f'Diferencia {difference:.2f}% (tolerancia {tolerance}%).'
            ),
        })

    price = _valid_number(data.get('price'))
    shares = _valid_number(data.get('shares_outstanding'))
    add(
        'market_cap_identity',
        'Market Cap ≈ precio × acciones',
        data.get('market_cap'),
        price * shares if price is not None and shares is not None else None,
        4,
    )

    eps = _valid_number(data.get('eps'))
    add(
        'pe_identity',
        'P/E ≈ precio ÷ EPS TTM',
        data.get('pe'),
        price / eps if price is not None and eps not in (None, 0) else None,
        5,
    )

    revenue = _valid_number(data.get('revenue_ttm'))
    net_income = _valid_number(data.get('net_income_ttm'))
    add(
        'margin_identity',
        'Margen neto ≈ ganancia neta ÷ Revenue TTM',
        data.get('profit_margin'),
        (net_income / revenue * 100)
        if revenue not in (None, 0) and net_income is not None else None,
        5,
    )
    add(
        'revenue_ttm_identity',
        'Revenue TTM = suma de 4 trimestres',
        data.get('revenue_ttm'),
        data.get('revenue_ttm_calculated')
        if data.get('revenue_quarters_count') == 4 else None,
        0.1,
    )
    return checks


def build_cross_source_checks(data, fmp_metrics=None, sec_metrics=None):
    """Contrasta solo métricas comparables disponibles en más de una fuente."""
    checks = []
    fmp_metrics = fmp_metrics or {}
    sec_metrics = sec_metrics or {}

    def add(check_id, label, first, second, tolerance):
        difference = relative_difference(first, second)
        if difference is None:
            return
        checks.append({
            'id': check_id,
            'label': label,
            'status': 'pass' if difference <= tolerance else 'review',
            'difference_pct': round(difference, 2),
            'actual_value': _valid_number(first),
            'expected_value': _valid_number(second),
            'detail': (
                f'Diferencia entre fuentes {difference:.2f}% '
                f'(tolerancia {tolerance}%).'
            ),
        })

    add(
        'fmp_revenue',
        'Revenue TTM: Yahoo vs FMP',
        data.get('revenue_ttm'),
        fmp_metrics.get('revenue_ttm'),
        8,
    )
    add(
        'fmp_cash',
        'Cash: Yahoo vs FMP',
        data.get('total_cash'),
        fmp_metrics.get('cash'),
        12,
    )
    add(
        'fmp_debt',
        'Deuda total: Yahoo vs FMP',
        data.get('total_debt'),
        fmp_metrics.get('debt'),
        12,
    )
    fmp_margin = _valid_number(fmp_metrics.get('net_margin'))
    if fmp_margin is not None and abs(fmp_margin) <= 1:
        fmp_margin *= 100
    add(
        'fmp_net_margin',
        'Margen neto: Yahoo vs FMP',
        data.get('profit_margin'),
        fmp_margin,
        5,
    )
    sec_cash = sec_metrics.get('cash_latest')
    add(
        'sec_cash',
        'Cash: Yahoo vs último reporte SEC',
        data.get('total_cash'),
        sec_cash.get('value') if isinstance(sec_cash, dict) else None,
        12,
    )
    return checks


def _cached_json(requests_module, url, params=None, headers=None, ttl=900, timeout=8):
    key = (url, tuple(sorted((params or {}).items())))
    cached = _REMOTE_CACHE.get(key)
    if cached and time.time() - cached[0] < ttl:
        return cached[1]
    response = requests_module.get(
        url, params=params or {}, headers=headers or {}, timeout=timeout
    )
    response.raise_for_status()
    value = response.json()
    _REMOTE_CACHE[key] = (time.time(), value)
    return value


def _cached_json_retry(requests_module, url, params=None, headers=None, ttl=900, timeout=8, attempts=3):
    """Reintenta lecturas públicas breves para tolerar 429 y fallos transitorios."""
    last_error = None
    for attempt in range(max(1, attempts)):
        try:
            return _cached_json(
                requests_module, url, params=params, headers=headers,
                ttl=ttl, timeout=timeout,
            )
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25 * (attempt + 1))
    raise last_error


def _cached_text(requests_module, url, headers=None, ttl=300, timeout=12):
    """Lee una página pública con caché breve para fuentes sin API JSON."""
    key = (url, tuple(sorted((headers or {}).items())))
    cached = _REMOTE_CACHE.get(key)
    if cached and time.time() - cached[0] < ttl:
        return cached[1]
    response = requests_module.get(url, headers=headers or {}, timeout=timeout)
    response.raise_for_status()
    value = response.text
    _REMOTE_CACHE[key] = (time.time(), value)
    return value


def fetch_fmp_snapshot(requests_module, ticker, api_key):
    """Obtiene un contraste normalizado de FMP sin reemplazar Yahoo."""
    if not api_key:
        return {'configured': False, 'status': 'disabled', 'metrics': {}}
    base = 'https://financialmodelingprep.com/stable'
    endpoints = {
        'ratios': 'ratios-ttm',
        'metrics': 'key-metrics-ttm',
        'income': 'income-statement',
        'balance': 'balance-sheet-statement',
        'cashflow': 'cash-flow-statement',
        'estimates': 'analyst-estimates',
    }
    raw = {name: [] for name in endpoints}
    errors = []

    def load_endpoint(name, path):
        params = {'symbol': ticker, 'apikey': api_key}
        if name in {'income', 'balance', 'cashflow'}:
            params.update({'period': 'quarter', 'limit': 4})
        if name == 'estimates':
            params.update({'period': 'annual', 'limit': 4})
        result = _cached_json(
            requests_module, f'{base}/{path}', params=params, ttl=900
        )
        return name, result if isinstance(result, list) else []

    # Evita que seis endpoints retrasen la ficha uno detrás de otro.
    with ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
        futures = {
            executor.submit(load_endpoint, name, path): name
            for name, path in endpoints.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                _, result = future.result()
                raw[name] = result
            except Exception as exc:
                errors.append(f'{name}: {type(exc).__name__}')
                raw[name] = []

    ratios = raw['ratios'][0] if raw['ratios'] else {}
    metrics = raw['metrics'][0] if raw['metrics'] else {}
    income = raw['income']
    balance = raw['balance'][0] if raw['balance'] else {}
    cashflow = raw['cashflow'][0] if raw['cashflow'] else {}
    estimates = raw['estimates'][0] if raw['estimates'] else {}
    revenue_ttm = sum(
        value for value in (first_number(row, 'revenue') for row in income[:4])
        if value is not None
    ) if income else None
    if revenue_ttm == 0:
        revenue_ttm = None

    normalized = {
        'revenue_ttm': revenue_ttm,
        'net_income_ttm': (
            sum(value for value in (
                first_number(row, 'netIncome') for row in income[:4]
            ) if value is not None) if income else None
        ),
        'gross_margin': first_number(ratios, 'grossProfitMarginTTM', 'grossProfitMargin'),
        'ebitda_margin': first_number(ratios, 'ebitdaMarginTTM', 'ebitdaMargin'),
        'operating_margin': first_number(ratios, 'operatingProfitMarginTTM', 'operatingProfitMargin'),
        'net_margin': first_number(ratios, 'netProfitMarginTTM', 'netProfitMargin'),
        'roa': first_number(ratios, 'returnOnAssetsTTM', 'returnOnAssets'),
        'roe': first_number(ratios, 'returnOnEquityTTM', 'returnOnEquity'),
        'price_to_book': first_number(ratios, 'priceToBookRatioTTM', 'priceToBookRatio'),
        'peg_ratio': first_number(ratios, 'priceEarningsToGrowthRatioTTM', 'priceEarningsToGrowthRatio'),
        'enterprise_to_revenue': first_number(metrics, 'evToSalesTTM', 'evToSales'),
        'enterprise_to_ebitda': first_number(metrics, 'enterpriseValueOverEBITDATTM', 'enterpriseValueOverEBITDA'),
        'price_to_fcf': first_number(ratios, 'priceToFreeCashFlowsRatioTTM', 'priceToFreeCashFlowsRatio'),
        'current_ratio': first_number(ratios, 'currentRatioTTM', 'currentRatio'),
        'cash': first_number(balance, 'cashAndShortTermInvestments', 'cashAndCashEquivalents'),
        'debt': first_number(balance, 'totalDebt'),
        'free_cash_flow': first_number(cashflow, 'freeCashFlow'),
        'research_and_development': (
            sum(value for value in (
                first_number(row, 'researchAndDevelopmentExpenses')
                for row in income[:4]
            ) if value is not None) if income else None
        ),
        'estimated_revenue_next_year': first_number(
            estimates, 'estimatedRevenueAvg', 'estimatedRevenueHigh'
        ),
        'estimated_eps_next_year': first_number(
            estimates, 'estimatedEpsAvg', 'estimatedEpsHigh'
        ),
    }
    return {
        'configured': True,
        'status': 'ok' if any(value is not None for value in normalized.values()) else 'limited',
        'metrics': normalized,
        'errors': errors,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }


def _latest_sec_fact(company_facts, tags):
    facts = company_facts.get('facts', {}).get('us-gaap', {})
    candidates = []
    for tag in tags:
        units = facts.get(tag, {}).get('units', {})
        for unit_rows in units.values():
            for row in unit_rows:
                value = _valid_number(row.get('val'))
                if value is None:
                    continue
                candidates.append((
                    row.get('filed', ''),
                    row.get('end', ''),
                    value,
                    row.get('form', ''),
                ))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    filed, end, value, form = candidates[0]
    return {'value': value, 'period_end': end, 'filed': filed, 'form': form}


def fetch_sec_snapshot(requests_module, ticker, user_agent):
    """Consulta Company Facts de SEC para valores oficiales de compañías US."""
    if not user_agent or '@' not in user_agent:
        return {
            'configured': False, 'status': 'disabled', 'metrics': {},
            'note': 'Define SEC_USER_AGENT con nombre y correo.',
        }
    headers = {'User-Agent': user_agent, 'Accept-Encoding': 'gzip, deflate'}
    try:
        tickers = _cached_json(
            requests_module,
            'https://www.sec.gov/files/company_tickers.json',
            headers=headers,
            ttl=86400,
        )
        row = next(
            (item for item in tickers.values()
             if str(item.get('ticker', '')).upper() == ticker.upper()),
            None,
        )
        if not row:
            return {'configured': True, 'status': 'not_applicable', 'metrics': {}}
        cik = str(row['cik_str']).zfill(10)
        facts = _cached_json(
            requests_module,
            f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',
            headers=headers,
            ttl=3600,
        )
        metrics = {
            'revenue_latest': _latest_sec_fact(
                facts, ('RevenueFromContractWithCustomerExcludingAssessedTax',
                        'Revenues', 'SalesRevenueNet')
            ),
            'net_income_latest': _latest_sec_fact(facts, ('NetIncomeLoss',)),
            'shares_latest': _latest_sec_fact(
                facts, ('CommonStocksIncludingAdditionalPaidInCapitalMember',
                        'CommonStockSharesOutstanding')
            ),
            'cash_latest': _latest_sec_fact(
                facts, ('CashAndCashEquivalentsAtCarryingValue',
                        'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents')
            ),
        }
        return {
            'configured': True, 'status': 'ok', 'cik': cik,
            'company': facts.get('entityName'), 'metrics': metrics,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            'configured': True, 'status': 'error', 'metrics': {},
            'error': type(exc).__name__,
        }


FRED_SERIES = {
    'fed_upper': ('DFEDTARU', 'Tasa FED superior', 'percent'),
    'fed_lower': ('DFEDTARL', 'Tasa FED inferior', 'percent'),
    # Use the non-seasonally-adjusted headline CPI series so the displayed
    # YoY rate matches the CPI figure reported by BLS in its release.
    'cpi': ('CPIAUCNS', 'CPI general (NSA)', 'index'),
    'core_pce': ('PCEPILFE', 'Core PCE', 'index'),
    'unemployment': ('UNRATE', 'Desempleo', 'percent'),
    'payrolls': ('PAYEMS', 'Nóminas no agrícolas', 'thousands'),
    'gdp': ('GDPC1', 'PIB real', 'billions'),
    'treasury_10y': ('DGS10', 'Treasury 10Y', 'percent'),
    'pmi': ('NAPM', 'ISM manufacturero', 'index'),
    'consumer_sentiment': ('UMCSENT', 'Confianza del consumidor', 'index'),
}


def fetch_bls_cpi_snapshot(requests_module):
    """Obtiene el CPI headline NSA directamente desde la API pública de BLS."""
    year = datetime.now(timezone.utc).year
    result = _cached_json_retry(
        requests_module,
        'https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0',
        params={
            'startyear': str(year - 6),
            'endyear': str(year),
        },
        # Without a BLS key, the public API has a limited daily quota. FRED
        # mirrors the same NSA series and is checked separately below.
        ttl=3600,
        timeout=6,
        attempts=2,
    )
    rows = (((result.get('Results') or {}).get('series') or [{}])[0].get('data') or [])
    rows = [
        row for row in rows
        if str(row.get('period', '')).startswith('M')
        and row.get('period') != 'M13'
        and _valid_number(row.get('value')) is not None
    ]
    rows.sort(key=lambda row: (int(row.get('year', 0)), int(str(row.get('period', 'M00'))[1:])), reverse=True)
    if not rows:
        raise ValueError('BLS CPI: sin observaciones mensuales')
    period_values = {
        (int(row.get('year')), int(str(row.get('period'))[1:])): _valid_number(row.get('value'))
        for row in rows
    }
    latest = rows[0]
    latest_key = (int(latest.get('year')), int(str(latest.get('period'))[1:]))
    latest_value = period_values[latest_key]
    history = []
    for index, row in enumerate(rows):
        row_key = (int(row.get('year')), int(str(row.get('period'))[1:]))
        row_value = period_values[row_key]
        previous = period_values.get((row_key[0] - 1, row_key[1]))
        if previous in (None, 0):
            continue
        month = int(str(row.get('period'))[1:])
        history.append({
            'date': f"{row.get('year')}-{month:02d}-01",
            'value': round(row_value, 4),
            'display_value': round((row_value / previous - 1) * 100, 2),
            'display_unit': 'percent_yoy',
        })
    latest_month = int(str(latest.get('period'))[1:])
    current = latest_value
    prior = period_values.get((latest_key[0] - 1, latest_key[1]))
    return {
        'id': 'CUUR0000SA0',
        'label': 'CPI general (BLS NSA)',
        'unit': 'index',
        'value': current,
        'date': f"{latest.get('year')}-{latest_month:02d}-01",
        'display_value': round((current / prior - 1) * 100, 2) if prior not in (None, 0) else None,
        'display_unit': 'percent_yoy',
        'source': 'BLS',
        'source_url': 'https://data.bls.gov/timeseries/CUUR0000SA0',
        'fetched_at': _source_fetched_at('https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0', {'startyear': str(year-6), 'endyear': str(year)}),
        'published_at': None,
        'history': list(reversed(history[:60])),
    }


_MONTH_NAMES = (
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december'
)


def _published_month(month_name, year):
    """Require a real month/year whose observation period is not in the future."""
    month = _MONTH_NAMES.index(month_name.lower()) + 1
    date = f'{int(year):04d}-{month:02d}-01'
    if date > datetime.now(timezone.utc).date().isoformat():
        raise ValueError('Período de la fuente en el futuro.')
    return date


def _page_text(html):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', html))).strip()


def fetch_bea_core_pce_snapshot(requests_module):
    """BEA's published *year-on-year percent* is the fallback for Core PCE."""
    url = 'https://www.bea.gov/data/personal-consumption-expenditures-price-index-excluding-food-and-energy'
    text = _page_text(_cached_text(requests_module, url, ttl=300, timeout=7))
    entries = []
    for match in re.finditer(r'\b(' + '|'.join(_MONTH_NAMES) + r')\s+(20\d{2})\s+([+-]?\d+(?:\.\d+)?)\s*%', text, re.I):
        try:
            date = _published_month(match.group(1), match.group(2))
        except ValueError:
            continue
        value = float(match.group(3))
        if -20 <= value <= 30:
            entries.append({'date': date, 'display_value': value, 'display_unit': 'percent_yoy'})
    entries.sort(key=lambda row: row['date'], reverse=True)
    if not entries or text.lower().find('excluding food and energy') == -1:
        raise ValueError('BEA Core PCE: período o variación interanual no verificables')
    latest = entries[0]
    return {
        'id': 'BEA-CORE-PCE-YOY', 'label': 'Core PCE', 'unit': 'percent_yoy',
        'value': None, 'display_value': latest['display_value'],
        'display_unit': 'percent_yoy', 'date': latest['date'],
        'source': 'BEA', 'source_url': url,
        'fetched_at': _source_fetched_at(url), 'published_at': None,
        'history': list(reversed(entries[:60])),
        'warning': 'Variación interanual publicada por BEA; no se sustituye por el índice.',
    }


def fetch_michigan_sentiment_snapshot(requests_module):
    """Read the survey's current release with its actual period and revision status."""
    url = 'https://www.sca.isr.umich.edu/'
    text = _page_text(_cached_text(requests_module, url, ttl=300, timeout=7))
    heading = re.search(r'\b(Preliminary|Final)\s+Results\s+for\s+(' + '|'.join(_MONTH_NAMES) + r')\s+(20\d{2})\b', text, re.I)
    if not heading:
        raise ValueError('U. Michigan: mes, año o carácter preliminar no verificables')
    period = _published_month(heading.group(2), heading.group(3))
    if (datetime.now(timezone.utc).date() - datetime.fromisoformat(period).date()).days > 105:
        raise ValueError('U. Michigan: tabla principal anterior al plazo de la encuesta')
    index = re.search(r'\bIndex\s+of\s+Consumer\s+Sentiment\s+(\d+(?:\.\d+)?)\b', text[heading.end():heading.end()+1600], re.I)
    if not index or not 0 <= float(index.group(1)) <= 150:
        raise ValueError('U. Michigan: índice no verificable en la tabla principal')
    return {
        'id': 'UMICH-ICS', 'label': 'Confianza del consumidor', 'unit': 'index',
        'value': float(index.group(1)), 'display_value': float(index.group(1)),
        'display_unit': 'index', 'date': period,
        'source': 'U. Michigan', 'source_url': url,
        'fetched_at': _source_fetched_at(url), 'published_at': None, 'history': [],
        'revision': heading.group(1).lower(),
        'warning': 'Lectura preliminar; puede revisarse en la publicación final.' if heading.group(1).lower() == 'preliminary' else 'Lectura final de la encuesta.',
    }


def fetch_ism_snapshot(requests_module):
    """Obtiene el PMI manufacturero del informe oficial mensual de ISM."""
    now = datetime.now(timezone.utc)
    candidates = []
    failures = []
    for offset in range(0, 4):
        month = now.month - 1 - offset
        year = now.year
        while month <= 0:
            month += 12
            year -= 1
        month_name = _MONTH_NAMES[month - 1]
        candidates.append((year, month, month_name))

    for year, month, month_name in candidates:
        url = f'https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/{month_name}/'
        try:
            page = _cached_text(requests_module, url, timeout=5)
            page_text = _page_text(page).replace('®', '').replace('™', '')
            # Month-only URLs are reused by ISM. Require a matching report
            # month AND year in the document, not the guessed URL period.
            report = re.search(r'\b' + month_name + r'\s+' + str(year) + r'\s+(?:ISM\s+)?Manufacturing\s+PMI\s+Report\b', page_text, re.I)
            if not report:
                continue
            match = re.search(
                r'Manufacturing\s+PMI\s+at\s+([0-9]+(?:\.[0-9]+)?)\s*%',
                page_text[max(0,report.start()-180):report.start()], re.I,
            )
            if not match:
                match = re.search(
                    r'The\s+Manufacturing\s+PMI\s+registered\s+([0-9]+(?:\.[0-9]+)?)\s+percent',
                    page_text[report.end():report.end()+1600], re.I,
                )
            if not match:
                continue
            value = float(match.group(1))
            if not 0 <= value <= 100:
                continue
            return {
                'id': 'ISM-PMI',
                'label': 'ISM manufacturero',
                'unit': 'index',
                'value': value,
                'display_value': value,
                'display_unit': 'index',
                'date': f'{year}-{month:02d}-01',
                'source': 'ISM',
                'source_url': url,
                'fetched_at': _source_fetched_at(url),
                'published_at': None,
                'history': [],
            }
        except Exception as exc:
            failures.append(_safe_error(exc))
            continue
    raise ValueError('ISM-PMI: ' + ('; '.join(sorted(set(failures))) if failures else 'mes, año o PMI del informe no verificables'))


def fetch_fred_snapshot(requests_module, api_key):
    series = {}
    errors = []

    def fetch_one(entry):
        key, (series_id, label, unit) = entry
        primary_error = None
        primary = None
        bea_primary = None
        try:
            if key == 'consumer_sentiment':
                try:
                    primary = fetch_michigan_sentiment_snapshot(requests_module)
                    if not api_key:
                        return key, primary, None
                except Exception as exc:
                    primary_error = 'U. Michigan: ' + _safe_error(exc)
            if key == 'cpi':
                try:
                    primary = fetch_bls_cpi_snapshot(requests_module)
                    if not api_key:
                        return key, primary, None
                except Exception as exc:
                    primary_error = 'BLS: ' + _safe_error(exc)
            if key == 'pmi':
                try:
                    return key, fetch_ism_snapshot(requests_module), None
                except Exception as exc:
                    return key, None, str(exc) if isinstance(exc, ValueError) else 'ISM-PMI: '+_safe_error(exc)
            if key == 'core_pce':
                try:
                    bea_primary = fetch_bea_core_pce_snapshot(requests_module)
                    if not api_key:
                        return key, bea_primary, None
                except Exception as exc:
                    primary_error = 'BEA: '+_safe_error(exc)
            if not api_key:
                return key, None, f'{series_id}: FRED sin configurar' + ('; '+primary_error if primary_error else '')
            params = {
                'series_id': series_id,
                'api_key': api_key,
                'file_type': 'json',
                'sort_order': 'desc',
                # 73 observaciones permiten calcular variaciones interanuales
                # y mostrar alrededor de cinco años en las gráficas mensuales.
                'limit': 73,
            }
            try:
                result = _cached_json_retry(requests_module, 'https://api.stlouisfed.org/fred/series/observations', params=params, ttl=300, timeout=6, attempts=2)
            except Exception:
                if primary:
                    return key, primary, None
                if bea_primary:
                    bea_primary['warning'] = 'FRED no respondió. ' + bea_primary['warning']
                    return key, bea_primary, None
                raise
            observations = result.get('observations') or []
            # FRED puede devolver primero una observación con valor "." en
            # días sin publicación. Usar esa fila dejaba fecha visible pero
            # valor vacío, aunque sí existiera un dato válido inmediatamente
            # después.
            valid_observations = [
                (row, _valid_number(row.get('value')))
                for row in observations
                if _valid_number(row.get('value')) is not None
            ]
            if not valid_observations:
                if primary:
                    return key, primary, None
                if bea_primary:
                    return key, bea_primary, None
                return key, None, f'{series_id}: sin valores numéricos'
            # An observation period cannot be later than the date of consultation.
            today = datetime.now(timezone.utc).date().isoformat()
            valid_observations = [pair for pair in valid_observations if pair[0].get('date', '') <= today]
            if not valid_observations:
                return key, primary or bea_primary, None if primary or bea_primary else f'{series_id}: sin períodos válidos'
            valid_observations.sort(key=lambda pair: pair[0]['date'], reverse=True)
            observation, value = valid_observations[0] if valid_observations else ({}, None)
            item = {
                'id': series_id, 'label': label, 'unit': unit, 'source': 'FRED',
                'value': value, 'date': observation.get('date'),
                'source_url': 'https://fred.stlouisfed.org/series/'+series_id,
                'fetched_at': _source_fetched_at('https://api.stlouisfed.org/fred/series/observations', params),
                'published_at': None,
            }
            if primary_error:
                if key == 'cpi':
                    item['warning'] = primary_error+'; respaldo explícito con la misma serie CPI NSA en FRED'
                elif key == 'consumer_sentiment':
                    item['warning'] = primary_error+'; FRED publica UMCSENT con un mes de retraso respecto a la encuesta.'
            if primary:
                if primary.get('date', '') >= item.get('date', ''):
                    return key, primary, None
                item['warning'] = ('FRED tiene un período más reciente que BLS; se muestra CPI NSA de FRED.'
                                   if key == 'cpi' else 'FRED tiene un período más reciente que la página de U. Michigan; verificar la revisión.')
            by_period = {row['date']: row_value for row, row_value in valid_observations}
            numeric = [row_value for _, row_value in valid_observations]
            previous_year = by_period.get(_shift_month(item['date'], -12))
            if key in {'cpi', 'core_pce', 'gdp'}:
                item['display_value'] = round((value / previous_year - 1) * 100, 2) if previous_year not in (None, 0) else None
                item['display_unit'] = 'percent_yoy'
            elif key == 'payrolls':
                prior_month = by_period.get(_shift_month(item['date'], -1))
                item['display_value'] = round(value - prior_month, 0) if prior_month is not None else None
                item['display_unit'] = 'change_thousands'
            else:
                item['display_value'] = value
                item['display_unit'] = unit

            if bea_primary and (
                bea_primary.get('date', '') > item.get('date', '')
                or item.get('display_value') is None
            ):
                bea_primary['warning'] = 'BEA publicó un período más reciente que FRED. ' + bea_primary['warning']
                return key, bea_primary, None

            history = []
            for index, (row, row_value) in enumerate(valid_observations):
                display_value = row_value
                display_unit = unit
                if key in {'cpi', 'core_pce', 'gdp'}:
                    previous = by_period.get(_shift_month(row['date'], -12))
                    if previous in (None, 0):
                        continue
                    display_value = (row_value / previous - 1) * 100
                    display_unit = 'percent_yoy'
                elif key == 'payrolls':
                    previous = by_period.get(_shift_month(row['date'], -1))
                    if previous is None:
                        continue
                    display_value = row_value - previous
                    display_unit = 'change_thousands'
                history.append({
                    'date': row.get('date'),
                    'value': round(row_value, 4),
                    'display_value': round(display_value, 2),
                    'display_unit': display_unit,
                })
            item['history'] = list(reversed(history[:60]))
            return key, item, None
        except Exception as exc:
            return key, None, f'{series_id}: {_safe_error(exc)}' + ('; '+primary_error if primary_error else '')

    # Las series son independientes. Consultarlas en paralelo evita que la
    # primera apertura de Pulso macro tarde la suma de ocho solicitudes.
    with ThreadPoolExecutor(max_workers=min(8, len(FRED_SERIES))) as executor:
        futures = [
            executor.submit(fetch_one, entry)
            for entry in FRED_SERIES.items()
        ]
        for future in as_completed(futures):
            key, item, error = future.result()
            if item is not None:
                item['status'] = 'ok' if item.get('display_value') is not None else 'unavailable'
                if item['status'] == 'unavailable':
                    item['error'] = 'Falta el período de comparación; no se calcula una variación aproximada.'
                previous = _MACRO_LAST_GOOD.get(key)
                if (item['status'] == 'ok' and previous and previous.get('date')
                    and (item.get('date', '') < previous['date'] or (
                        item.get('date') == previous['date']
                        and previous.get('revision') == 'final'
                        and item.get('revision') != 'final'
                    ))):
                    item = dict(previous, status='stale', warning='La fuente devolvió una lectura anterior a la última verificada; se mantiene la anterior sin contarla como actual.')
                series[key] = item
                if item['status'] == 'ok':
                    _MACRO_LAST_GOOD[key] = dict(item)
            if error:
                errors.append(error)

    # Mantener todas las tarjetas visibles evita confundir un fallo temporal
    # de una serie con un problema de renderizado. Nunca se inventa un valor.
    for key, (series_id, label, unit) in FRED_SERIES.items():
        if key not in series:
            error_prefix = 'ISM-PMI' if key == 'pmi' else series_id
            matching_error = next((error for error in errors if error.startswith(f'{error_prefix}:')), None)
            if key in _MACRO_LAST_GOOD:
                series[key] = dict(_MACRO_LAST_GOOD[key], status='stale', warning=matching_error or 'La fuente no respondió; se conserva la última lectura, sin marcarla como nueva.')
                continue
            series[key] = {
                'id': series_id,
                'label': label,
                'unit': unit,
                'source': 'ISM' if key == 'pmi' else 'BLS / FRED' if key == 'cpi' else 'FRED',
                'value': None,
                'display_value': None,
                'display_unit': unit,
                'date': None,
                'history': [],
                'status': 'unavailable',
                'error': matching_error or 'No disponible en este intento',
            }

    now = datetime.now(timezone.utc)
    # Observation dates represent the FIRST day of the reference period,
    # not their publication dates. Core PCE is released late the next month;
    # FRED's Michigan series is also delayed at the publisher's request.
    # The quarter's observation date is its FIRST day. Q2 (April 1) is still
    # the latest published GDP until the Q3 advance estimate in late October.
    max_age = {'fed_upper': 5, 'fed_lower': 5, 'treasury_10y': 10,
               'gdp': 240, 'core_pce': 105, 'consumer_sentiment': 105}
    for key, item in series.items():
        item.setdefault('published_at', None)
        if item.get('date'):
            try:
                days = (now.date()-datetime.fromisoformat(item['date']).date()).days
                if days > max_age.get(key, 75) or days < 0:
                    item['period_warning'] = 'Período antiguo o futuro: comprobar con la fuente. No equivale a una publicación de hoy.'
            except ValueError:
                item['period_warning'] = 'Período no verificable.'
    valid = sum(item.get('status') == 'ok' and not item.get('period_warning') for item in series.values())
    return {
        'configured': bool(api_key),
        'status': 'ok' if valid == len(series) else 'partial' if valid else 'error',
        'series': series,
        'errors': errors,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }


# Series complementarias para el sesgo diario. Se mantienen separadas del
# panel macro principal porque son señales de mercado, no indicadores de
# actividad económica de publicación mensual.
FRED_SENTIMENT_SERIES = {
    'credit_spread': ('BAMLH0A0HYM2', 'High Yield OAS', 'percent'),
    'yield_curve': ('T10Y2Y', 'Curva 10Y–2Y', 'percent'),
}


def fetch_fred_sentiment(requests_module, api_key):
    """Carga crédito y curva de tipos para el indicador de dirección diaria.

    Estas series no predicen el mercado por sí solas. Sirven para comprobar si
    el movimiento de los precios está acompañado por una lectura razonable de
    riesgo financiero. Si FRED no está disponible, el consumidor puede
    recalcular el resultado con las señales de precios que sí existan.
    """
    if not api_key:
        return {'configured': False, 'status': 'disabled', 'series': {}, 'errors': []}

    series = {}
    errors = []

    def fetch_one(entry):
        key, (series_id, label, unit) = entry
        try:
            result = _cached_json(
                requests_module,
                'https://api.stlouisfed.org/fred/series/observations',
                params={
                    'series_id': series_id,
                    'api_key': api_key,
                    'file_type': 'json',
                    'sort_order': 'desc',
                    'limit': 400,
                },
                ttl=900,
            )
            observations = result.get('observations') or []
            clean_observations = []
            for row in observations:
                value = _valid_number(row.get('value'))
                if value is not None:
                    clean_observations.append({
                        'date': row.get('date'),
                        'value': round(value, 6),
                    })
            if not clean_observations:
                return key, None, f'{series_id}: sin observaciones'
            current = clean_observations[0]
            return key, {
                'id': series_id,
                'label': label,
                'unit': unit,
                'value': current['value'],
                'date': current.get('date'),
                # La interfaz y el cálculo necesitan la serie cronológica en
                # orden ascendente para percentiles y tooltips.
                'history': list(reversed(clean_observations[:260])),
            }, None
        except Exception as exc:
            return key, None, f'{series_id}: {type(exc).__name__}'

    with ThreadPoolExecutor(max_workers=len(FRED_SENTIMENT_SERIES)) as executor:
        futures = [
            executor.submit(fetch_one, entry)
            for entry in FRED_SENTIMENT_SERIES.items()
        ]
        for future in as_completed(futures):
            key, item, error = future.result()
            if item is not None:
                series[key] = item
            if error:
                errors.append(error)

    return {
        'configured': True,
        'status': 'ok' if series else 'error',
        'series': series,
        'errors': errors,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }


def _normalize_yahoo_news(rows):
    articles = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get('title') or '').strip()
        link = str(row.get('link') or '').strip()
        if not title or not link.startswith(('https://', 'http://')):
            continue
        timestamp = _valid_number(row.get('providerPublishTime'))
        published_at = None
        if timestamp is not None:
            published_at = datetime.fromtimestamp(
                timestamp, tz=timezone.utc
            ).isoformat()
        articles.append({
            'id': row.get('uuid'),
            'title': title,
            'publisher': str(row.get('publisher') or 'Yahoo Finance'),
            'url': link,
            'published_at': published_at,
            'related_tickers': [
                str(value).upper() for value in (row.get('relatedTickers') or [])
                if value
            ][:6],
        })
    return articles


def _fetch_google_news_rss(requests_module, query, count):
    """Respaldo sin clave cuando Yahoo no entrega resultados."""
    response = requests_module.get(
        'https://news.google.com/rss/search',
        params={
            'q': f'{query} when:7d',
            'hl': 'en-US',
            'gl': 'US',
            'ceid': 'US:en',
        },
        headers={'User-Agent': 'Mozilla/5.0 MarketIntel/1.0'},
        timeout=10,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.text)
    articles = []
    for item in root.findall('./channel/item')[:max(1, min(int(count), 20))]:
        title = str(item.findtext('title') or '').strip()
        link = str(item.findtext('link') or '').strip()
        if not title or not link.startswith(('https://', 'http://')):
            continue
        published_at = None
        raw_date = item.findtext('pubDate')
        if raw_date:
            try:
                published_at = parsedate_to_datetime(raw_date).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, OverflowError):
                published_at = None
        source = item.findtext('{http://news.google.com/mrss}source') or item.findtext('source')
        articles.append({
            'id': link,
            'title': title,
            'publisher': str(source or 'Google News'),
            'url': link,
            'published_at': published_at,
            'related_tickers': [],
        })
    return articles


def fetch_market_news(requests_module, query='stock market', count=12):
    """Obtiene titulares actuales sin requerir una API key adicional.

    Yahoo Finance es la fuente principal. Se prueba query1 y query2 porque
    Yahoo puede enrutar temporalmente uno de sus hosts de búsqueda de forma
    distinta. Google News RSS queda como respaldo para no mostrar una pantalla
    vacía durante una incidencia temporal de Yahoo.
    """
    safe_query = str(query or 'stock market').strip()[:80]
    news_count = max(1, min(int(count), 20))
    errors = []
    for host in ('query1', 'query2'):
        try:
            result = _cached_json(
                requests_module,
                f'https://{host}.finance.yahoo.com/v1/finance/search',
                params={
                    'q': safe_query,
                    'quotesCount': 0,
                    'newsCount': news_count,
                    'enableFuzzyQuery': 'false',
                },
                headers={
                    'User-Agent': 'Mozilla/5.0 MarketIntel/1.0',
                    'Accept': 'application/json',
                },
                ttl=300,
                timeout=10,
            )
            articles = _normalize_yahoo_news(result.get('news'))
            if articles:
                return {
                    'status': 'ok',
                    'source': 'Yahoo Finance',
                    'query': safe_query,
                    'articles': articles[:news_count],
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                }
        except Exception as exc:
            errors.append(f'{host}: {type(exc).__name__}')

    try:
        articles = _fetch_google_news_rss(requests_module, safe_query, news_count)
        if articles:
            return {
                'status': 'ok',
                'source': 'Google News RSS (respaldo)',
                'query': safe_query,
                'articles': articles,
                'fallback': True,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }
    except Exception as exc:
        errors.append(f'google-rss: {type(exc).__name__}')

    return {
        'status': 'error' if errors else 'empty',
        'source': 'Yahoo Finance',
        'query': safe_query,
        'articles': [],
        'errors': errors,
        'error': 'No se pudieron obtener titulares actuales.' if errors else None,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
