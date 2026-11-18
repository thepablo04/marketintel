"""Timestamped, bounded market reports. Never substitute sample or stale observations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime, timedelta, timezone
from html import unescape
from io import BytesIO
from urllib.parse import quote
from zoneinfo import ZoneInfo
import math
import re
import threading
import time

from marketintel_pulse import market_session
from marketintel_report_sources import fetch_report_breadth, fetch_watchlist_calendar

NY = ZoneInfo('America/New_York')
UTC = timezone.utc
MAG7 = (('NVDA', 'Nvidia'), ('MSFT', 'Microsoft'), ('AAPL', 'Apple'), ('AMZN', 'Amazon'),
        ('GOOGL', 'Alphabet'), ('META', 'Meta'), ('TSLA', 'Tesla'))
_HEADERS = {'User-Agent': 'Mozilla/5.0 MarketIntel/1.0', 'Accept': 'application/json,text/html,text/csv'}
_CACHE = {}
_LOCK = threading.RLock()


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _stamp(value):
    try:
        if isinstance(value, (int, float)):
            if value > 1e12:
                value /= 1000
            return datetime.fromtimestamp(value, UTC)
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _iso(value):
    return value.astimezone(UTC).isoformat() if value else None


def _ticker(value):
    value = str(value).strip().upper().replace('.', '-')
    return value if re.fullmatch(r'[A-Z0-9][A-Z0-9^-]{0,14}', value) else None


def _fetch(requests, url, params=None, *, json=True, ttl=60):
    # Cache is scoped to the HTTP adapter (also makes offline fixtures isolated).
    key = (id(requests), url, tuple(sorted((params or {}).items())), json)
    with _LOCK:
        saved = _CACHE.get(key)
        if saved and time.monotonic()-saved[0] < ttl:
            return saved[1]
    response = requests.get(url, params=params, headers=_HEADERS, timeout=4)
    response.raise_for_status()
    data = response.json() if json else response.text
    with _LOCK:
        if len(_CACHE) > 200:
            _CACHE.clear()
        _CACHE[key] = (time.monotonic(), data)
    return data


def _parallel(function, items, workers=8):
    def safe(item):
        try:
            return item, function(item)
        except Exception:
            return item, None
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(items)))) as executor:
        return dict(executor.map(safe, items))


def _chart(requests, symbol):
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol, safe='')
    raw = _fetch(requests, url, {'range': '5d', 'interval': '5m', 'includePrePost': 'true'}, ttl=45)
    results = (raw.get('chart') or {}).get('result') or []
    return results[0] if results else {}


def _bars(chart):
    indicator = ((chart.get('indicators') or {}).get('quote') or [{}])[0]
    values = indicator.get('close') or []
    result = []
    for stamp, price in zip(chart.get('timestamp') or [], values):
        date, price = _stamp(stamp), _number(price)
        if date and price is not None and price > 0:
            result.append((date, price))
    return sorted(result)


def _last_bar(chart, begin, end, freshness=timedelta(minutes=20)):
    seconds = {'1m':60, '5m':300}.get((chart.get('meta') or {}).get('dataGranularity', '5m'))
    if seconds is None:
        return None
    rows = []
    for date, price in _bars(chart):
        # The irregular terminal point is a quote, not a candle start. Adding
        # five minutes would falsely make its timestamp and freshness newer.
        completed = date+timedelta(seconds=seconds) if date.timestamp()%seconds == 0 else date
        if date >= begin and completed <= end:
            rows.append((completed,price))
    if not rows:
        return None
    date, price = rows[-1]
    return (date, price) if end-date <= freshness else None


def _missing(symbol, label, reason, unit='USD'):
    return {'ticker': symbol, 'label': label, 'price': None, 'previous': None,
            'change': None, 'change_pct': None, 'unit': unit, 'status': 'unavailable',
            'source': 'Yahoo Finance', 'source_url': 'https://finance.yahoo.com/quote/'+quote(symbol, safe=''),
            'as_of': None, 'reason': reason}


def _quote(chart, symbol, label, kind, session, cutoff, *, future=False, gold=False):
    result = _missing(symbol, label, 'No se recibió una cotización verificable para esta ventana.', 'pts' if future or symbol.startswith('^') else 'USD')
    if not chart:
        return result
    meta = chart.get('meta') or {}
    if str(meta.get('symbol', '')).upper() != symbol.upper():
        result['reason'] = 'La fuente no identifica el activo solicitado.'
        return result
    if meta.get('currency') != 'USD':
        result['reason'] = 'La moneda de la cotización no se pudo verificar como USD.'
        return result
    opening, closing = _stamp(session['open_at']), _stamp(session['close_at'])
    day = cutoff.astimezone(NY).date()
    baseline = _number(meta.get('previousClose'))
    # previousClose belongs to the latest quote session, unlike chartPreviousClose
    # which can refer to the first day of the five-day chart.
    current_period = ((meta.get('currentTradingPeriod') or {}).get('regular') or {})
    period_end = _stamp(current_period.get('end'))
    if not period_end or period_end.astimezone(NY).date() != day:
        result['reason'] = 'La referencia anterior no corresponde a la sesión solicitada.'
        return result
    price, date = None, None
    if gold:
        observed = _last_bar(chart, datetime.combine(day, dtime(0), NY).astimezone(UTC), cutoff)
        if observed:
            date, price = observed
    elif kind == 'opening':
        observed = _last_bar(chart, datetime.combine(day, dtime(4), NY).astimezone(UTC), cutoff)
        if observed:
            date, price = observed
    else:
        date = _stamp(meta.get('regularMarketTime'))
        price = _number(meta.get('regularMarketPrice'))
        if not date or not closing-timedelta(minutes=2) <= date <= min(cutoff, closing+timedelta(minutes=2)):
            date, price = None, None
    if price is None or price <= 0 or baseline is None or baseline <= 0:
        return result
    result.update(price=price, previous=baseline, change=round(price-baseline, 6),
                  change_pct=round((price/baseline-1)*100, 6), as_of=_iso(date), status='ok',
                  reason=None, delay_note='La fuente puede llevar retraso. Se muestra la hora del dato.',
                  baseline_label='Referencia previa del mismo contrato según Yahoo' if future or gold else 'Cierre regular anterior')
    if gold:
        result['unit'] = 'USD/onza'
        result['instrument'] = 'Futuro de oro GC, no precio al contado XAU/USD'
    if kind == 'closing' and not gold and not future:
        after = _last_bar(chart, closing, cutoff)
        if after:
            post_at, post_price = after
            result.update(post_price=post_price, post_as_of=_iso(post_at),
                          post_change=round(post_price-price, 6), post_change_pct=round((post_price/price-1)*100, 6))
    return result


def _breadth(universe, quotes, known, kind, session, cutoff, label):
    values = universe.get('symbols',[]) if universe else []
    result = {'label':label,'total':len(values) or None,'valid':0,'up':0,'down':0,'unchanged':0,
              'missing':len(values) or None,'status':'unavailable','as_of':_iso(cutoff),
              'source':universe.get('source') if universe else 'Composición no disponible',
              'note':'La muestra parcial no se extrapola al índice completo.'}
    opening, closing = _stamp(session['open_at']), _stamp(session['close_at'])
    for symbol in values:
        row = known.get(symbol)
        if row and row.get('status')=='ok':
            price, prior, stamp = row['price'], row['previous'], _stamp(row['as_of'])
        else:
            row = quotes.get(symbol) or {}
            price, prior, stamp = _number(row.get('price')), _number(row.get('previous')), _stamp(row.get('as_of'))
        if price is None or prior is None or price<=0 or prior<=0 or not stamp:
            continue
        if kind=='opening':
            if not datetime.combine(cutoff.astimezone(NY).date(),dtime(4),NY).astimezone(UTC) <= stamp <= cutoff or cutoff-stamp>timedelta(minutes=20):
                continue
        elif not closing-timedelta(minutes=2)<=stamp<=min(cutoff,closing+timedelta(minutes=2)):
            continue
        result['valid']+=1
        # Flat is measured at the precision returned by the provider.
        field = 'up' if price>prior else 'down' if price<prior else 'unchanged'
        result[field]+=1
    if values:
        result['missing']=len(values)-result['valid']
        result['status']='ok' if result['valid']==len(values) else 'partial' if result['valid'] else 'unavailable'
    result['coverage_pct']=round(result['valid']/len(values)*100,2) if values else None
    return result


_MONTHS = {name:i for i,name in enumerate(('january','february','march','april','may','june','july','august','september','october','november','december'),1)}

def _bls_release(page, cutoff, title):
    text = unescape(re.sub(r'<[^>]+>',' ',page)); text = re.sub(r'\s+',' ',text)
    # Require a real embargo publication line, never the month measured or fetched.
    match = re.search(r'(?:embargoed until|for release at).{0,80}?(\d{1,2}):(\d{2})\s*(a\.m\.|p\.m\.).{0,100}?([A-Z][a-z]+)\s+(\d{1,2}),?\s+(20\d{2})',text,re.I)
    if not match: return None
    hour, minute, ampm, month, day, year = match.groups()
    month = _MONTHS.get(month.lower())
    if not month:return None
    hour=int(hour)%12+(12 if ampm.lower().startswith('p') else 0)
    try:
        published=datetime(int(year),month,int(day),hour,int(minute),tzinfo=NY).astimezone(UTC)
    except ValueError:
        return None
    if published.astimezone(NY).date()!=cutoff.astimezone(NY).date() or published>cutoff:return None
    heading = r'CONSUMER PRICE INDEX' if title == 'CPI' else r'THE EMPLOYMENT SITUATION'
    period = re.search(heading + r'\s*[-–—]\s*([A-Z]+)\s+(20\d{2})', text, re.I)
    if not period or period.group(1).lower() not in _MONTHS:
        return None
    measured_month = _MONTHS[period.group(1).lower()]
    measured = f'{period.group(2)}-{measured_month:02d}-01'
    prior_month = list(_MONTHS)[(measured_month-2) % 12]
    months_es = ('enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre')
    period_label = months_es[measured_month-1]+' '+period.group(2)
    prior_label = months_es[(measured_month-2) % 12]
    previous = None
    if title=='CPI':
        body = text[period.end():]
        sentence = re.split(r'\.(?!\d)|(?<!\d)\.', body, maxsplit=1)[0]
        reading = re.search(r'(?:all items index|consumer price index for all urban consumers).{0,150}?\b(rose|increased|declined|decreased|fell)\s+(\d+(?:\.\d+)?)\s+percent',sentence,re.I)
        if reading and re.search(r'seasonally adjusted', sentence, re.I):
            change = float(reading.group(2)) * (-1 if reading.group(1).lower() in ('declined','decreased','fell') else 1)
            value = f'{change:g}% mensual, ajustado por estacionalidad · {period_label}'
            prior = re.search(r'after\s+(rising|increasing|declining|decreasing|falling)\s+(\d+(?:\.\d+)?)\s+percent\s+in\s+'+prior_month+r'\b', sentence, re.I)
            if prior:
                old = float(prior.group(2)) * (-1 if prior.group(1).lower() in ('declining','decreasing','falling') else 1)
                previous = f'{old:g}% mensual, ajustado por estacionalidad · {prior_label}'
            explanation = ('Los precios de esta cesta '+('subieron' if change>0 else 'bajaron' if change<0 else 'se mantuvieron')+' frente al mes anterior. Es la variación mensual ajustada por estacionalidad, no la inflación interanual. Sin consenso verificado no se califica como sorpresa; este dato por sí solo no decide una bajada de tasas.')
        else:
            value = 'Consultar comunicado oficial; no se pudo verificar la cifra mensual y su base.'
            explanation = 'La publicación de inflación de hoy está confirmada. La cifra mensual no se extrajo con una base verificable; consulta el comunicado antes de interpretarla.'
    else:
        reading=re.search(r'total nonfarm payroll employment\s+(increased|rose|declined|decreased|fell)\s+(?:by\s+)?(\d[\d,]*)\s+in\s+'+period.group(1)+r'\b',text,re.I)
        value=(('-' if reading.group(1).lower() in ('declined','decreased','fell') else '+')+reading.group(2)+' puestos en el mes · '+period_label) if reading else 'Consultar comunicado oficial'
        revision = re.search(r'change(?: in total nonfarm payroll employment)? for\s+'+prior_month+r'\s+was revised.{0,120}?from\s+([+-]?[\d,]+)\s+to\s+([+-]?[\d,]+)',text,re.I)
        if revision:
            previous = revision.group(2)+' puestos en el mes · '+prior_label+' (cifra revisada del comunicado actual)'
        explanation='NFP mide el cambio neto de puestos en nómina respecto al mes anterior, no personas únicas. Un saldo negativo sigue siendo pérdida de puestos aunque mejore frente a otra pérdida mayor. Desempleo, salarios y revisiones ayudan a interpretarlo; sin consenso verificado no se atribuye una sorpresa.'
    return {'title':title+' · publicación de hoy','actual':value,'consensus':None,'previous':previous,'period':measured,
            'explanation':explanation,'published_at':_iso(published),'source':'BLS',
            'source_url':'https://www.bls.gov/news.release/'+('cpi' if title=='CPI' else 'empsit')+'.htm'}


def _macro(requests, cutoff):
    def read(name):
        url='https://www.bls.gov/news.release/'+('cpi' if name=='CPI' else 'empsit')+'.htm'
        return _bls_release(_fetch(requests,url,json=False,ttl=60),cutoff,name)
    return [v for v in _parallel(read,['CPI','NFP'],2).values() if v]


def _watchlist_reports(requests, tickers, cutoff, known, fmp_key=''):
    if not tickers:return []
    # Source workload is bounded; unchecked symbols remain explicitly unverified.
    inspected=tickers[:12]
    keywords=re.compile(r'\b(earnings|quarterly results|financial results|results for|guidance|outlook|preliminary results|reports? (?:first|second|third|fourth|q[1-4]))\b',re.I)
    def read(ticker):
        data=_fetch(requests,'https://query1.finance.yahoo.com/v1/finance/search',
                    {'q':ticker,'quotesCount':0,'newsCount':12,'enableFuzzyQuery':'false'},ttl=60)
        records=[]
        for item in data.get('news') or []:
            title=str(item.get('title') or '')[:400]
            related=[_ticker(v) for v in item.get('relatedTickers') or []]
            stamp=_stamp(item.get('providerPublishTime'))
            url=str(item.get('link') or '')
            if ticker not in related or not keywords.search(title) or not stamp or not url.startswith('https://'):
                continue
            if stamp.astimezone(NY).date()!=cutoff.astimezone(NY).date() or stamp>cutoff:
                continue
            preview=bool(re.search(r'\b(preview|will report|to report|scheduled|what to expect|sets .{0,25}date)\b',title,re.I))
            records.append({'ticker':ticker,'title':title,'status':'unverified' if preview else 'published','published_at':_iso(stamp),
                            'summary':('Noticia previa sobre futuros resultados. La fecha del reporte y su hora exacta no están confirmadas en este titular.' if preview else
                                       'Noticia de resultados o previsiones relacionada con esta empresa. La hora es la del titular, no necesariamente la del comunicado original. No se deducen cifras ni consenso del titular.'),
                            'actual':None,'consensus':None,'source':str(item.get('publisher') or 'Yahoo Finance')[:150],
                            'source_url':url,'publication_kind':'news_about_results'})
        return sorted(records,key=lambda item:item['published_at'],reverse=True)[:2]
    fetched=_parallel(read,inspected,6)
    output=[]
    for ticker in tickers:
        records=fetched.get(ticker)
        if records:
            for row in records:
                q=known.get(ticker) or {}
                stamp=_stamp(row['published_at']);post_at=_stamp(q.get('post_as_of'))
                if q.get('post_price') is not None and post_at and post_at>=stamp:
                    row.update(price=q['price'],post_price=q['post_price'],post_as_of=q['post_as_of'],
                               post_change_pct=q['post_change_pct'])
                output.append(row)
        else:
            output.append({'ticker':ticker,'title':'Resultados sin confirmar','status':'unverified','published_at':None,
                           'actual':None,'consensus':None,'source':'Yahoo Finance · búsqueda de noticias',
                           'summary':('No se recibió una fuente verificable de resultados hasta el corte. Esto no confirma que no haya publicaciones.' if ticker in inspected else
                                      'No se consultó esta empresa en esta generación para mantener acotado el tiempo de respuesta. Su estado queda sin verificar.')})
    try:
        calendar=fetch_watchlist_calendar(requests,tickers,cutoff,fmp_key=fmp_key)
    except Exception:
        calendar=[]
    for event in calendar:
        ticker=event.get('ticker')
        if ticker not in tickers or any(row['ticker']==ticker and row['status']=='published' for row in output):
            continue
        output=[row for row in output if row['ticker']!=ticker]
        output.append(event)
    return output


def explain_report(report):
    """Connect observed facts; never infer causation or extrapolate missing stocks."""
    def fmt(value, signed=False):
        number = _number(value)
        if number is None:
            return 'sin dato'
        return ((('+' if number>0 else '') if signed else '')+f'{number:,.2f}').replace(',','~').replace('.',',').replace('~','.')
    closing=report.get('kind')=='closing'
    scope='índices' if closing else 'futuros'
    valid=[q for q in (report.get('quotes') or [])[:2]
           if q.get('status')=='ok' and _number(q.get('change_pct')) is not None]
    points=[]
    if len(valid)==2:
        a,b=valid
        av,bv=a['change_pct'],b['change_pct']
        if av>0 and bv>0:
            headline='Los '+scope+(' cerraron al alza.' if closing else ' avanzan.')
            title='S&P 500 y Nasdaq 100 acompañan la subida'
            comparison='El Nasdaq 100 registra un avance mayor.' if bv>av else 'El S&P 500 registra un avance mayor.' if av>bv else 'Sus avances son similares a la precisión disponible.'
        elif av<0 and bv<0:
            headline='Los '+scope+(' cerraron a la baja.' if closing else ' retroceden.')
            title='Los dos índices muestran caídas'
            comparison='La caída es mayor en el Nasdaq 100.' if bv<av else 'La caída es mayor en el S&P 500.' if av<bv else 'Sus caídas son similares a la precisión disponible.'
        elif av==0 and bv==0:
            headline='Los '+scope+' se mantienen sin cambios.'
            title='Las dos referencias se mantienen estables'
            comparison='No muestran variación en la precisión suministrada por la fuente.'
        else:
            headline='Los '+scope+' muestran movimientos distintos.'
            title='La dirección de los índices no es uniforme'
            comparison='Conviene leer cada referencia por separado: no hay una subida o caída común de ambos.'
        index_text='S&P 500: '+fmt(av,True)+'%; Nasdaq 100: '+fmt(bv,True)+'%. '+comparison
    elif valid:
        headline='Falta una referencia para completar la lectura.'
        title='La comparación entre índices está incompleta'
        index_text=valid[0]['label']+' muestra '+fmt(valid[0]['change_pct'],True)+'%. La otra referencia no tiene una cotización válida para este corte.'
    else:
        headline='No hay cotizaciones suficientes para resumir el mercado.'
        title='Faltan las dos referencias del mercado'
        index_text='No se interpreta la dirección del S&P 500 ni del Nasdaq 100 con precios ausentes o de otra ventana.'
    gold=next((q for q in report.get('quotes',[]) if q.get('ticker')=='GC=F' and q.get('status')=='ok'),None)
    if gold and _number(gold.get('change_pct')) is not None:
        index_text+=' El futuro del oro '+('sube ' if gold['change_pct']>0 else 'baja ' if gold['change_pct']<0 else 'no cambia: ')+fmt(abs(gold['change_pct']))+'%.'
    points.append({'title':title,'text':index_text})
    seven=[q for q in report.get('magnificent_seven',[]) if q.get('status')=='ok' and _number(q.get('change_pct')) is not None]
    up=[q for q in seven if q['change_pct']>0];down=[q for q in seven if q['change_pct']<0]
    mixed=bool(up and down)
    if seven:
        if len(seven)==7:
            seven_text=f'{len(up)} de las siete suben, {len(down)} bajan y {7-len(up)-len(down)} no cambian.'
        else:
            seven_text=f'De {len(seven)} con datos, {len(up)} suben y {len(down)} bajan. Faltan {7-len(seven)} cotizaciones; no se completa ese grupo con precios anteriores.'
        if up:
            best=max(up,key=lambda q:q['change_pct']);seven_text+=' '+str(best.get('ticker'))+' destaca al alza ('+fmt(best['change_pct'],True)+'%).'
        if down:
            worst=min(down,key=lambda q:q['change_pct']);seven_text+=' '+str(worst.get('ticker'))+' registra la mayor caída del grupo ('+fmt(worst['change_pct'],True)+'%).'
        seven_title='Las grandes acciones no se mueven todas igual' if mixed else 'Así participan las siete magníficas'
    else:
        seven_title='Las siete todavía no tienen datos comparables'
        seven_text='No hay precios válidos para resumir este grupo en la ventana del reporte.'
    points.append({'title':seven_title,'text':seven_text})
    breadth=report.get('breadth') or []
    incomplete=not breadth or any(not row.get('total') or row.get('valid',0)<row['total'] for row in breadth)
    pieces=[]
    for row in breadth:
        total,observed=row.get('total'),row.get('valid',0)
        if total:
            pieces.append(str(row.get('label'))+': '+str(observed)+'/'+str(total)+' valores ('+fmt(observed/total*100)+'% de cobertura)')
        else:
            pieces.append(str(row.get('label'))+': composición sin verificar')
    coverage='; '.join(pieces)+'.' if pieces else 'No hay una composición y muestra verificables de los índices.'
    coverage+=(' Los conteos describen solo los valores observados; falta información para cerrar el balance del conjunto.' if incomplete else
               'Los conteos cubren el universo consultado. El índice pondera sus componentes; el número de acciones no equivale al aporte en puntos.')
    points.append({'title':'La participación tiene cobertura parcial' if incomplete else 'La participación cubre el universo consultado','text':coverage})
    if mixed and len(valid)==2 and all(q['change_pct']>0 for q in valid):
        synthesis='Los '+scope+' suben y las siete van divididas. Las empresas no pesan igual en cada índice.'
    elif mixed and len(valid)==2 and all(q['change_pct']<0 for q in valid):
        synthesis='Los '+scope+' bajan y algunas de las siete suben. Las empresas no pesan igual en cada índice.'
    else:
        synthesis='La lectura conecta las referencias de los índices con las acciones que tienen datos válidos al corte.'
    if incomplete:
        synthesis+=' La cobertura incompleta limita la conclusión sobre el conjunto.'
    macro=report.get('macro') or []
    if macro:
        item=macro[0]
        points.insert(0,{'title':str(item.get('title') or 'Publicación macro confirmada'),
                         'text':'Resultado: '+str(item.get('actual') or 'consultar comunicado')+'. '+('Sin consenso verificado no se califica como sorpresa.' if item.get('consensus') is None else 'Consenso: '+str(item['consensus'])+'.')})
        # Three takeaways fit the approved overview. The complete seven-company
        # interpretation remains on its own page and in structured analysis.
        overview=[points[0],points[1],points[-1]]
    else:
        overview=points
    return {'headline':headline,'key_points':overview,'synthesis':synthesis,
            'coverage_note':coverage,'seven_title':seven_title,'seven_text':seven_text}


def build_report(kind, watchlist, *, requests_module, fmp_key='', fred_key='', now=None):
    if kind not in ('opening','closing'):
        raise ValueError('Tipo de reporte no válido.')
    if not isinstance(watchlist, (list, tuple)):
        raise ValueError('La watchlist debe ser una lista de símbolos.')
    tickers=list(dict.fromkeys(value for raw in watchlist if (value:=_ticker(raw))))
    if len(tickers)>200:
        raise ValueError('La watchlist supera el máximo de 200 símbolos por reporte.')
    now=now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError('La hora del reporte debe incluir su zona horaria.')
    now=now.astimezone(UTC);local=now.astimezone(NY)
    session=market_session(now)
    if not session.get('calendar_verified'):
        raise ValueError('No se pudo verificar el calendario bursátil. Reintenta antes de generar el reporte.')
    if not session.get('open_at'):
        raise ValueError('Hoy no hay sesión regular de Nueva York; no se genera un reporte de otra fecha como si fuera de hoy.')
    opening,closing=_stamp(session['open_at']),_stamp(session['close_at'])
    close_cut=datetime.combine(local.date(),dtime(17),NY).astimezone(UTC)
    if kind=='closing' and now<close_cut:
        raise ValueError('El reporte de sesión está disponible desde las 17:00 de Nueva York.')
    if kind=='opening' and not datetime.combine(local.date(),dtime(4),NY).astimezone(UTC)<=now<opening:
        raise ValueError('El reporte de apertura se genera durante el premercado, desde las 04:00 y antes de la apertura de Nueva York.')
    cutoff=close_cut if kind=='closing' else now
    symbols=['ES=F','NQ=F','GC=F'] if kind=='opening' else ['^GSPC','^NDX','GC=F']
    wanted=list(dict.fromkeys(symbols+[t for t,_ in MAG7]+tickers[:12]))
    # All independent provider work runs concurrently and stays bounded.
    tasks={'breadth':lambda:fetch_report_breadth(requests_module,kind,session,cutoff,now=now,fmp_key=fmp_key),
           'charts':lambda:_parallel(lambda t:_chart(requests_module,t),wanted,8),
           'macro':lambda:_macro(requests_module,cutoff)}
    if kind=='closing':tasks['watch']=lambda:_watchlist_reports(requests_module,tickers,cutoff,{},fmp_key=fmp_key)
    results=_parallel(lambda name:tasks[name](),list(tasks),4)
    charts=results.get('charts') or {}
    known={}
    for ticker,name in MAG7:
        q=_quote(charts.get(ticker),ticker,name,kind,session,cutoff)
        q['name']=name;known[ticker]=q
    market=[]
    for symbol,label in zip(symbols,(['S&P 500 · futuro ES','Nasdaq 100 · futuro NQ','Oro · futuro GC'] if kind=='opening' else ['S&P 500 · índice al contado','Nasdaq 100 · índice al contado','Oro · futuro GC'])):
        market.append(_quote(charts.get(symbol),symbol,label,kind,session,cutoff,future=symbol in ('ES=F','NQ=F'),gold=symbol=='GC=F'))
    macro=results.get('macro') or []
    for publication in macro:
        publication['market_reaction']=[]
        published=_stamp(publication.get('published_at'))
        for q in market[:2] if kind=='opening' else []:
            after_at=_stamp(q.get('as_of'))
            if not published or not after_at or q.get('status')!='ok' or after_at<=published:
                continue
            before=_last_bar(charts.get(q['ticker']) or {},published-timedelta(minutes=30),published)
            if before:
                before_at,before_price=before
                publication['market_reaction'].append({'label':q['label'],'before':before_price,'before_at':_iso(before_at),
                    'price':q['price'],'as_of':q['as_of'],'change':round(q['price']-before_price,6),'unit':q['unit'],'source':q['source']})
        publication['market_reaction_note']='La comparación temporal no prueba que la publicación sea la única causa del movimiento.' if publication['market_reaction'] else 'No hay una ventana anterior y posterior verificada para atribuir una reacción a esta publicación.'
    breadth=results.get('breadth') or [_breadth(None,{},known,kind,session,cutoff,label) for label in ('S&P 500','Nasdaq 100')]
    for observation in breadth:
        if not observation.get('valid'):
            observation.update(up=None,down=None,unchanged=None)
    watch=results.get('watch') or []
    # Attach after-close quotes only if they follow the report's article timestamp.
    for row in watch:
        symbol=row['ticker'];q=known.get(symbol)
        if q is None and symbol in charts:
            q=_quote(charts.get(symbol),symbol,symbol,kind,session,cutoff)
        stamp,post_at=_stamp(row.get('published_at')),_stamp((q or {}).get('post_as_of'))
        if q and stamp and post_at and post_at>=stamp:
            row.update(price=q['price'],post_price=q['post_price'],post_as_of=q['post_as_of'],post_change_pct=q['post_change_pct'])
            row.update(close_price=q['price'],after_hours_price=q['post_price'],after_hours_as_of=q['post_as_of'],
                       after_hours_change_pct=q['post_change_pct'],after_hours_change=q['post_price']-q['price'])
    warnings=[]
    if any(q['status']!='ok' for q in market):warnings.append('Faltan cotizaciones de referencia verificables para esta ventana; no se sustituyen con precios de otra sesión.')
    if any(row['status']!='ok' for row in breadth):warnings.append('La participación tiene cobertura parcial o no disponible. No se extrapola la muestra a todo el índice.')
    if kind=='closing' and not tickers:warnings.append('La watchlist de este navegador está vacía; no se sustituyó por una lista de ejemplo.')
    if len(tickers)>12:warnings.append('La verificación individual de noticias cubrió hasta 12 empresas por generación; las demás quedan sin confirmar.')
    if kind=='closing' and any(r['status']=='unverified' for r in watch):warnings.append('No se pudo confirmar la ausencia de resultados en toda la watchlist. Los estados sin verificar no equivalen a ausencia de publicaciones.')
    partial=bool(warnings) or any(r['status']!='ok' for r in known.values())
    report={'kind':kind,'report_version':'6.5.2','title':'Reporte de apertura' if kind=='opening' else 'Resumen de sesión · 17:00 NY',
            'status':'partial' if partial else 'ok','session_date':session['date'],'generated_at':_iso(now),
            'cutoff_at':_iso(cutoff),'session':{'open_at':session['open_at'],'close_at':session['close_at'],'previous_date':session.get('previous_date')},
            'quotes':market,'breadth':breadth,'magnificent_seven':list(known.values()),
            'macro':macro,'watchlist_reports':watch,'watchlist':tickers,'warnings':warnings,
            'notes':['Los precios y titulares pueden llevar retraso; se muestran las horas recibidas.',
                     'Los futuros ES/NQ y GC no son los índices al contado ni oro XAU/USD.',
                     'El consenso no se estima cuando no hay una fuente verificable.']}
    report['analysis']=explain_report(report)
    report['summary']=[point['title']+'. '+point['text'] for point in report['analysis']['key_points']]
    report['summary'].append(report['analysis']['synthesis'])
    return report


def render_report_pdf(report):
    """Render the exact report snapshot with the approved visual layout."""
    from marketintel_report_pdf import render_report_pdf as render
    return render(report)
