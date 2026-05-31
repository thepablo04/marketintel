from flask import Flask, jsonify, send_file
from flask_cors import CORS
import yfinance as yf
import traceback
import os

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return send_file('index.html')

@app.route('/stock/<ticker>')
def get_stock(ticker):
    try:
        ticker = ticker.upper().strip()
        t = yf.Ticker(ticker)
        info = t.info

        if not info or (info.get('regularMarketPrice') is None and info.get('currentPrice') is None):
            return jsonify({'error': f'Ticker "{ticker}" no encontrado'}), 404

        hist = t.history(period="1y")

        price = info.get('currentPrice') or info.get('regularMarketPrice')
        prev_close = info.get('previousClose') or info.get('regularMarketPreviousClose')
        change = round(price - prev_close, 2) if price and prev_close else None
        change_pct = round((change / prev_close) * 100, 2) if change and prev_close else None

        sma200 = None
        above_sma200 = None
        if len(hist) >= 20:
            period = min(200, len(hist))
            sma200 = round(hist['Close'].rolling(period).mean().dropna().iloc[-1], 2)
            above_sma200 = bool(price > sma200) if price else None

        atr = None
        if len(hist) >= 14:
            hl = hist['High'] - hist['Low']
            atr = round(hl.rolling(14).mean().iloc[-1], 2)

        rev_growth = None
        try:
            fin = t.financials
            if fin is not None and not fin.empty and 'Total Revenue' in fin.index:
                revs = fin.loc['Total Revenue'].dropna()
                if len(revs) >= 2:
                    rev_growth = round((revs.iloc[0] - revs.iloc[1]) / abs(revs.iloc[1]) * 100, 1)
        except:
            pass

        total_cash = info.get('totalCash')
        op_expenses = None
        runway_months = None
        try:
            inc = t.income_stmt
            if inc is not None and not inc.empty and 'Total Expenses' in inc.index:
                op_expenses = float(inc.loc['Total Expenses'].dropna().iloc[0])
            if total_cash and op_expenses and op_expenses > 0:
                runway_months = round(total_cash / (op_expenses / 12), 1)
        except:
            pass

        return jsonify({
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
            'revenue_growth': rev_growth,
            'profit_margin': round(info['profitMargins'] * 100, 1) if info.get('profitMargins') else None,
            'sma200': sma200,
            'above_sma200': above_sma200,
            'atr': atr,
            'total_cash': total_cash,
            'total_debt': info.get('totalDebt'),
            'runway_months': runway_months,
            'analyst_target': info.get('targetMeanPrice'),
            'analyst_low': info.get('targetLowPrice'),
            'analyst_high': info.get('targetHighPrice'),
            'recommendation': info.get('recommendationKey', '—'),
            'num_analysts': info.get('numberOfAnalystOpinions'),
            'fifty_two_week_low': info.get('fiftyTwoWeekLow'),
            'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
            'dividend_yield': round(info['dividendYield'] * 100, 2) if info.get('dividendYield') else None,
            'short_ratio': info.get('shortRatio'),
        })

    except Exception as e:
        traceback.print_exc()
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
    app.run(host='0.0.0.0', port=port, debug=False)
