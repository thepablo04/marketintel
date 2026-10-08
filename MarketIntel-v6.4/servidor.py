from flask import Flask, jsonify, send_file, request as flask_request
from flask_cors import CORS
import yfinance as yf
import traceback
import os
import math
import re
import statistics
import time
import secrets
import threading
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime, timezone

from marketintel_storage import LocalStore
from marketintel_pulse import PulseService, weighted, market_session

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name('.env'))
except ImportError:
    pass

try:
    import requests as http_req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from marketintel_data import (
    build_cross_source_checks,
    build_identity_checks,
    calculate_operating_expense_runway,
    fetch_fmp_snapshot,
    fetch_fred_snapshot,
    fetch_fred_sentiment,
    fetch_market_news,
    fetch_sec_snapshot,
    normalize_debt_to_equity,
    normalize_dividend_yield,
)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8_500_000
APP_VERSION = '6.4'
INSTALL_ID = hashlib.sha256(str(Path(__file__).resolve().parent).encode()).hexdigest()[:16]
LOCAL_TOKEN = secrets.token_urlsafe(32)
local_store = LocalStore()
_local_origins = 'http://localhost:3000,http://localhost:5000,http://localhost:5050,http://localhost:5500,http://127.0.0.1:3000,http://127.0.0.1:5000,http://127.0.0.1:5050,http://127.0.0.1:5500'
ALLOWED_ORIGINS = [x.strip() for x in os.environ.get('MARKETINTEL_ALLOWED_ORIGINS', _local_origins).split(',') if x.strip()]
CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}})
TICKER_RE = re.compile(r'^[A-Z0-9.^=-]{1,15}$')
CACHE_TTL = int(os.environ.get('MARKETINTEL_CACHE_TTL', '120'))
FMP_API_KEY = os.environ.get('FMP_API_KEY', '').strip()
FRED_API_KEY = os.environ.get('FRED_API_KEY', '').strip()
SEC_USER_AGENT = os.environ.get('SEC_USER_AGENT', '').strip()
_CACHE = {}
_YAHOO_DOWNLOAD_LOCK = threading.RLock()
_MACRO_LOCK = threading.Lock()
_MACRO_RESULT = None
_MACRO_AT = 0


def yahoo_download(*args, **kwargs):
    # Older yfinance versions share a process-global download buffer.
    with _YAHOO_DOWNLOAD_LOCK:
        return yf.download(*args, **kwargs)

CHATBOT_SYSTEM = """Eres MarketBot, el asistente financiero de MarketIntel. Especializado en value investing y análisis de mercados bursátiles.

Los 7 principios del usuario:
1. Price Target — upside ≥20% sobre el precio actual
2. Crecimiento en ventas — mínimo +20% YoY
3. SMA 200 — precio por debajo de la media = descuento/oportunidad de compra
4. Conference Call — revisar guidance del CEO, tono y márgenes
5. P/E Ratio — razonable (<50x trailing)
6. Beta/Volatilidad — Beta <2.5, ATR manejable
7. Williams %R — zona de sobreventa en semanal (−80 a −100)

Indicadores macro que conoces: FED rates, CPI, Core PCE, NFP/Desempleo, PIB/GDP, ISM PMI, Confianza del Consumidor.
Análisis fundamental: EPS (TTM y Forward), P/E, Graham Number (√22.5×EPS×BVPS), Graham formula (EPS×(8.5+2g)), Fair Value (EPS Fwd×15), runway de caja.
Análisis técnico: SMA/EMA, ATR, Beta, Williams %R, Golden Cross, Death Cross, soporte/resistencia.

Responde siempre en español. Sé conciso pero completo. No des recomendaciones directas de compra/venta — da análisis objetivo y educativo.
Cuando te pregunten por una acción específica, menciona cuáles de los 7 principios podrían cumplirse o fallar basándote en los datos disponibles."""

def clean(val):
    if val is None:
        return None
    try:
        if math.isnan(float(val)) or math.isinf(float(val)):
            return None
    except (TypeError, ValueError):
        pass
    return val

def clean_list(lst):
    if lst is None:
        return None
    return [clean(v) for v in lst]

def latest_statement_value(statement, row_names):
    """Obtiene el valor más reciente disponible de una fila financiera."""
    try:
        if statement is None or statement.empty:
            return None
        for row_name in row_names:
            if row_name in statement.index:
                values = statement.loc[row_name].dropna()
                if len(values):
                    value = clean(values.iloc[0])
                    return float(value) if value is not None else None
    except Exception:
        pass
    return None

def normalize_ticker(raw):
    ticker = str(raw or '').upper().strip()
    if not TICKER_RE.fullmatch(ticker):
        raise ValueError('Ticker inválido')
    return ticker

def cache_get(key, ttl=None):
    item = _CACHE.get(key)
    if not item: return None
    created, value = item
    if time.time() - created > (CACHE_TTL if ttl is None else ttl):
        _CACHE.pop(key, None)
        return None
    return value

def cache_set(key, value):
    _CACHE[key] = (time.time(), value)
    if len(_CACHE) > 300:
        for old_key, _ in sorted(_CACHE.items(), key=lambda x: x[1][0])[:50]:
            _CACHE.pop(old_key, None)

def historical_pe_series(t, period='5y', interval='3mo'):
    result = []
    try:
        fin = t.financials
        if fin is None or fin.empty: return result
        row = next((name for name in ('Diluted EPS', 'Basic EPS') if name in fin.index), None)
        if not row: return result
        eps_by_year = {}
        for col, value in fin.loc[row].dropna().items():
            try:
                year = int(getattr(col, 'year', str(col)[:4])); eps = float(value)
                if eps > 0: eps_by_year[year] = eps
            except (TypeError, ValueError): pass
        hist = t.history(period=period, interval=interval)
        if hist is None or hist.empty: return result
        for date, price in hist['Close'].dropna().items():
            eligible = [year for year in eps_by_year if year <= int(date.year)]
            if not eligible: continue
            fiscal_year = max(eligible); eps = eps_by_year[fiscal_year]; pe = float(price) / eps
            if 0 < pe < 500:
                result.append({'period': str(date)[:7], 'pe': round(pe, 1), 'price': round(float(price), 2), 'eps': round(eps, 2), 'fiscal_year': fiscal_year})
    except Exception: pass
    return result

@app.route('/')
def home():
    return send_file(Path(__file__).with_name('index.html'))


@app.after_request
def response_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if not flask_request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.before_request
def protect_local_storage():
    if not flask_request.path.startswith(('/local-', '/signal-history')):
        return None
    hostname = urlsplit(flask_request.host_url).hostname
    if flask_request.remote_addr not in ('127.0.0.1', '::1') or hostname not in ('localhost', '127.0.0.1', '::1'):
        return jsonify({'error': 'Los respaldos solo son accesibles desde esta PC.'}), 403
    origin = flask_request.headers.get('Origin')
    if origin and origin.rstrip('/') != flask_request.host_url.rstrip('/'):
        return jsonify({'error': 'Origen no permitido.'}), 403
    if flask_request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return jsonify({'error': 'Solicitud externa bloqueada.'}), 403
    if flask_request.path != '/local-state' and not secrets.compare_digest(flask_request.headers.get('X-MarketIntel-Token', ''), LOCAL_TOKEN):
        return jsonify({'error': 'Vuelve a cargar la página para acceder al respaldo local.'}), 403


@app.route('/local-state')
def local_state():
    return jsonify({'token': LOCAL_TOKEN, 'version': APP_VERSION, 'directory': str(local_store.directory)})


@app.route('/local-backups', methods=['GET', 'POST'])
def local_backups():
    try:
        if flask_request.method == 'GET':
            before = flask_request.args.get('before')
            if before is not None and (not before.isdigit() or len(before) > 18 or int(before) < 1):
                raise ValueError('Página de respaldos inválida.')
            rows = local_store.list_backups(int(before) if before is not None else None)
            return jsonify({'backups': rows, 'next_before': rows[-1]['id'] if len(rows) == 100 else None})
        body = flask_request.get_json(silent=True) or {}
        return jsonify(local_store.save_backup(body.get('snapshot'), body.get('profile'), body.get('reason', 'automatic')))
    except (ValueError, TypeError) as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception:
        return jsonify({'error': 'No se pudo acceder al respaldo local. Comprueba espacio y permisos de la carpeta.'}), 503


@app.route('/local-backups/<int:backup_id>')
def read_local_backup(backup_id):
    try:
        return jsonify(local_store.read_backup(backup_id))
    except LookupError:
        return jsonify({'error': 'No existe esa copia.'}), 404
    except Exception:
        return jsonify({'error': 'No se pudo leer la copia local.'}), 503


@app.route('/signal-history')
def signal_history():
    try:
        return jsonify(local_store.signal_history(complete=True))
    except Exception:
        return jsonify({'error': 'No se pudo leer el seguimiento local.'}), 503

@app.route('/health')
def health():
    return jsonify({
        'status':'ok',
        'service':'MarketIntel',
        'version': APP_VERSION,
        'install_id': INSTALL_ID,
        'source':'Yahoo Finance',
        'integrations': {
            'fmp': bool(FMP_API_KEY),
            'fred': bool(FRED_API_KEY),
            'sec_edgar': bool(SEC_USER_AGENT and '@' in SEC_USER_AGENT),
            'yahoo_news': True,
            'market_sentiment': True,
        },
        'cache_ttl_seconds':CACHE_TTL,
        'server_time':datetime.now(timezone.utc).isoformat(),
    })

@app.route('/meta')
def meta():
    return jsonify({
        'app':'MarketIntel',
        'version': APP_VERSION,
        'data_source':'Yahoo Finance',
        'data_delay_note':'La disponibilidad y el retraso dependen del mercado y de Yahoo Finance.',
        'integrations': {
            'fmp': {'configured': bool(FMP_API_KEY), 'purpose': 'Contraste de fundamentales, ratios y estimaciones'},
            'fred': {'configured': bool(FRED_API_KEY), 'purpose': 'Indicadores macroeconómicos oficiales'},
            'sec_edgar': {'configured': bool(SEC_USER_AGENT and '@' in SEC_USER_AGENT), 'purpose': 'Verificación de reportes oficiales US'},
            'yahoo_news': {'configured': True, 'purpose': 'Titulares financieros recientes'},
            'market_sentiment': {'configured': True, 'purpose': 'Dirección diaria con precios, volatilidad, amplitud y riesgo macro'},
        },
        'cache_ttl_seconds':CACHE_TTL,
        'server_time':datetime.now(timezone.utc).isoformat(),
    })


@app.route('/macro')
def get_macro():
    global _MACRO_RESULT, _MACRO_AT
    if not HAS_REQUESTS:
        return jsonify({
            'configured': False,
            'status': 'unavailable',
            'series': {},
            'error': 'Instala requests para usar FRED.',
        })
    with _MACRO_LOCK:
        if _MACRO_RESULT is None or time.monotonic() - _MACRO_AT >= 60:
            _MACRO_RESULT = fetch_fred_snapshot(http_req, FRED_API_KEY)
            _MACRO_AT = time.monotonic()
        response = jsonify(_MACRO_RESULT)
        response.headers['Cache-Control'] = 'no-store'
        return response


@app.route('/news')
def get_news():
    if not HAS_REQUESTS:
        return jsonify({
            'status': 'unavailable',
            'source': 'Yahoo Finance',
            'articles': [],
            'error': 'Instala requests para cargar noticias.',
        })
    query = str(flask_request.args.get('q', 'stock market') or '').strip()
    if not query:
        query = 'stock market'
    if len(query) > 80:
        return jsonify({'error': 'Consulta demasiado larga.'}), 400
    return jsonify(fetch_market_news(http_req, query=query, count=12))


# El pulso diario usa ETFs líquidos y una serie de crédito de FRED. No intenta
# adivinar el precio de una acción concreta: estima si el entorno general está
# acompañando a los compradores o a los vendedores.
SENTIMENT_CORE_TICKERS = ('SPY', 'QQQ', 'IWM', 'HYG', '^VIX')
SENTIMENT_BREADTH_TICKERS = (
    'XLK', 'XLF', 'XLE', 'XLI', 'XLY', 'XLP',
    'XLV', 'XLC', 'XLU', 'XLRE', 'XLB',
)
SENTIMENT_TICKERS = tuple(dict.fromkeys(
    SENTIMENT_CORE_TICKERS + SENTIMENT_BREADTH_TICKERS
))


def _clip(value, low=0.0, high=100.0):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return None


def _sentiment_mean(values):
    clean_values = [float(value) for value in values if value is not None]
    return sum(clean_values) / len(clean_values) if clean_values else None


def _bounded_signal(value, scale):
    """Convierte una variación en una señal 0–100 sin permitir extremos."""
    try:
        if value is None or not scale:
            return None
        return _clip(50 + (float(value) / float(scale)) * 50)
    except (TypeError, ValueError):
        return None


def _percentile(values, current):
    clean_values = []
    for value in values or []:
        try:
            number = float(value)
            if math.isfinite(number):
                clean_values.append(number)
        except (TypeError, ValueError):
            continue
    try:
        current_number = float(current)
    except (TypeError, ValueError):
        return None
    if not clean_values:
        return None
    if len(clean_values) == 1:
        return 50.0
    return _clip((sum(value < current_number for value in clean_values)
                  + 0.5 * sum(value == current_number for value in clean_values))
                 / len(clean_values) * 100)


def _download_sentiment_histories():
    """Descarga un año de cierres para todas las señales de una sola vez."""
    if not HAS_PANDAS:
        return {}, [], None
    try:
        frame = yahoo_download(
            ' '.join(SENTIMENT_TICKERS),
            period='1y',
            interval='1d',
            auto_adjust=True,
            progress=False,
            threads=False,
            group_by='column',
        )
        if frame is None or frame.empty:
            return {}, ['Yahoo: historial vacío'], None

        close_frame = None
        if isinstance(frame.columns, pd.MultiIndex):
            for level in range(frame.columns.nlevels):
                if 'Close' in frame.columns.get_level_values(level):
                    close_frame = frame.xs('Close', level=level, axis=1)
                    break
        elif 'Close' in frame.columns:
            close_frame = frame['Close']
        if close_frame is None:
            return {}, ['Yahoo: no se encontró Close'], None

        histories = {}
        for ticker in SENTIMENT_TICKERS:
            series = None
            if isinstance(close_frame, pd.Series):
                # Sólo ocurre si Yahoo reduce la respuesta a un ticker.
                series = close_frame if len(SENTIMENT_TICKERS) == 1 else None
            else:
                for column in close_frame.columns:
                    labels = list(column) if isinstance(column, tuple) else [str(column)]
                    if ticker in labels:
                        series = close_frame[column]
                        break
            if series is None:
                continue
            values = []
            for value in series.tolist():
                try:
                    number = float(value)
                    if math.isfinite(number):
                        values.append(number)
                except (TypeError, ValueError):
                    continue
            if values:
                histories[ticker] = values[-260:]

        last_date = None
        try:
            last_date = str(frame.index[-1].date())
        except Exception:
            pass
        errors = [] if histories else ['Yahoo: no se pudieron extraer cierres']
        return histories, errors, last_date
    except Exception as exc:
        return {}, [f'Yahoo: {type(exc).__name__}'], None


def _series_metrics(values, live_price=None, live_change_pct=None):
    if not values or len(values) < 2:
        return None
    try:
        closes = [float(value) for value in values if math.isfinite(float(value))]
    except (TypeError, ValueError):
        return None
    if len(closes) < 2:
        return None
    current = None
    try:
        if live_price is not None and float(live_price) > 0:
            current = float(live_price)
    except (TypeError, ValueError):
        pass
    if current is None:
        current = closes[-1]

    def return_over(period):
        if len(closes) <= period or closes[-(period + 1)] <= 0:
            return None
        return current / closes[-(period + 1)] - 1

    def sma(period):
        if len(closes) < period:
            return None
        window = closes[-period:]
        return sum(window) / len(window)

    previous = closes[-2]
    one_day = current / previous - 1 if previous > 0 else None
    if live_change_pct is not None:
        try:
            one_day = float(live_change_pct) / 100
        except (TypeError, ValueError):
            pass
    sma_20 = sma(20)
    sma_50 = sma(50)
    sma_200 = sma(200)
    return {
        'price': round(current, 4),
        'ret_1d': one_day,
        'ret_5d': return_over(5),
        'ret_20d': return_over(20),
        'sma_20': sma_20,
        'sma_50': sma_50,
        'sma_200': sma_200,
        'distance_20': current / sma_20 - 1 if sma_20 else None,
        'distance_50': current / sma_50 - 1 if sma_50 else None,
        'distance_200': current / sma_200 - 1 if sma_200 else None,
        'history': closes,
    }


def _build_sentiment_component(key, label, weight, score, detail, sample=None):
    score = round(float(score), 1) if score is not None else None
    state = 'unavailable'
    if score is not None:
        state = 'bullish' if score >= 60 else 'bearish' if score <= 40 else 'neutral'
    return {
        'key': key,
        'label': label,
        'weight': weight,
        'score': score,
        'state': state,
        'available': score is not None,
        'detail': detail,
        'sample': sample,
    }


def _market_session():
    return market_session()


def build_market_context(histories, fred, last_history_date, errors):
    """Contexto de cierres, explícitamente separado de la sesión intradía."""
    metrics = {}
    for ticker, values in histories.items():
        metrics[ticker] = _series_metrics(values)

    components = []

    trend_scores = []
    for ticker in ('SPY', 'QQQ', 'IWM'):
        item = metrics.get(ticker)
        if not item:
            continue
        signals = [
            _bounded_signal(item.get('ret_5d'), 0.04),
            _bounded_signal(item.get('ret_20d'), 0.12),
            _bounded_signal(item.get('distance_50'), 0.08),
            _bounded_signal(item.get('distance_200'), 0.20),
        ]
        score = _sentiment_mean(signals)
        if score is not None:
            trend_scores.append(score)
    trend_score = _sentiment_mean(trend_scores)
    trend_detail = (
        f'{len(trend_scores)}/3 índices con histórico; combina retornos de 5/20 días '
        'y posición frente a SMA 50/200.'
    )
    components.append(_build_sentiment_component(
        'trend', 'Tendencia', 30, trend_score, trend_detail, len(trend_scores)
    ))

    breadth_items = [metrics.get(ticker) for ticker in SENTIMENT_BREADTH_TICKERS]
    breadth_items = [item for item in breadth_items if item]
    if breadth_items:
        above_50 = sum(
            item.get('distance_50') is not None and item['distance_50'] >= 0
            for item in breadth_items
        ) / len(breadth_items)
        positive_5 = sum(
            item.get('ret_5d') is not None and item['ret_5d'] >= 0
            for item in breadth_items
        ) / len(breadth_items)
        positive_20 = sum(
            item.get('ret_20d') is not None and item['ret_20d'] >= 0
            for item in breadth_items
        ) / len(breadth_items)
        breadth_score = (above_50 * 0.45 + positive_5 * 0.25 + positive_20 * 0.30) * 100
        breadth_detail = (
            f'{round(above_50 * 100)}% de sectores sobre SMA 50; '
            f'{round(positive_5 * 100)}% positivos en 5 días; '
            f'{round(positive_20 * 100)}% positivos en 20 días.'
        )
    else:
        breadth_score = None
        breadth_detail = 'No hay suficientes ETFs sectoriales para medir amplitud.'
    components.append(_build_sentiment_component(
        'breadth', 'Amplitud sectorial', 20, breadth_score, breadth_detail, len(breadth_items)
    ))

    vix = metrics.get('^VIX')
    if vix:
        vix_percentile = _percentile(vix.get('history'), vix.get('price'))
        vix_level_score = 100 - vix_percentile if vix_percentile is not None else None
        vix_direction_score = _bounded_signal(-vix['ret_5d'], 0.10) if vix.get('ret_5d') is not None else None
        volatility_score = weighted([(vix_level_score, .70), (vix_direction_score, .30)])
        vix_detail = (
            f'VIX {vix["price"]:.2f}; nivel relativo de 1 año y dirección de 5 días. '
            'Un VIX alto o subiendo resta confianza al riesgo.'
        )
    else:
        volatility_score = None
        vix_detail = 'No hay VIX disponible.'
    components.append(_build_sentiment_component(
        'volatility', 'Volatilidad', 20, volatility_score, vix_detail,
        len(vix.get('history', [])) if vix else 0,
    ))

    spy = metrics.get('SPY')
    iwm = metrics.get('IWM')
    hyg = metrics.get('HYG')
    risk_scores = []
    if hyg and hyg.get('ret_20d') is not None:
        risk_scores.append(_bounded_signal(hyg['ret_20d'], 0.08))
    if spy and iwm and spy.get('ret_20d') is not None and iwm.get('ret_20d') is not None:
        risk_scores.append(_bounded_signal(iwm['ret_20d'] - spy['ret_20d'], 0.08))
    risk_score = _sentiment_mean(risk_scores)
    risk_detail = (
        f'HYG y fortaleza relativa de IWM frente a SPY; {len(risk_scores)}/2 señales disponibles.'
    )
    components.append(_build_sentiment_component(
        'risk_appetite', 'Apetito por riesgo', 15, risk_score, risk_detail, len(risk_scores)
    ))

    fred_series = fred.get('series') or {}
    macro_scores = []
    macro_details = []
    credit = fred_series.get('credit_spread')
    if credit:
        values = [row.get('value') for row in credit.get('history', [])]
        rank = _percentile(values, credit.get('value'))
        if rank is not None:
            macro_scores.append(100 - rank)
            macro_details.append(f'crédito HY en percentil {round(rank)} (invertido)')
    curve = fred_series.get('yield_curve')
    if curve:
        values = [row.get('value') for row in curve.get('history', [])]
        rank = _percentile(values, curve.get('value'))
        # FRED returns percentage points (e.g. 0.50), not decimal fractions.
        level = _bounded_signal(curve.get('value'), 2.0)
        curve_score = _sentiment_mean([rank, level])
        if curve_score is not None:
            macro_scores.append(curve_score)
            macro_details.append(f'curva 10Y–2Y {curve["value"]:.2f}%')
    macro_score = _sentiment_mean(macro_scores)
    macro_detail = '; '.join(macro_details) if macro_details else (
        'FRED no está disponible; se omite esta parte y se reajustan los pesos.'
    )
    components.append(_build_sentiment_component(
        'macro_risk', 'Macro y crédito', 15, macro_score, macro_detail, len(macro_scores)
    ))

    available = [item for item in components if item['available']]
    total_weight = sum(item['weight'] for item in available)
    if available and total_weight:
        score = sum(item['score'] * item['weight'] for item in available) / total_weight
        component_scores = [item['score'] for item in available]
        dispersion = statistics.pstdev(component_scores) if len(component_scores) > 1 else 0
        agreement = _clip(100 - dispersion * 2)
        expected_samples = {'trend': 3, 'breadth': 11, 'volatility': 200, 'risk_appetite': 2, 'macro_risk': 2}
        coverage = sum(item['weight'] * min(1, (item['sample'] or 0) / expected_samples[item['key']]) for item in available)
        confidence = round(coverage * (.5 + .5 * agreement / 100))
    else:
        score = None
        confidence = 0
        dispersion = None
    score = round(_clip(score), 1) if score is not None else None
    if score is None:
        label = 'Contexto no disponible'
    elif score >= 60:
        label = 'Sesgo alcista'
    elif score <= 40:
        label = 'Sesgo bajista'
    else:
        label = 'Mixto / indeciso'

    result = {
        'status': 'ok' if available else 'error',
        'score': score,
        'label': label,
        'quality': confidence,
        'horizon': 'Tendencia de varios días · cierres completos',
        'session': _market_session(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'last_history_date': last_history_date,
        'source': 'Yahoo Finance + FRED',
        'data_delay_note': 'Usa el último precio disponible; algunos datos pueden tener retraso o ser de cierre.',
        'available_weight': round(total_weight, 1),
        'dispersion': round(dispersion, 1) if dispersion is not None else None,
        'components': components,
        'errors': errors + list(fred.get('errors') or []),
        'disclaimer': 'Contexto heurístico de varios días, no probabilidad ni predicción intradía.',
    }
    return result


pulse_service = PulseService(
    download=yahoo_download,
    fetch_fred=lambda: fetch_fred_sentiment(http_req, FRED_API_KEY) if HAS_REQUESTS else {'series': {}, 'errors': ['requests no instalado']},
    build_context=build_market_context, store=local_store,
)


@app.route('/market-sentiment', methods=['GET', 'POST'])
def get_market_sentiment():
    body = flask_request.get_json(silent=True) or {}
    force = body.get('force') is True or flask_request.args.get('force') == '1'
    # Deliberately ignore browser-supplied quotes: all inputs are timestamped
    # server downloads, so an old dashboard batch cannot override fresh data.
    return jsonify(pulse_service.snapshot(force=force))

@app.route('/stock/<ticker>')
def get_stock(ticker):
    try:
        ticker = normalize_ticker(ticker)
        include_supplemental = flask_request.args.get('audit', '0').lower() in {
            '1', 'true', 'yes'
        }
        cached = cache_get(('stock', ticker, include_supplemental))
        if cached is not None: return jsonify(cached)
        t = yf.Ticker(ticker)
        info = t.info

        if not info or (info.get('regularMarketPrice') is None and info.get('currentPrice') is None):
            return jsonify({'error': f'Ticker "{ticker}" no encontrado'}), 404

        hist = t.history(period="1y")

        balance_sheet = None
        try:
            balance_sheet = t.quarterly_balance_sheet
            if balance_sheet is None or balance_sheet.empty:
                balance_sheet = t.balance_sheet
        except Exception:
            balance_sheet = None

        price = info.get('currentPrice') or info.get('regularMarketPrice')
        prev_close = info.get('previousClose') or info.get('regularMarketPreviousClose')
        change = round(price - prev_close, 2) if price is not None and prev_close else None
        change_pct = round((change / prev_close) * 100, 2) if change is not None and prev_close else None

        sma200 = None
        sma_period = None
        above_sma200 = None
        if len(hist) >= 200:
            sma_period = 200
            sma200 = round(hist['Close'].rolling(200).mean().dropna().iloc[-1], 2)
            above_sma200 = bool(price > sma200) if price else None

        atr = None
        if len(hist) >= 14:
            prev_close_series = hist['Close'].shift(1)
            true_range = pd.concat([hist['High']-hist['Low'],(hist['High']-prev_close_series).abs(),(hist['Low']-prev_close_series).abs()],axis=1).max(axis=1)
            atr = round(float(true_range.rolling(14).mean().iloc[-1]), 2)

        rev_growth = None
        revenue_ttm = None
        revenue_ttm_calculated = None
        revenue_ttm_reported = clean(info.get('totalRevenue'))
        revenue_quarters_count = 0
        revenue_quarter_values = []
        net_income_ttm = None
        fin = None
        qfin = None
        try:
            qfin = t.quarterly_financials
            if qfin is not None and not qfin.empty and 'Total Revenue' in qfin.index:
                qrevs = qfin.loc['Total Revenue'].dropna().iloc[:4]
                revenue_quarters_count = len(qrevs)
                revenue_quarter_values = [float(value) for value in qrevs]
                if len(qrevs) == 4:
                    revenue_ttm_calculated = float(qrevs.sum())
                    revenue_ttm = revenue_ttm_calculated
            if qfin is not None and not qfin.empty:
                net_income_row = next(
                    (name for name in ('Net Income', 'Net Income Common Stockholders')
                     if name in qfin.index),
                    None,
                )
                if net_income_row:
                    qincome = qfin.loc[net_income_row].dropna().iloc[:4]
                    if len(qincome) == 4:
                        net_income_ttm = float(qincome.sum())
            fin = t.financials
            if fin is not None and not fin.empty and 'Total Revenue' in fin.index:
                revs = fin.loc['Total Revenue'].dropna()
                if len(revs) >= 2:
                    rev_growth = round((revs.iloc[0] - revs.iloc[1]) / abs(revs.iloc[1]) * 100, 1)
        except:
            pass

        if revenue_ttm is None:
            revenue_ttm = revenue_ttm_reported
        if rev_growth is None and clean(info.get('revenueGrowth')) is not None:
            rev_growth = round(float(info.get('revenueGrowth')) * 100, 1)

        total_cash = clean(info.get('totalCash'))
        if total_cash is None:
            total_cash = latest_statement_value(balance_sheet, (
                'Cash Cash Equivalents And Short Term Investments',
                'Cash And Cash Equivalents',
                'Cash Financial',
            ))
        total_debt = clean(info.get('totalDebt'))
        if total_debt is None:
            total_debt = latest_statement_value(balance_sheet, (
                'Total Debt',
                'Long Term Debt And Capital Lease Obligation',
                'Long Term Debt',
            ))
        runway_months = None
        operating_expenses_annual = None
        monthly_operating_expenses = None
        quarterly_burn = None
        quarterly_cash_flow = None
        monthly_cash_burn = None
        cash_generating = None
        cash_burn_source = None
        try:
            qcf = t.quarterly_cashflow
            if qcf is not None and not qcf.empty:
                cash_flow = None
                for row_name in ('Free Cash Flow','Operating Cash Flow','Total Cash From Operating Activities'):
                    if row_name in qcf.index:
                        vals=qcf.loc[row_name].dropna()
                        if len(vals): cash_flow=float(vals.iloc[0]); cash_burn_source=row_name; break
                if cash_flow is not None:
                    quarterly_cash_flow = round(cash_flow, 2)
                    cash_generating = cash_flow >= 0
                    if cash_flow < 0:
                        quarterly_burn=abs(cash_flow)
                        monthly_cash_burn=round(quarterly_burn/3, 2)
        except Exception: pass

        # Fórmula original del usuario: Cash total ÷ (Operating Expenses anuales ÷ 12).
        # Conservamos también los campos de flujo de caja para no retirar datos de la API.
        if fin is None:
            try:
                fin = t.financials
            except Exception:
                fin = None
        operating_expenses_annual = latest_statement_value(fin, (
            'Operating Expense',
            'Total Operating Expenses',
            'Operating Expenses',
        ))
        monthly_operating_expenses, runway_months = calculate_operating_expense_runway(
            total_cash,
            operating_expenses_annual,
        )

        graham_number = None
        pe_fair_value = None
        graham_formula = None
        book_value = info.get('bookValue')
        try:
            eps_ttm = info.get('trailingEps')
            eps_fwd = info.get('forwardEps')
            if book_value and eps_ttm and book_value > 0 and eps_ttm > 0:
                graham_number = round(math.sqrt(22.5 * eps_ttm * book_value), 2)
            if eps_fwd and eps_fwd > 0:
                pe_fair_value = round(eps_fwd * 15, 2)
            if eps_ttm and eps_ttm > 0 and rev_growth is not None:
                g = max(0, min(rev_growth, 50))
                graham_formula = round(eps_ttm * (8.5 + 2 * g), 2)
        except:
            pass

        debt_to_equity_raw = clean(info.get('debtToEquity'))
        debt_to_equity_ratio = normalize_debt_to_equity(debt_to_equity_raw)
        dividend_yield = normalize_dividend_yield(info.get('dividendYield'))
        advanced_metrics = {
            'gross_margin': round(float(info['grossMargins']) * 100, 2) if clean(info.get('grossMargins')) is not None else None,
            'ebitda_margin': round(float(info['ebitdaMargins']) * 100, 2) if clean(info.get('ebitdaMargins')) is not None else None,
            'operating_margin': round(float(info['operatingMargins']) * 100, 2) if clean(info.get('operatingMargins')) is not None else None,
            'net_margin': round(float(info['profitMargins']) * 100, 2) if clean(info.get('profitMargins')) is not None else None,
            'return_on_assets': round(float(info['returnOnAssets']) * 100, 2) if clean(info.get('returnOnAssets')) is not None else None,
            'return_on_equity': round(float(info['returnOnEquity']) * 100, 2) if clean(info.get('returnOnEquity')) is not None else None,
            'price_to_book': clean(info.get('priceToBook')),
            'peg_ratio': clean(info.get('trailingPegRatio')) or clean(info.get('pegRatio')),
            'enterprise_to_revenue': clean(info.get('enterpriseToRevenue')),
            'enterprise_to_ebitda': clean(info.get('enterpriseToEbitda')),
            'price_to_free_cash_flow': clean(info.get('priceToFreeCashflows')),
            'current_ratio': clean(info.get('currentRatio')),
            'free_cash_flow': clean(info.get('freeCashflow')),
            'operating_cash_flow': clean(info.get('operatingCashflow')),
            'research_and_development': latest_statement_value(
                fin,
                ('Research And Development', 'Research Development'),
            ),
        }
        advanced_metric_sources = {
            key: ('Yahoo Finance' if value is not None else None)
            for key, value in advanced_metrics.items()
        }
        shares_outstanding = (
            clean(info.get('sharesOutstanding'))
            or clean(info.get('impliedSharesOutstanding'))
        )
        market_cap_calculated = (
            float(price) * float(shares_outstanding)
            if price is not None and shares_outstanding is not None else None
        )
        pe_calculated = (
            float(price) / float(eps_ttm)
            if price is not None and eps_ttm not in (None, 0) else None
        )
        margin_calculated = (
            float(net_income_ttm) / float(revenue_ttm) * 100
            if net_income_ttm is not None and revenue_ttm not in (None, 0) else None
        )
        updated_at = datetime.now(timezone.utc).isoformat()

        def trace(source, kind, period, method=None, received=None, calculated=None):
            item = {
                'source': source,
                'kind': kind,
                'period': period,
                'updated_at': updated_at,
            }
            if method:
                item['method'] = method
            if received is not None:
                item['received_value'] = clean(received)
            if calculated is not None:
                item['calculated_value'] = clean(calculated)
            return item

        metric_provenance = {
            'price': trace('Yahoo Finance', 'reported', 'Último', received=price),
            'market_cap': trace(
                'Yahoo Finance', 'reported', 'Último',
                'Precio × acciones en circulación',
                info.get('marketCap'), market_cap_calculated,
            ),
            'shares_outstanding': trace(
                'Yahoo Finance', 'reported', 'Último',
                received=shares_outstanding,
            ),
            'pe': trace(
                'Yahoo Finance', 'reported', 'TTM',
                'Precio ÷ EPS TTM', info.get('trailingPE'), pe_calculated,
            ),
            'forward_pe': trace(
                'Yahoo Finance', 'estimated', 'Forward',
                received=info.get('forwardPE'),
            ),
            'eps': trace(
                'Yahoo Finance', 'reported', 'TTM',
                received=info.get('trailingEps'),
            ),
            'eps_forward': trace(
                'Yahoo Finance', 'estimated', 'Forward',
                received=info.get('forwardEps'),
            ),
            'revenue_ttm': trace(
                'Yahoo Finance', 'calculated', 'TTM',
                'Suma de los últimos 4 trimestres',
                revenue_ttm_reported, revenue_ttm_calculated,
            ),
            'revenue_growth': trace(
                'Yahoo Finance', 'calculated', 'FY YoY',
                '(Revenue FY actual ÷ Revenue FY anterior − 1) × 100',
                clean(info.get('revenueGrowth')) * 100
                if clean(info.get('revenueGrowth')) is not None else None,
                rev_growth,
            ),
            'profit_margin': trace(
                'Yahoo Finance', 'reported', 'TTM',
                'Ganancia neta TTM ÷ Revenue TTM',
                clean(info.get('profitMargins')) * 100
                if clean(info.get('profitMargins')) is not None else None,
                margin_calculated,
            ),
            'total_cash': trace(
                'Yahoo Finance', 'reported', 'Último trimestre',
                received=total_cash,
            ),
            'total_debt': trace(
                'Yahoo Finance', 'reported', 'Último trimestre',
                received=total_debt,
            ),
            'debt_to_equity_ratio': trace(
                'Yahoo Finance', 'calculated', 'Último trimestre',
                'Debt to Equity recibido ÷ 100 cuando Yahoo lo expresa como porcentaje',
                debt_to_equity_raw, debt_to_equity_ratio,
            ),
            'monthly_operating_expenses': trace(
                'Yahoo Finance', 'calculated', 'FY',
                'Operating Expenses anuales ÷ 12',
                operating_expenses_annual, monthly_operating_expenses,
            ),
            'runway_months': trace(
                'Yahoo Finance', 'calculated', 'FY',
                'Cash ÷ (Operating Expenses anuales ÷ 12)',
                calculated=runway_months,
            ),
            'analyst_target': trace(
                'Yahoo Finance', 'estimated', 'Consenso',
                received=info.get('targetMeanPrice'),
            ),
            'atr': trace(
                'Yahoo Finance', 'calculated', '14 sesiones',
                'True Range incluyendo el cierre anterior',
                calculated=atr,
            ),
            'sma200': trace(
                'Yahoo Finance', 'calculated', '200 sesiones',
                'Promedio simple de 200 cierres',
                calculated=sma200,
            ),
            'beta': trace('Yahoo Finance', 'reported', 'Histórico', received=info.get('beta')),
            'dividend_yield': trace(
                'Yahoo Finance', 'calculated', 'Forward/TTM',
                'Normalización del rendimiento recibido a porcentaje',
                info.get('dividendYield'), dividend_yield,
            ),
        }

        payload = {
            'ticker': ticker,
            'name': info.get('longName') or info.get('shortName', ticker),
            'sector': info.get('sector', '—'),
            'industry': info.get('industry', '—'),
            'price': round(price, 2) if price else None,
            'change': change,
            'change_pct': change_pct,
            'pe': round(info['trailingPE'], 1) if info.get('trailingPE') else None,
            'forward_pe': round(info['forwardPE'], 1) if info.get('forwardPE') else None,
            'eps': info.get('trailingEps'),
            'eps_forward': info.get('forwardEps'),
            'beta': round(info['beta'], 2) if info.get('beta') else None,
            'market_cap': info.get('marketCap'),
            'shares_outstanding': shares_outstanding,
            'revenue_ttm': revenue_ttm,
            'revenue_ttm_calculated': revenue_ttm_calculated,
            'revenue_ttm_reported': revenue_ttm_reported,
            'revenue_quarters_count': revenue_quarters_count,
            'revenue_quarter_values': revenue_quarter_values,
            'net_income_ttm': net_income_ttm,
            'revenue_growth': rev_growth,
            'profit_margin': round(info['profitMargins'] * 100, 1) if info.get('profitMargins') else None,
            'sma200': sma200,
            'sma_period': sma_period,
            'above_sma200': above_sma200,
            'atr': atr,
            'total_cash': total_cash,
            'total_debt': total_debt,
            'debt_to_equity': debt_to_equity_raw,
            'debt_to_equity_ratio': debt_to_equity_ratio,
            'runway_months': runway_months,
            'runway_method': 'cash_divided_by_monthly_operating_expenses',
            'operating_expenses_annual': operating_expenses_annual,
            'monthly_operating_expenses': monthly_operating_expenses,
            'cash_generating': cash_generating,
            'cash_burn_source': cash_burn_source,
            'analyst_target': info.get('targetMeanPrice'),
            'analyst_low': info.get('targetLowPrice'),
            'analyst_high': info.get('targetHighPrice'),
            'recommendation': info.get('recommendationKey', '—'),
            'num_analysts': info.get('numberOfAnalystOpinions'),
            'fifty_two_week_low': info.get('fiftyTwoWeekLow'),
            'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
            'dividend_yield': dividend_yield,
            'short_ratio': info.get('shortRatio'),
            'book_value': book_value,
            'graham_number': graham_number,
            'pe_fair_value': pe_fair_value,
            'graham_formula': graham_formula,
            'quarterly_burn': quarterly_burn,
            'quarterly_cash_flow': quarterly_cash_flow,
            'monthly_cash_burn': monthly_cash_burn,
            'advanced_metrics': advanced_metrics,
            'advanced_metric_sources': advanced_metric_sources,
            'metric_provenance': metric_provenance,
            'data_source':'Yahoo Finance',
            'updated_at':updated_at,
        }

        if HAS_REQUESTS and include_supplemental:
            fmp_snapshot = fetch_fmp_snapshot(http_req, ticker, FMP_API_KEY)
            sec_snapshot = fetch_sec_snapshot(http_req, ticker, SEC_USER_AGENT)
        else:
            fmp_snapshot = {
                'configured': bool(FMP_API_KEY),
                'status': 'standby' if FMP_API_KEY else 'disabled',
                'metrics': {},
            }
            sec_snapshot = {
                'configured': bool(SEC_USER_AGENT and '@' in SEC_USER_AGENT),
                'status': 'standby' if SEC_USER_AGENT and '@' in SEC_USER_AGENT else 'disabled',
                'metrics': {},
            }

        # FMP complementa los huecos, pero no reemplaza silenciosamente a Yahoo.
        fmp_metrics = fmp_snapshot.get('metrics') or {}
        advanced_fmp_map = {
            'gross_margin': 'gross_margin',
            'ebitda_margin': 'ebitda_margin',
            'operating_margin': 'operating_margin',
            'net_margin': 'net_margin',
            'return_on_assets': 'roa',
            'return_on_equity': 'roe',
            'price_to_book': 'price_to_book',
            'peg_ratio': 'peg_ratio',
            'enterprise_to_revenue': 'enterprise_to_revenue',
            'enterprise_to_ebitda': 'enterprise_to_ebitda',
            'price_to_free_cash_flow': 'price_to_fcf',
            'current_ratio': 'current_ratio',
            'free_cash_flow': 'free_cash_flow',
            'research_and_development': 'research_and_development',
        }
        for local_key, fmp_key in advanced_fmp_map.items():
            if advanced_metrics.get(local_key) is None and fmp_metrics.get(fmp_key) is not None:
                value = fmp_metrics[fmp_key]
                if local_key in {
                    'gross_margin', 'ebitda_margin', 'operating_margin',
                    'net_margin', 'return_on_assets', 'return_on_equity',
                } and abs(float(value)) <= 1:
                    value = float(value) * 100
                advanced_metrics[local_key] = round(float(value), 3)
                advanced_metric_sources[local_key] = 'FMP'

        advanced_periods = {
            'gross_margin': 'TTM',
            'ebitda_margin': 'TTM',
            'operating_margin': 'TTM',
            'net_margin': 'TTM',
            'return_on_assets': 'TTM',
            'return_on_equity': 'TTM',
            'price_to_book': 'TTM',
            'peg_ratio': 'TTM',
            'enterprise_to_revenue': 'TTM',
            'enterprise_to_ebitda': 'TTM',
            'price_to_free_cash_flow': 'TTM',
            'current_ratio': 'Último trimestre',
            'free_cash_flow': 'TTM',
            'operating_cash_flow': 'TTM',
            'research_and_development': 'FY',
        }
        for metric_key, metric_value in advanced_metrics.items():
            metric_provenance[metric_key] = trace(
                advanced_metric_sources.get(metric_key) or 'Sin fuente',
                'reported',
                advanced_periods.get(metric_key, 'TTM'),
                received=metric_value,
            )

        payload['integrations'] = {
            'yahoo': {'configured': True, 'status': 'ok'},
            'fmp': {
                'configured': fmp_snapshot.get('configured', False),
                'status': fmp_snapshot.get('status', 'disabled'),
                'errors': fmp_snapshot.get('errors', []),
            },
            'sec_edgar': {
                'configured': sec_snapshot.get('configured', False),
                'status': sec_snapshot.get('status', 'disabled'),
                'cik': sec_snapshot.get('cik'),
            },
        }
        payload['cross_source'] = {
            'fmp': fmp_metrics,
            'sec_edgar': sec_snapshot.get('metrics') or {},
        }
        payload['data_checks'] = (
            build_identity_checks(payload)
            + build_cross_source_checks(
                payload,
                fmp_metrics,
                sec_snapshot.get('metrics') or {},
            )
        )
        payload['data_quality'] = {
            'passed': sum(1 for check in payload['data_checks'] if check['status'] == 'pass'),
            'review': sum(1 for check in payload['data_checks'] if check['status'] == 'review'),
            'unavailable': sum(1 for check in payload['data_checks'] if check['status'] == 'unavailable'),
        }
        cache_set(('stock',ticker,include_supplemental),payload)
        return jsonify(payload)

    except ValueError as e:
        return jsonify({'error':str(e)}),400
    except Exception as e:
        traceback.print_exc()
        message=str(e); status=429 if 'Too Many Requests' in message or 'Rate limit' in message else 502
        return jsonify({'error':message}),status


@app.route('/history/<ticker>')
def get_history(ticker):
    try:
        ticker = normalize_ticker(ticker)
        period = flask_request.args.get('period', '1y').lower().strip()
        allowed_periods = {'1mo', '6mo', '1y', '5y'}
        if period not in allowed_periods:
            return jsonify({'error': 'Periodo inválido. Usa 1mo, 6mo, 1y o 5y.'}), 400
        cached=cache_get(('history',ticker,period))
        if cached is not None: return jsonify(cached)
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty:
            return jsonify({'error': 'Sin historial disponible'}), 404
        dates = [str(d.date()) for d in hist.index]
        prices = [round(float(p), 2) for p in hist['Close']]
        payload={'ticker':ticker,'period':period,'dates':dates,'prices':prices,'data_source':'Yahoo Finance','updated_at':datetime.now(timezone.utc).isoformat()}
        cache_set(('history',ticker,period),payload)
        return jsonify(payload)
    except ValueError as e:
        return jsonify({'error':str(e)}),400
    except Exception as e:
        message = str(e)
        status = 429 if 'Too Many Requests' in message or 'Rate limit' in message else 502
        return jsonify({'error': message}), status


@app.route('/fundamentals/<ticker>')
def get_fundamentals(ticker):
    try:
        ticker = normalize_ticker(ticker)
        t = yf.Ticker(ticker)
        result = {'ticker': ticker, 'eps': [], 'revenue': [], 'margins': [], 'pe_history': []}

        try:
            earnings = t.quarterly_earnings
            if earnings is not None and not earnings.empty:
                for date, row in earnings.iterrows():
                    result['eps'].append({
                        'period': str(date),
                        'actual': round(float(row.get('Earnings', 0) or 0), 2),
                        'estimate': round(float(row.get('Estimate', 0) or 0), 2) if row.get('Estimate') else None
                    })
                result['eps'] = list(reversed(result['eps']))[-8:]
        except: pass

        try:
            fin = t.financials
            if fin is not None and not fin.empty:
                for col in fin.columns[:4]:
                    rev = fin.loc['Total Revenue', col] if 'Total Revenue' in fin.index else None
                    net = fin.loc['Net Income', col] if 'Net Income' in fin.index else None
                    gross = fin.loc['Gross Profit', col] if 'Gross Profit' in fin.index else None
                    if rev and rev > 0:
                        result['revenue'].append({
                            'period': str(col.year),
                            'revenue': round(float(rev) / 1e9, 2),
                            'net_income': round(float(net) / 1e9, 2) if net else None,
                            'gross_profit': round(float(gross) / 1e9, 2) if gross else None,
                            'margin': round(float(net) / float(rev) * 100, 1) if net and rev else None,
                            'gross_margin': round(float(gross) / float(rev) * 100, 1) if gross and rev else None,
                        })
                result['revenue'] = list(reversed(result['revenue']))
        except: pass

        try:
            qfin = t.quarterly_financials
            result['quarterly_revenue'] = []
            if qfin is not None and not qfin.empty and 'Total Revenue' in qfin.index:
                for col in list(reversed(qfin.columns))[-8:]:
                    rev = qfin.loc['Total Revenue', col]
                    if rev and rev > 0:
                        net = qfin.loc['Net Income', col] if 'Net Income' in qfin.index else None
                        result['quarterly_revenue'].append({
                            'period': str(col)[:7],
                            'revenue': round(float(rev) / 1e9, 2),
                            'net_income': round(float(net) / 1e9, 2) if net is not None else None,
                            'margin': round(float(net) / float(rev) * 100, 1)
                            if net is not None else None,
                        })
        except: pass

        result['pe_history']=historical_pe_series(t,period='5y',interval='3mo')[-12:]
        result['pe_history_method']='Precio trimestral / EPS diluido del año fiscal disponible'

        def sanitize(obj):
            if isinstance(obj, dict): return {k: sanitize(v) for k, v in obj.items()}
            elif isinstance(obj, list): return [sanitize(v) for v in obj]
            elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return None
            return obj
        result = sanitize(result)
        return jsonify(result)

    except ValueError as e:
        return jsonify({'error':str(e)}),400
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/financials/<ticker>')
def get_financials(ticker):
    try:
        ticker = normalize_ticker(ticker)
        t = yf.Ticker(ticker)
        result = {}

        try:
            qe = t.quarterly_earnings
            if qe is not None and not qe.empty:
                qe = qe.sort_index()
                result['eps_quarterly'] = {
                    'labels': [str(i) for i in qe.index],
                    'reported': [round(float(v),2) if v == v else None for v in qe.get('Reported EPS', qe.iloc[:,0])],
                    'estimated': [round(float(v),2) if v == v else None for v in qe.get('Estimated EPS', qe.iloc[:,0])]
                }
        except: pass

        try:
            fin = t.financials
            if fin is not None and not fin.empty:
                cols = list(fin.columns)
                cols_sorted = sorted(cols)
                labels = [str(c.date()) for c in cols_sorted]
                def get_row(name):
                    if name in fin.index:
                        return [round(float(fin.loc[name, c])/1e9, 2) if fin.loc[name, c] == fin.loc[name, c] else None for c in cols_sorted]
                    return None
                rev = get_row('Total Revenue')
                net = get_row('Net Income')
                gross = get_row('Gross Profit')
                result['annual'] = {'labels': labels, 'revenue': rev, 'net_income': net, 'gross_profit': gross}
        except: pass

        try:
            qfin = t.quarterly_financials
            if qfin is not None and not qfin.empty:
                cols = list(qfin.columns)
                cols_sorted = sorted(cols)[-8:]
                labels = [str(c.date()) for c in cols_sorted]
                def get_qrow(name):
                    if name in qfin.index:
                        return [round(float(qfin.loc[name, c])/1e9, 2) if qfin.loc[name, c] == qfin.loc[name, c] else None for c in cols_sorted]
                    return None
                qrev = get_qrow('Total Revenue')
                qnet = get_qrow('Net Income')
                result['quarterly'] = {'labels': labels, 'revenue': qrev, 'net_income': qnet}
        except: pass

        try:
            pe_points=historical_pe_series(t,period='5y',interval='3mo')
            result['pe_history']={'labels':[p['period'] for p in pe_points],'pe':[p['pe'] for p in pe_points],'eps':[p['eps'] for p in pe_points],'method':'Precio trimestral / EPS diluido del año fiscal disponible'}
        except Exception: pass

        try:
            fin2 = t.financials
            if fin2 is not None and not fin2.empty:
                cols = sorted(fin2.columns)
                labels = [str(c.date()) for c in cols]
                margins = []
                for c in cols:
                    try:
                        rev_v = float(fin2.loc['Total Revenue', c])
                        net_v = float(fin2.loc['Net Income', c])
                        margins.append(round(net_v/rev_v*100, 1) if rev_v else None)
                    except: margins.append(None)
                result['margins'] = {'labels': labels, 'net_margin': margins}
        except: pass

        def sanitize(obj):
            if isinstance(obj, dict): return {k: sanitize(v) for k, v in obj.items()}
            elif isinstance(obj, list): return [sanitize(v) for v in obj]
            elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return None
            return obj
        result = sanitize(result)
        return jsonify(result)

    except ValueError as e:
        return jsonify({'error':str(e)}),400
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/batch', methods=['POST'])
def get_batch():
    """Endpoint para heatmap: obtiene precio y cambio % de múltiples tickers a la vez."""
    body = flask_request.get_json(silent=True) or {}
    raw = body.get('tickers', [])
    tickers_list=[]
    for value in raw:
        try:
            ticker=normalize_ticker(value)
            if ticker not in tickers_list: tickers_list.append(ticker)
        except ValueError: continue
        if len(tickers_list)>=60: break
    if not tickers_list:
        return jsonify({})

    results = {t: cache_get(('batch-quote', t), ttl=30) for t in tickers_list}
    tickers_list = [t for t in tickers_list if results[t] is None]
    if not tickers_list:
        return jsonify(results)
    for t in tickers_list:
        results[t] = {'ticker': t, 'price': None, 'change': None, 'change_pct': None, 'market_cap': None, 'name': t}

    # --- Batch price download via yfinance ---
    try:
        joined = ' '.join(tickers_list)
        df = yahoo_download(joined, period='5d', progress=False, auto_adjust=True, threads=4, timeout=8)

        if HAS_PANDAS:
            is_multi = hasattr(df.columns, 'levels')
        else:
            is_multi = False

        def get_closes(ticker_sym):
            try:
                if is_multi:
                    if 'Close' in df.columns.get_level_values(0):
                        col_df = df['Close']
                        if hasattr(col_df, 'columns') and ticker_sym in col_df.columns:
                            return col_df[ticker_sym].dropna()
                    if ticker_sym in df.columns.get_level_values(0):
                        return df[ticker_sym]['Close'].dropna()
                else:
                    if len(tickers_list) == 1 and 'Close' in df.columns:
                        return df['Close'].dropna()
            except:
                pass
            return None

        for t in tickers_list:
            try:
                closes = get_closes(t)
                if closes is not None and len(closes) >= 2:
                    price = float(closes.iloc[-1])
                    prev  = float(closes.iloc[-2])
                    if prev > 0:
                        chg  = round(price - prev, 2)
                        chgp = round(chg / prev * 100, 2)
                        results[t].update({'price': round(price, 2), 'change': chg, 'change_pct': chgp,
                                           'data_date': str(closes.index[-1].date()),
                                           'source': 'Yahoo Finance · vela diaria, puede ser parcial',
                                           'spark_prices': [round(float(x), 4) for x in closes.iloc[-20:]],
                                           'queried_at': datetime.now(timezone.utc).isoformat()})
            except:
                pass
    except:
        traceback.print_exc()

    # --- Market cap + fallback price via fast_info ---
    for t in tickers_list[:30]:
        try:
            fi = yf.Ticker(t).fast_info
            mc = getattr(fi, 'market_cap', None)
            if mc:
                v = clean(mc)
                if v is not None:
                    results[t]['market_cap'] = int(v)
            if results[t]['price'] is None:
                lp = getattr(fi, 'last_price', None)
                pc = getattr(fi, 'previous_close', None)
                if lp and float(lp) > 0:
                    p2 = round(float(lp), 2)
                    results[t]['price'] = p2
                    results[t]['source'] = 'Yahoo Finance · hora del precio no informada'
                    results[t]['data_date'] = None
                    if pc and float(pc) > 0:
                        chg = round(p2 - float(pc), 2)
                        results[t]['change'] = chg
                        results[t]['change_pct'] = round(chg / float(pc) * 100, 2)
        except:
            pass

    def sanitize(obj):
        if isinstance(obj, dict): return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list): return [sanitize(v) for v in obj]
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return None
        return obj

    results = sanitize(results)
    for ticker in tickers_list:
        if results[ticker]['price'] is not None:
            cache_set(('batch-quote', ticker), results[ticker])
    return jsonify(results)


@app.route('/chat', methods=['POST'])
def chat():
    """Proxy hacia Groq API (100% gratis) — API Key en console.groq.com"""
    body = flask_request.get_json(silent=True) or {}
    messages = body.get('messages', [])
    api_key = body.get('api_key', '').strip() or os.environ.get('GROQ_API_KEY', '')
    if not api_key:
        return jsonify({'error': 'API_KEY_MISSING'}), 400
    if not messages:
        return jsonify({'error': 'Sin mensajes'}), 400
    if not HAS_REQUESTS:
        return jsonify({'error': 'pip install requests'}), 500
    full_messages = [{'role': 'system', 'content': CHATBOT_SYSTEM}] + messages[-20:]

    # Auto-detectar proveedor por prefijo de la key
    # sk-...   → OpenAI  (gpt-4o-mini)
    # gsk_...  → Groq    (llama-3.3-70b-versatile — gratis)
    # AIza...  → Google Gemini (gemini-2.0-flash — gratis)
    if api_key.startswith('sk-'):
        url   = 'https://api.openai.com/v1/chat/completions'
        model = 'gpt-4o-mini'
        try:
            resp = http_req.post(url,
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': model, 'messages': full_messages, 'max_tokens': 1500, 'temperature': 0.7},
                timeout=30)
            if not resp.ok:
                try: err_msg = resp.json().get('error',{}).get('message', f'HTTP {resp.status_code}')
                except: err_msg = f'HTTP {resp.status_code}'
                return jsonify({'error': err_msg}), resp.status_code
            return jsonify({'content': resp.json()['choices'][0]['message']['content']})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif api_key.startswith('AIza') or api_key.startswith('AQ.'):
        # Google Gemini REST API
        gemini_url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}'
        # Convertir mensajes al formato Gemini
        gemini_contents = []
        for m in messages[-20:]:
            role = 'user' if m['role'] == 'user' else 'model'
            gemini_contents.append({'role': role, 'parts': [{'text': m['content']}]})
        # System prompt como primer turno user/model
        gemini_payload = {
            'system_instruction': {'parts': [{'text': CHATBOT_SYSTEM}]},
            'contents': gemini_contents,
            'generationConfig': {'maxOutputTokens': 1500, 'temperature': 0.7}
        }
        try:
            resp = http_req.post(gemini_url, json=gemini_payload, timeout=30)
            if not resp.ok:
                try: err_msg = resp.json().get('error',{}).get('message', f'HTTP {resp.status_code}')
                except: err_msg = f'HTTP {resp.status_code}'
                return jsonify({'error': err_msg}), resp.status_code
            data = resp.json()
            text = data['candidates'][0]['content']['parts'][0]['text']
            return jsonify({'content': text})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    else:
        # Groq por defecto
        url = 'https://api.groq.com/openai/v1/chat/completions'
        model = 'llama-3.3-70b-versatile'
        try:
            resp = http_req.post(url,
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': model, 'messages': full_messages, 'max_tokens': 1500, 'temperature': 0.7},
                timeout=30)
            if not resp.ok:
                try: err_msg = resp.json().get('error',{}).get('message', f'HTTP {resp.status_code}')
                except: err_msg = f'HTTP {resp.status_code}'
                return jsonify({'error': err_msg}), resp.status_code
            return jsonify({'content': resp.json()['choices'][0]['message']['content']})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    is_local = port == 5050
    if is_local:
        print("\n" + "="*50)
        print("  MarketIntel — Servidor iniciado")
        print("  Abre tu navegador en:")
        print("  http://localhost:5050")
        print("="*50 + "\n")
    app.run(host=os.environ.get('MARKETINTEL_HOST', '127.0.0.1'), port=port, debug=False)
