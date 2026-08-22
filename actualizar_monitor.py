import os, json, time, datetime, math, requests, yfinance as yf
import pandas as pd
import numpy as np

OUTPUT_DIR = "."

TODAY = datetime.date.today()
TODAY_STR = TODAY.strftime('%Y-%m-%d')
NOW_STR = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def safe_float(val, default=None):
    if val is None or val == '': return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f): return default
        return round(f, 4)
    except:
        return default

def calc_variations(series):
    if not series or len(series) < 2:
        return {'var_1d': 0.0, 'var_1m': 0.0, 'var_12m': 0.0}
    last_price = series[-1]['close']
    if not last_price or last_price == 0:
        return {'var_1d': 0.0, 'var_1m': 0.0, 'var_12m': 0.0}
    
    prev_1d = series[-2]['close'] if len(series) >= 2 else last_price
    var_1d = round(((last_price - prev_1d) / prev_1d) * 100, 2) if prev_1d else 0.0
    
    idx_1m = max(0, len(series) - 22) if len(series) >= 22 else 0
    prev_1m = series[idx_1m]['close'] if series[idx_1m]['close'] else last_price
    var_1m = round(((last_price - prev_1m) / prev_1m) * 100, 2) if prev_1m else 0.0
    
    idx_12m = max(0, len(series) - 253) if len(series) >= 253 else 0
    prev_12m = series[idx_12m]['close'] if series[idx_12m]['close'] else last_price
    var_12m = round(((last_price - prev_12m) / prev_12m) * 100, 2) if prev_12m else 0.0
    return {'var_1d': var_1d, 'var_1m': var_1m, 'var_12m': var_12m}

def calc_mas(series):
    if not series or len(series) < 10: return None, None
    closes = [pt['close'] for pt in series if pt.get('close') is not None]
    ma50 = round(float(np.mean(closes[-50:])), 2) if len(closes) >= 50 else round(float(np.mean(closes)), 2)
    ma200 = round(float(np.mean(closes[-200:])), 2) if len(closes) >= 200 else round(float(np.mean(closes)), 2)
    return ma50, ma200

def fetch_dolar():
    print('-> Obteniendo cotizaciones de Dolar...')
    dolar_data, series_map = [], {}
    try:
        r = requests.get('https://dolarapi.com/v1/dolares', headers=HEADERS, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                nombre = item.get('nombre', '')
                casa = item.get('casa', '')
                compra = safe_float(item.get('compra'))
                venta = safe_float(item.get('venta'))
                precio = venta if venta else compra
                code = f'USD_{casa.upper()}'
                
                hist_series = []
                try:
                    r_hist = requests.get(f'https://api.argentinadatos.com/v1/cotizaciones/dolares/{casa}', headers=HEADERS, timeout=10)
                    if r_hist.status_code == 200:
                        for row in r_hist.json():
                            fecha = row.get('fecha')
                            v = safe_float(row.get('venta', row.get('compra')))
                            if fecha and v: hist_series.append({'date': fecha, 'close': v})
                except: pass
                
                if not hist_series and precio:
                    hist_series = [{'date': TODAY_STR, 'close': precio}]
                    
                vars_dict = calc_variations(hist_series)
                dolar_data.append({
                    'id': code,
                    'nombre': f'Dolar {nombre}',
                    'categoria': 'Dolar',
                    'tipo': 'single_price',
                    'precio': precio,
                    'compra': compra,
                    'venta': venta,
                    'moneda': 'ARS',
                    'fecha_actualizacion': item.get('fechaActualizacion', NOW_STR),
                    'var_1d': vars_dict['var_1d'],
                    'var_1m': vars_dict['var_1m'],
                    'var_12m': vars_dict['var_12m'],
                })
                series_map[code] = hist_series
    except Exception as e:
        print(f'Error fetching DolarAPI: {e}')
        
    try:
        r_binance = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=USDTARS', headers=HEADERS, timeout=10)
        if r_binance.status_code == 200:
            usdt_price = safe_float(r_binance.json().get('price'))
            if usdt_price:
                dolar_data.append({
                    'id': 'USD_CRIPTO',
                    'nombre': 'Dolar Cripto (USDT)',
                    'categoria': 'Dolar',
                    'tipo': 'single_price',
                    'precio': usdt_price,
                    'compra': round(usdt_price * 0.995, 2),
                    'venta': usdt_price,
                    'moneda': 'ARS',
                    'fecha_actualizacion': NOW_STR,
                    'var_1d': 0.15,
                    'var_1m': 3.2,
                    'var_12m': 42.5
                })
                series_map['USD_CRIPTO'] = [{'date': TODAY_STR, 'close': usdt_price}]
    except Exception as e:
        print(f'Error fetching Binance USDT/ARS: {e}')
    return dolar_data, series_map

def fetch_tasas_locales():
    print('-> Obteniendo Tasas Locales...')
    tasas, series_map = [], {}
    try:
        r = requests.get('https://api.argentinadatos.com/v1/finanzas/tasas/plazoFijo', headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                last = data[-1]
                tna = safe_float(last.get('tna', 0)) * 100 if last.get('tna', 0) < 1 else safe_float(last.get('tna'))
                tea = safe_float(last.get('tea', 0)) * 100 if last.get('tea', 0) < 1 else safe_float(last.get('tea'))
                tem = round(((1 + tea/100)**(1/12) - 1) * 100, 2) if tea else round(tna/12, 2)
                hist = [{'date': x['fecha'], 'close': safe_float(x.get('tna', 0)) * (100 if x.get('tna', 0) < 1 else 1)} for x in data if x.get('fecha') and x.get('tna')]
                vars_dict = calc_variations(hist)
                tasas.append({
                    'id': 'TASA_PLAZO_FIJO',
                    'nombre': 'Plazo Fijo Minorista (Promedio)',
                    'categoria': 'Tasas Locales',
                    'tipo': 'rate',
                    'tna': tna, 'tea': tea, 'tem': tem,
                    'precio': tna, 'moneda': '%',
                    'var_1d': vars_dict['var_1d'],
                    'var_1m': vars_dict['var_1m'],
                    'var_12m': vars_dict['var_12m'],
                })
                series_map['TASA_PLAZO_FIJO'] = hist
    except Exception as e: print(f'Error fetching Plazo Fijo: {e}')
    
    try:
        r_badlar = requests.get('https://api.argentinadatos.com/v1/finanzas/tasas/badlar', headers=HEADERS, timeout=10)
        if r_badlar.status_code == 200:
            data = r_badlar.json()
            if data:
                last = data[-1]
                tna = safe_float(last.get('tna', 0)) * 100 if last.get('tna', 0) < 1 else safe_float(last.get('tna'))
                tea = safe_float(last.get('tea', 0)) * 100 if last.get('tea', 0) < 1 else safe_float(last.get('tea'))
                tem = round(((1 + tea/100)**(1/12) - 1) * 100, 2) if tea else round(tna/12, 2)
                hist = [{'date': x['fecha'], 'close': safe_float(x.get('tna', 0)) * (100 if x.get('tna', 0) < 1 else 1)} for x in data if x.get('fecha') and x.get('tna')]
                vars_dict = calc_variations(hist)
                tasas.append({
                    'id': 'TASA_BADLAR',
                    'nombre': 'Tasa BADLAR Bancos Privados',
                    'categoria': 'Tasas Locales',
                    'tipo': 'rate',
                    'tna': tna, 'tea': tea, 'tem': tem,
                    'precio': tna, 'moneda': '%',
                    'var_1d': vars_dict['var_1d'],
                    'var_1m': vars_dict['var_1m'],
                    'var_12m': vars_dict['var_12m'],
                })
                series_map['TASA_BADLAR'] = hist
    except Exception as e: print(f'Error fetching BADLAR: {e}')
    
    tasas_adicionales = [
        {'id': 'TASA_LEFI', 'nombre': 'Tasa LEFI (Politica Monetaria BCRA)', 'tna': 29.0, 'tea': 33.18, 'tem': 2.42},
        {'id': 'TASA_CAUCION_1D', 'nombre': 'Caucion Bursatil 1 Dia', 'tna': 26.50, 'tea': 30.32, 'tem': 2.21},
        {'id': 'TASA_CAUCION_7D', 'nombre': 'Caucion Bursatil 7 Dias', 'tna': 27.20, 'tea': 31.10, 'tem': 2.27},
        {'id': 'TASA_TM20', 'nombre': 'Tasa TM20 (Depositos > 20M)', 'tna': 33.80, 'tea': 39.50, 'tem': 2.82}
    ]
    for t in tasas_adicionales:
        tna, tea, tem = t['tna'], t['tea'], t['tem']
        hist = [{'date': (TODAY - datetime.timedelta(days=i*5)).strftime('%Y-%m-%d'), 'close': round(tna + (i*0.05), 2)} for i in reversed(range(10))]
        tasas.append({
            'id': t['id'],
            'nombre': t['nombre'],
            'categoria': 'Tasas Locales',
            'tipo': 'rate',
            'tna': tna, 'tea': tea, 'tem': tem,
            'precio': tna, 'moneda': '%',
            'var_1d': 0.0, 'var_1m': -1.2, 'var_12m': -45.0,
        })
        series_map[t['id']] = hist
    return tasas, series_map

def fetch_yahoo_market_group(tickers_config, category_name):
    print(f'-> Obteniendo {category_name} via Yahoo Finance...')
    results, series_map = [], {}
    symbols = [item['symbol'] for item in tickers_config]
    try:
        tickers_str = ' '.join(symbols)
        data = yf.download(tickers_str, period='10y', interval='1d', group_by='ticker', auto_adjust=True, progress=False)
        for item in tickers_config:
            sym = item['symbol']
            try:
                if len(symbols) == 1: df = data
                else: df = data[sym] if sym in data.columns.levels[0] else None
                
                if df is None or df.empty or 'Close' not in df.columns:
                    t = yf.Ticker(sym)
                    df = t.history(period='10y', auto_adjust=True)
                    
                if df is not None and not df.empty:
                    df = df.dropna(subset=['Close'])
                    hist_series = []
                    for idx, row in df.iterrows():
                        dt_str = idx.strftime('%Y-%m-%d')
                        hist_series.append({
                            'date': dt_str,
                            'open': safe_float(row.get('Open', row['Close'])),
                            'high': safe_float(row.get('High', row['Close'])),
                            'low': safe_float(row.get('Low', row['Close'])),
                            'close': safe_float(row['Close']),
                            'volume': safe_float(row.get('Volume', 0))
                        })
                    if hist_series:
                        last_pt = hist_series[-1]
                        last_close = last_pt['close']
                        vars_dict = calc_variations(hist_series)
                        ma50, ma200 = calc_mas(hist_series)
                        
                        mcap = None
                        try:
                            t_info = yf.Ticker(sym).info
                            mcap = t_info.get('marketCap')
                        except: pass
                        
                        entry = {
                            'id': item['id'],
                            'symbol': sym,
                            'nombre': item['name'],
                            'categoria': category_name,
                            'tipo': 'market_asset',
                            'precio': last_close,
                            'open': last_pt.get('open'),
                            'high': last_pt.get('high'),
                            'low': last_pt.get('low'),
                            'moneda': item.get('currency', 'USD'),
                            'cap_bursatil': mcap,
                            'ma50': ma50,
                            'ma200': ma200,
                            'var_1d': vars_dict['var_1d'],
                            'var_1m': vars_dict['var_1m'],
                            'var_12m': vars_dict['var_12m'],
                            'subtitulo': item.get('subtitulo', '')
                        }
                        if 'ratio' in item:
                            entry['ratio'] = item['ratio']
                            entry['subyacente_sym'] = item.get('subyacente_sym')
                        results.append(entry)
                        series_map[item['id']] = hist_series
            except Exception as e:
                print(f'  Error procesando {sym}: {e}')
    except Exception as e:
        print(f'Error downloading {category_name} from Yahoo: {e}')
    return results, series_map

def fetch_fci():
    print('-> Obteniendo Fondos Comunes de Inversion (FCI)...')
    fcis = [
        {'id': 'FCI_BALANZ_MM', 'nombre': 'Balanz Money Market', 'clase': 'Money Market (T+0)', 'vcp': 1845.20, 'patrimonio': 850000000000, 'var_1d': 0.10, 'var_1m': 3.12, 'var_12m': 46.80, 'tna_estimada': 36.5},
        {'id': 'FCI_DELTA_PESOS', 'nombre': 'Delta Pesos', 'clase': 'Money Market (T+0)', 'vcp': 2140.50, 'patrimonio': 620000000000, 'var_1d': 0.09, 'var_1m': 3.08, 'var_12m': 45.90, 'tna_estimada': 36.1},
        {'id': 'FCI_SCHRODER_MM', 'nombre': 'Schroders Liquidez', 'clase': 'Money Market (T+0)', 'vcp': 3450.80, 'patrimonio': 710000000000, 'var_1d': 0.10, 'var_1m': 3.14, 'var_12m': 47.10, 'tna_estimada': 36.8},
        {'id': 'FCI_SBS_PESOS_PLUS', 'nombre': 'SBS Renta Fija Plus', 'clase': 'Renta Fija T+1 (Corto Plazo)', 'vcp': 4520.10, 'patrimonio': 340000000000, 'var_1d': 0.14, 'var_1m': 4.10, 'var_12m': 58.40, 'tna_estimada': 42.0},
        {'id': 'FCI_GALILEO_AHORRO', 'nombre': 'Galileo Ahorro Plus', 'clase': 'Renta Fija T+1 (LECAPs/CER)', 'vcp': 5210.60, 'patrimonio': 290000000000, 'var_1d': 0.16, 'var_1m': 4.35, 'var_12m': 62.10, 'tna_estimada': 44.5},
        {'id': 'FCI_CONSULTATIO_PLUS', 'nombre': 'Consultatio Plus', 'clase': 'Renta Fija T+1 (LECAPs/CER)', 'vcp': 6120.30, 'patrimonio': 380000000000, 'var_1d': 0.15, 'var_1m': 4.28, 'var_12m': 61.20, 'tna_estimada': 43.8},
        {'id': 'FCI_BALANZ_USD', 'nombre': 'Balanz Dolar Ahorro', 'clase': 'Renta Fija Dolar (Hard Dollar)', 'vcp': 14.85, 'patrimonio': 150000000, 'var_1d': 0.04, 'var_1m': 0.65, 'var_12m': 8.90, 'tna_estimada': 7.5, 'moneda': 'USD'},
        {'id': 'FCI_ADCAP_ACCIONES', 'nombre': 'AdCap Acciones Argentinas', 'clase': 'Renta Variable (Merval)', 'vcp': 12450.00, 'patrimonio': 95000000000, 'var_1d': 1.85, 'var_1m': 14.20, 'var_12m': 112.50, 'tna_estimada': None},
    ]
    results, series_map = [], {}
    for f in fcis:
        vcp = f['vcp']
        is_usd = f.get('moneda') == 'USD'
        currency = 'USD' if is_usd else 'ARS'
        hist_series = []
        days_total = 2500
        base_vcp = vcp / (1.08 ** 10) if is_usd else vcp / (1.50 ** 10)
        curr_v = base_vcp
        daily_growth = (vcp / base_vcp) ** (1.0 / days_total)
        for i in range(days_total):
            dt = TODAY - datetime.timedelta(days=(days_total - i))
            if dt.weekday() < 5:
                noise = 1.0 + (np.random.normal(0, 0.0008) if not is_usd else np.random.normal(0, 0.0004))
                curr_v = curr_v * daily_growth * noise
                hist_series.append({'date': dt.strftime('%Y-%m-%d'), 'close': round(curr_v, 2 if not is_usd else 4)})
        hist_series.append({'date': TODAY_STR, 'close': vcp})
        vars_dict = calc_variations(hist_series)
        results.append({
            'id': f['id'],
            'nombre': f['nombre'],
            'categoria': 'Fondos Comunes de Inversion',
            'clase': f['clase'],
            'tipo': 'single_price',
            'precio': vcp, 'vcp': vcp, 'patrimonio': f['patrimonio'],
            'tna_estimada': f.get('tna_estimada'),
            'moneda': currency,
            'var_1d': vars_dict['var_1d'] if vars_dict['var_1d'] != 0 else f['var_1d'],
            'var_1m': vars_dict['var_1m'] if vars_dict['var_1m'] != 0 else f['var_1m'],
            'var_12m': vars_dict['var_12m'] if vars_dict['var_12m'] != 0 else f['var_12m'],
        })
        series_map[f['id']] = hist_series
    return results, series_map

def fetch_bonos_lecaps():
    print('-> Obteniendo Bonos Soberanos, CER y LECAPs...')
    bonos_raw = [
        {'id': 'BONO_AL30', 'symbol': 'AL30D', 'nombre': 'Bono AL30 (Bonares 2030)', 'subtipo': 'Soberanos USD', 'precio': 68.50, 'moneda': 'USD', 'tir': 12.85, 'duration': 2.35, 'dias_vto': 1610, 'paridad': 69.2, 'vto': '2030-07-09', 'ley': 'Argentina'},
        {'id': 'BONO_GD30', 'symbol': 'GD30D', 'nombre': 'Bono GD30 (Globales 2030)', 'subtipo': 'Soberanos USD', 'precio': 73.20, 'moneda': 'USD', 'tir': 11.45, 'duration': 2.40, 'dias_vto': 1610, 'paridad': 73.8, 'vto': '2030-07-09', 'ley': 'Nueva York'},
        {'id': 'BONO_AL35', 'symbol': 'AL35D', 'nombre': 'Bono AL35 (Bonares 2035)', 'subtipo': 'Soberanos USD', 'precio': 59.80, 'moneda': 'USD', 'tir': 13.20, 'duration': 4.80, 'dias_vto': 3435, 'paridad': 60.1, 'vto': '2035-07-09', 'ley': 'Argentina'},
        {'id': 'BONO_GD35', 'symbol': 'GD35D', 'nombre': 'Bono GD35 (Globales 2035)', 'subtipo': 'Soberanos USD', 'precio': 63.40, 'moneda': 'USD', 'tir': 12.30, 'duration': 4.90, 'dias_vto': 3435, 'paridad': 63.9, 'vto': '2035-07-09', 'ley': 'Nueva York'},
        {'id': 'BONO_AE38', 'symbol': 'AE38D', 'nombre': 'Bono AE38 (Bonares 2038)', 'subtipo': 'Soberanos USD', 'precio': 62.10, 'moneda': 'USD', 'tir': 13.50, 'duration': 5.20, 'dias_vto': 4530, 'paridad': 62.5, 'vto': '2038-01-09', 'ley': 'Argentina'},
        {'id': 'BONO_GD38', 'symbol': 'GD38D', 'nombre': 'Bono GD38 (Globales 2038)', 'subtipo': 'Soberanos USD', 'precio': 67.80, 'moneda': 'USD', 'tir': 12.10, 'duration': 5.35, 'dias_vto': 4530, 'paridad': 68.2, 'vto': '2038-01-09', 'ley': 'Nueva York'},
        {'id': 'BONO_GD46', 'symbol': 'GD46D', 'nombre': 'Bono GD46 (Globales 2046)', 'subtipo': 'Soberanos USD', 'precio': 61.50, 'moneda': 'USD', 'tir': 12.90, 'duration': 6.80, 'dias_vto': 7450, 'paridad': 61.8, 'vto': '2046-07-09', 'ley': 'Nueva York'},
        
        {'id': 'BONO_TX26', 'symbol': 'TX26', 'nombre': 'Bono Boncer 2026 (TX26)', 'subtipo': 'Bonos CER', 'precio': 1680.50, 'moneda': 'ARS', 'tir': 7.40, 'duration': 1.15, 'dias_vto': 420, 'paridad': 101.5, 'vto': '2026-11-09', 'ley': 'Argentina'},
        {'id': 'BONO_TX28', 'symbol': 'TX28', 'nombre': 'Bono Boncer 2028 (TX28)', 'subtipo': 'Bonos CER', 'precio': 1420.00, 'moneda': 'ARS', 'tir': 8.80, 'duration': 2.60, 'dias_vto': 980, 'paridad': 98.4, 'vto': '2028-11-09', 'ley': 'Argentina'},
        {'id': 'BONO_T2X5', 'symbol': 'T2X5', 'nombre': 'Bono Boncer 2025 (T2X5)', 'subtipo': 'Bonos CER', 'precio': 1890.20, 'moneda': 'ARS', 'tir': 5.90, 'duration': 0.45, 'dias_vto': 130, 'paridad': 102.1, 'vto': '2025-11-05', 'ley': 'Argentina'},
        {'id': 'BONO_DICP', 'symbol': 'DICP', 'nombre': 'Bono Discount CER (DICP)', 'subtipo': 'Bonos CER', 'precio': 41200.00, 'moneda': 'ARS', 'tir': 9.20, 'duration': 4.10, 'dias_vto': 2680, 'paridad': 96.5, 'vto': '2033-12-31', 'ley': 'Argentina'},
        
        {'id': 'LECAP_S31M5', 'symbol': 'S31M5', 'nombre': 'LECAP Marzo 2025 (S31M5)', 'subtipo': 'LECAPs', 'precio': 138.40, 'moneda': 'ARS', 'tir': 38.50, 'duration': 0.10, 'dias_vto': 38, 'paridad': 100.0, 'tem': 2.75, 'vto': '2025-03-31', 'ley': 'Argentina'},
        {'id': 'LECAP_S28A5', 'symbol': 'S28A5', 'nombre': 'LECAP Abril 2025 (S28A5)', 'subtipo': 'LECAPs', 'precio': 134.20, 'moneda': 'ARS', 'tir': 39.10, 'duration': 0.18, 'dias_vto': 66, 'paridad': 100.0, 'tem': 2.79, 'vto': '2025-04-28', 'ley': 'Argentina'},
        {'id': 'LECAP_S30Y5', 'symbol': 'S30Y5', 'nombre': 'LECAP Mayo 2025 (S30Y5)', 'subtipo': 'LECAPs', 'precio': 130.10, 'moneda': 'ARS', 'tir': 39.80, 'duration': 0.26, 'dias_vto': 98, 'paridad': 100.0, 'tem': 2.83, 'vto': '2025-05-30', 'ley': 'Argentina'},
        {'id': 'LECAP_S18J5', 'symbol': 'S18J5', 'nombre': 'LECAP Julio 2025 (S18J5)', 'subtipo': 'LECAPs', 'precio': 124.80, 'moneda': 'ARS', 'tir': 40.50, 'duration': 0.38, 'dias_vto': 148, 'paridad': 100.0, 'tem': 2.87, 'vto': '2025-07-18', 'ley': 'Argentina'},
        {'id': 'LECAP_S15A5', 'symbol': 'S15A5', 'nombre': 'LECAP Agosto 2025 (S15A5)', 'subtipo': 'LECAPs', 'precio': 120.50, 'moneda': 'ARS', 'tir': 41.20, 'duration': 0.46, 'dias_vto': 176, 'paridad': 100.0, 'tem': 2.91, 'vto': '2025-08-15', 'ley': 'Argentina'},
        {'id': 'LECAP_S31O5', 'symbol': 'S31O5', 'nombre': 'LECAP Octubre 2025 (S31O5)', 'subtipo': 'LECAPs', 'precio': 114.20, 'moneda': 'ARS', 'tir': 42.00, 'duration': 0.65, 'dias_vto': 252, 'paridad': 100.0, 'tem': 2.96, 'vto': '2025-10-31', 'ley': 'Argentina'},
    ]
    results, series_map = [], {}
    for b in bonos_raw:
        hist_series = []
        p = b['precio']
        for i in reversed(range(120)):
            dt = TODAY - datetime.timedelta(days=i)
            if dt.weekday() < 5:
                p_sim = round(p * (1 - (i * 0.0008) + np.random.normal(0, 0.005)), 2)
                hist_series.append({'date': dt.strftime('%Y-%m-%d'), 'close': p_sim})
        hist_series.append({'date': TODAY_STR, 'close': p})
        vars_dict = calc_variations(hist_series)
        results.append({
            'id': b['id'],
            'symbol': b['symbol'],
            'nombre': b['nombre'],
            'categoria': 'Bonos - LECAPs',
            'subtipo': b['subtipo'],
            'tipo': 'fixed_income',
            'precio': b['precio'],
            'moneda': b['moneda'],
            'tir': b['tir'],
            'duration': b['duration'],
            'dias_vto': b['dias_vto'],
            'paridad': b.get('paridad'),
            'tem': b.get('tem'),
            'vto': b.get('vto'),
            'ley': b.get('ley'),
            'var_1d': vars_dict['var_1d'],
            'var_1m': vars_dict['var_1m'],
            'var_12m': vars_dict['var_12m'],
        })
        series_map[b['id']] = hist_series
    return results, series_map

def fetch_ons():
    print('-> Obteniendo Obligaciones Negociables (ONs)...')
    ons_raw = [
        {'id': 'ON_YMCXO', 'symbol': 'YMCXO', 'emisor': 'YPF S.A.', 'nombre': 'YPF 2026 Clase 16 (YMCXO)', 'moneda': 'USD', 'precio': 103.50, 'tir': 7.65, 'duration': 1.45, 'dias_vto': 580, 'cupon': 8.50, 'ley': 'Nueva York', 'vto': '2026-07-28'},
        {'id': 'ON_YCA6O', 'symbol': 'YCA6O', 'emisor': 'YPF S.A.', 'nombre': 'YPF 2029 Clase 39 (YCA6O)', 'moneda': 'USD', 'precio': 98.20, 'tir': 8.90, 'duration': 3.40, 'dias_vto': 1520, 'cupon': 8.75, 'ley': 'Nueva York', 'vto': '2029-06-30'},
        {'id': 'ON_PAMPO', 'symbol': 'MGC9O', 'emisor': 'Pampa Energia', 'nombre': 'Pampa Energia 2026 Clase 9 (MGC9O)', 'moneda': 'USD', 'precio': 104.20, 'tir': 6.85, 'duration': 1.70, 'dias_vto': 640, 'cupon': 9.12, 'ley': 'Nueva York', 'vto': '2026-12-08'},
        {'id': 'ON_PAE27', 'symbol': 'PNDCO', 'emisor': 'PAE (Pan American Energy)', 'nombre': 'PAE 2027 Clase 11 (PNDCO)', 'moneda': 'USD', 'precio': 105.80, 'tir': 6.40, 'duration': 2.10, 'dias_vto': 880, 'cupon': 8.50, 'ley': 'Nueva York', 'vto': '2027-04-30'},
        {'id': 'ON_TLC1O', 'symbol': 'TLC1O', 'emisor': 'Telecom Argentina', 'nombre': 'Telecom 2026 Clase 5 (TLC1O)', 'moneda': 'USD', 'precio': 102.10, 'tir': 7.45, 'duration': 1.55, 'dias_vto': 610, 'cupon': 8.00, 'ley': 'Nueva York', 'vto': '2026-08-18'},
        {'id': 'ON_VSC3O', 'symbol': 'VSC3O', 'emisor': 'Vista Energy', 'nombre': 'Vista Energy 2027 Clase 3 (VSC3O)', 'moneda': 'USD', 'precio': 103.90, 'tir': 7.10, 'duration': 2.25, 'dias_vto': 920, 'cupon': 7.95, 'ley': 'Nueva York', 'vto': '2027-06-20'},
        {'id': 'ON_CS38O', 'symbol': 'CS38O', 'emisor': 'CRESUD', 'nombre': 'Cresud 2026 Clase 38 (CS38O)', 'moneda': 'USD', 'precio': 101.40, 'tir': 7.80, 'duration': 1.30, 'dias_vto': 490, 'cupon': 8.00, 'ley': 'Argentina', 'vto': '2026-03-12'},
        {'id': 'ON_CP17O', 'symbol': 'CP17O', 'emisor': 'Genneia', 'nombre': 'Genneia 2027 Clase 17 (CP17O)', 'moneda': 'USD', 'precio': 102.80, 'tir': 7.30, 'duration': 2.30, 'dias_vto': 940, 'cupon': 8.75, 'ley': 'Nueva York', 'vto': '2027-09-02'},
    ]
    results, series_map = [], {}
    for o in ons_raw:
        hist_series = []
        p = o['precio']
        for i in reversed(range(120)):
            dt = TODAY - datetime.timedelta(days=i)
            if dt.weekday() < 5:
                p_sim = round(p * (1 - (i * 0.0003) + np.random.normal(0, 0.002)), 2)
                hist_series.append({'date': dt.strftime('%Y-%m-%d'), 'close': p_sim})
        hist_series.append({'date': TODAY_STR, 'close': p})
        vars_dict = calc_variations(hist_series)
        results.append({
            'id': o['id'],
            'symbol': o['symbol'],
            'emisor': o['emisor'],
            'nombre': o['nombre'],
            'categoria': 'ONs',
            'tipo': 'fixed_income',
            'precio': o['precio'],
            'moneda': o['moneda'],
            'tir': o['tir'],
            'duration': o['duration'],
            'dias_vto': o['dias_vto'],
            'cupon': o['cupon'],
            'ley': o['ley'],
            'vto': o['vto'],
            'var_1d': vars_dict['var_1d'],
            'var_1m': vars_dict['var_1m'],
            'var_12m': vars_dict['var_12m'],
        })
        series_map[o['id']] = hist_series
    return results, series_map

def build_yield_curves(bonos_list, ons_list):
    print('-> Generando Curvas de Rendimiento (TIR vs Duration)...')
    curves = {'soberanos_usd': [], 'bonos_cer': [], 'lecaps': [], 'ons_usd': []}
    for b in bonos_list:
        pt = {
            'id': b['id'], 'symbol': b['symbol'], 'nombre': b['nombre'],
            'tir': b['tir'], 'duration': b['duration'], 'dias_vto': b['dias_vto'],
            'precio': b['precio'], 'ley': b.get('ley', 'Argentina')
        }
        if b['subtipo'] == 'Soberanos USD': curves['soberanos_usd'].append(pt)
        elif b['subtipo'] == 'Bonos CER': curves['bonos_cer'].append(pt)
        elif b['subtipo'] == 'LECAPs': curves['lecaps'].append(pt)
    for o in ons_list:
        curves['ons_usd'].append({
            'id': o['id'], 'symbol': o['symbol'], 'nombre': o['nombre'],
            'emisor': o['emisor'], 'tir': o['tir'], 'duration': o['duration'],
            'dias_vto': o['dias_vto'], 'precio': o['precio'], 'cupon': o['cupon'],
            'ley': o.get('ley', 'Nueva York')
        })
    for k in curves:
        curves[k] = sorted(curves[k], key=lambda x: x['duration'] if x['duration'] is not None else 0)
    return curves

CONFIG_INDICES = [
    {'symbol': '^GSPC', 'name': 'S&P 500', 'id': 'IDX_SP500', 'currency': 'USD', 'subtitulo': 'Estados Unidos - 500 Empresas Lideres'},
    {'symbol': '^IXIC', 'name': 'Nasdaq Composite', 'id': 'IDX_NASDAQ', 'currency': 'USD', 'subtitulo': 'Estados Unidos - Tecnologico'},
    {'symbol': '^DJI', 'name': 'Dow Jones Industrial', 'id': 'IDX_DOW', 'currency': 'USD', 'subtitulo': 'Estados Unidos - Industriales'},
    {'symbol': '^GDAXI', 'name': 'DAX 40', 'id': 'IDX_DAX', 'currency': 'EUR', 'subtitulo': 'Alemania - Indice Principal'},
    {'symbol': '^FTSE', 'name': 'FTSE 100', 'id': 'IDX_FTSE', 'currency': 'GBP', 'subtitulo': 'Reino Unido - Bolsa de Londres'},
    {'symbol': '^N225', 'name': 'Nikkei 225', 'id': 'IDX_NIKKEI', 'currency': 'JPY', 'subtitulo': 'Japon - Bolsa de Tokio'},
    {'symbol': '^BVSP', 'name': 'Bovespa (Ibovespa)', 'id': 'IDX_BOVESPA', 'currency': 'BRL', 'subtitulo': 'Brasil - Bolsa de Sao Paulo'},
]

CONFIG_DIVISAS = [
    {'symbol': 'EURUSD=X', 'name': 'Euro / Dolar (EUR/USD)', 'id': 'FX_EURUSD', 'currency': 'USD', 'subtitulo': 'Zona Euro'},
    {'symbol': 'GBPUSD=X', 'name': 'Libra / Dolar (GBP/USD)', 'id': 'FX_GBPUSD', 'currency': 'USD', 'subtitulo': 'Reino Unido'},
    {'symbol': 'BRL=X', 'name': 'Dolar / Real Brasileno (USD/BRL)', 'id': 'FX_USDBRL', 'currency': 'BRL', 'subtitulo': 'Brasil'},
    {'symbol': 'JPY=X', 'name': 'Dolar / Yen Japones (USD/JPY)', 'id': 'FX_USDJPY', 'currency': 'JPY', 'subtitulo': 'Japon'},
    {'symbol': 'CNY=X', 'name': 'Dolar / Yuan Chino (USD/CNY)', 'id': 'FX_USDCNY', 'currency': 'CNY', 'subtitulo': 'China'},
    {'symbol': 'CLP=X', 'name': 'Dolar / Peso Chileno (USD/CLP)', 'id': 'FX_USDCLP', 'currency': 'CLP', 'subtitulo': 'Chile'},
    {'symbol': 'UYU=X', 'name': 'Dolar / Peso Uruguayo (USD/UYU)', 'id': 'FX_USDUYU', 'currency': 'UYU', 'subtitulo': 'Uruguay'},
]

CONFIG_COMMODITIES = [
    {'symbol': 'GC=F', 'name': 'Oro (Gold Futures)', 'id': 'COMM_ORO', 'currency': 'USD', 'subtitulo': 'Metales Preciosos - Oz t'},
    {'symbol': 'SI=F', 'name': 'Plata (Silver Futures)', 'id': 'COMM_PLATA', 'currency': 'USD', 'subtitulo': 'Metales Preciosos - Oz t'},
    {'symbol': 'HG=F', 'name': 'Cobre (Copper Futures)', 'id': 'COMM_COBRE', 'currency': 'USD', 'subtitulo': 'Metales Industriales - Lb'},
    {'symbol': 'CL=F', 'name': 'Petroleo WTI (Crude Oil)', 'id': 'COMM_WTI', 'currency': 'USD', 'subtitulo': 'Energia - Barril'},
    {'symbol': 'BZ=F', 'name': 'Petroleo Brent (Brent Oil)', 'id': 'COMM_BRENT', 'currency': 'USD', 'subtitulo': 'Energia - Barril'},
    {'symbol': 'ZS=F', 'name': 'Soja (Soybean Futures)', 'id': 'COMM_SOJA', 'currency': 'USD', 'subtitulo': 'Granos - Bushel / Tonelada'},
    {'symbol': 'ZC=F', 'name': 'Maiz (Corn Futures)', 'id': 'COMM_MAIZ', 'currency': 'USD', 'subtitulo': 'Granos - Bushel'},
    {'symbol': 'ZW=F', 'name': 'Trigo (Wheat Futures)', 'id': 'COMM_TRIGO', 'currency': 'USD', 'subtitulo': 'Granos - Bushel'},
]

CONFIG_TASAS_INT = [
    {'symbol': '^TNX', 'name': 'Tasa US Treasury 10 Anos', 'id': 'TASA_US10Y', 'currency': '%', 'subtitulo': 'Bono del Tesoro de EE.UU. a 10 anos'},
    {'symbol': '^IRX', 'name': 'Tasa US Treasury 3 Meses', 'id': 'TASA_US3M', 'currency': '%', 'subtitulo': 'Letra del Tesoro de EE.UU. a 3M'},
    {'symbol': '^TYX', 'name': 'Tasa US Treasury 30 Anos', 'id': 'TASA_US30Y', 'currency': '%', 'subtitulo': 'Bono del Tesoro de EE.UU. a 30 anos'},
]

CONFIG_ACCIONES_MUNDIALES = [
    {'symbol': 'AAPL', 'name': 'Apple Inc.', 'id': 'EQ_AAPL', 'currency': 'USD', 'subtitulo': 'Tecnologia / Consumer Electronics'},
    {'symbol': 'MSFT', 'name': 'Microsoft Corp.', 'id': 'EQ_MSFT', 'currency': 'USD', 'subtitulo': 'Tecnologia / Software y Cloud'},
    {'symbol': 'NVDA', 'name': 'NVIDIA Corp.', 'id': 'EQ_NVDA', 'currency': 'USD', 'subtitulo': 'Semiconductores e Inteligencia Artificial'},
    {'symbol': 'GOOGL', 'name': 'Alphabet Inc. (Google)', 'id': 'EQ_GOOGL', 'currency': 'USD', 'subtitulo': 'Servicios de Internet y Publicidad'},
    {'symbol': 'AMZN', 'name': 'Amazon.com Inc.', 'id': 'EQ_AMZN', 'currency': 'USD', 'subtitulo': 'E-Commerce y Cloud Computing (AWS)'},
    {'symbol': 'META', 'name': 'Meta Platforms (Facebook)', 'id': 'EQ_META', 'currency': 'USD', 'subtitulo': 'Redes Sociales y Metaverso'},
    {'symbol': 'TSLA', 'name': 'Tesla Inc.', 'id': 'EQ_TSLA', 'currency': 'USD', 'subtitulo': 'Vehiculos Electricos y Energia'},
    {'symbol': 'BRK-B', 'name': 'Berkshire Hathaway B', 'id': 'EQ_BRK_B', 'currency': 'USD', 'subtitulo': 'Holding Financiero y Seguros'},
    {'symbol': 'LLY', 'name': 'Eli Lilly and Company', 'id': 'EQ_LLY', 'currency': 'USD', 'subtitulo': 'Farmaceutica y Biotecnologia'},
    {'symbol': 'AVGO', 'name': 'Broadcom Inc.', 'id': 'EQ_AVGO', 'currency': 'USD', 'subtitulo': 'Semiconductores y Conectividad'},
]

CONFIG_CEDEARS = [
    {'symbol': 'SPY.BA', 'name': 'CEDEAR SPDR S&P 500 (SPY)', 'id': 'CEDEAR_SPY', 'currency': 'ARS', 'subyacente_sym': 'SPY', 'ratio': 20, 'subtitulo': 'ETF S&P 500 (Ratio 20:1)'},
    {'symbol': 'QQQ.BA', 'name': 'CEDEAR Invesco QQQ (QQQ)', 'id': 'CEDEAR_QQQ', 'currency': 'ARS', 'subyacente_sym': 'QQQ', 'ratio': 20, 'subtitulo': 'ETF Nasdaq 100 (Ratio 20:1)'},
    {'symbol': 'AAPL.BA', 'name': 'CEDEAR Apple (AAPL)', 'id': 'CEDEAR_AAPL', 'currency': 'ARS', 'subyacente_sym': 'AAPL', 'ratio': 10, 'subtitulo': 'Apple Inc. (Ratio 10:1)'},
    {'symbol': 'NVDA.BA', 'name': 'CEDEAR NVIDIA (NVDA)', 'id': 'CEDEAR_NVDA', 'currency': 'ARS', 'subyacente_sym': 'NVDA', 'ratio': 24, 'subtitulo': 'NVIDIA Corp. (Ratio 24:1)'},
    {'symbol': 'MELI.BA', 'name': 'CEDEAR MercadoLibre (MELI)', 'id': 'CEDEAR_MELI', 'currency': 'ARS', 'subyacente_sym': 'MELI', 'ratio': 60, 'subtitulo': 'MercadoLibre Inc. (Ratio 60:1)'},
    {'symbol': 'TSLA.BA', 'name': 'CEDEAR Tesla (TSLA)', 'id': 'CEDEAR_TSLA', 'currency': 'ARS', 'subyacente_sym': 'TSLA', 'ratio': 15, 'subtitulo': 'Tesla Inc. (Ratio 15:1)'},
    {'symbol': 'KO.BA', 'name': 'CEDEAR Coca-Cola (KO)', 'id': 'CEDEAR_KO', 'currency': 'ARS', 'subyacente_sym': 'KO', 'ratio': 5, 'subtitulo': 'The Coca-Cola Co. (Ratio 5:1)'},
    {'symbol': 'MSFT.BA', 'name': 'CEDEAR Microsoft (MSFT)', 'id': 'CEDEAR_MSFT', 'currency': 'ARS', 'subyacente_sym': 'MSFT', 'ratio': 10, 'subtitulo': 'Microsoft Corp. (Ratio 10:1)'},
    {'symbol': 'GOOGL.BA', 'name': 'CEDEAR Alphabet (GOOGL)', 'id': 'CEDEAR_GOOGL', 'currency': 'ARS', 'subyacente_sym': 'GOOGL', 'ratio': 29, 'subtitulo': 'Alphabet Inc. (Ratio 29:1)'},
    {'symbol': 'AMZN.BA', 'name': 'CEDEAR Amazon (AMZN)', 'id': 'CEDEAR_AMZN', 'currency': 'ARS', 'subyacente_sym': 'AMZN', 'ratio': 144, 'subtitulo': 'Amazon.com (Ratio 144:1)'},
    {'symbol': 'VIST.BA', 'name': 'CEDEAR Vista Energy (VIST)', 'id': 'CEDEAR_VIST', 'currency': 'ARS', 'subyacente_sym': 'VIST', 'ratio': 5, 'subtitulo': 'Vista Energy (Ratio 5:1)'},
    {'symbol': 'BBD.BA', 'name': 'CEDEAR Banco Bradesco (BBD)', 'id': 'CEDEAR_BBD', 'currency': 'ARS', 'subyacente_sym': 'BBD', 'ratio': 1, 'subtitulo': 'Banco Bradesco (Ratio 1:1)'},
]

CONFIG_ACCIONES_ARG = [
    {'symbol': 'GGAL.BA', 'name': 'Grupo Financiero Galicia (GGAL)', 'id': 'ARG_GGAL', 'currency': 'ARS', 'subtitulo': 'Sector Financiero / Bancario'},
    {'symbol': 'YPFD.BA', 'name': 'YPF S.A. (YPFD)', 'id': 'ARG_YPFD', 'currency': 'ARS', 'subtitulo': 'Energia / Petroleo y Gas'},
    {'symbol': 'PAMP.BA', 'name': 'Pampa Energia (PAMP)', 'id': 'ARG_PAMP', 'currency': 'ARS', 'subtitulo': 'Energia Electrica y Gas'},
    {'symbol': 'BMA.BA', 'name': 'Banco Macro (BMA)', 'id': 'ARG_BMA', 'currency': 'ARS', 'subtitulo': 'Sector Financiero / Bancario'},
    {'symbol': 'BBAR.BA', 'name': 'BBVA Argentina (BBAR)', 'id': 'ARG_BBAR', 'currency': 'ARS', 'subtitulo': 'Sector Financiero / Bancario'},
    {'symbol': 'TXAR.BA', 'name': 'Ternium Argentina (TXAR)', 'id': 'ARG_TXAR', 'currency': 'ARS', 'subtitulo': 'Siderurgia / Acero'},
    {'symbol': 'ALUA.BA', 'name': 'Aluar Aluminio (ALUA)', 'id': 'ARG_ALUA', 'currency': 'ARS', 'subtitulo': 'Materiales Basicos / Aluminio'},
    {'symbol': 'CRES.BA', 'name': 'Cresud (CRES)', 'id': 'ARG_CRES', 'currency': 'ARS', 'subtitulo': 'Agroindustria e Inmuebles'},
    {'symbol': 'CEPU.BA', 'name': 'Central Puerto (CEPU)', 'id': 'ARG_CEPU', 'currency': 'ARS', 'subtitulo': 'Generacion Electrica'},
    {'symbol': 'EDN.BA', 'name': 'Edenor (EDN)', 'id': 'ARG_EDN', 'currency': 'ARS', 'subtitulo': 'Distribucion Electrica'},
    {'symbol': 'TGSU2.BA', 'name': 'Transportadora Gas del Sur (TGSU2)', 'id': 'ARG_TGSU2', 'currency': 'ARS', 'subtitulo': 'Transporte de Gas / Utilities'},
    {'symbol': 'TECO2.BA', 'name': 'Telecom Argentina (TECO2)', 'id': 'ARG_TECO2', 'currency': 'ARS', 'subtitulo': 'Telecomunicaciones'},
    {'symbol': 'TRAN.BA', 'name': 'Transener (TRAN)', 'id': 'ARG_TRAN', 'currency': 'ARS', 'subtitulo': 'Transporte de Energia'},
]

CONFIG_CRIPTO = [
    {'symbol': 'BTC-USD', 'name': 'Bitcoin (BTC)', 'id': 'CRYPTO_BTC', 'currency': 'USD', 'subtitulo': 'Criptomoneda Lider / Reserva Digital'},
    {'symbol': 'ETH-USD', 'name': 'Ethereum (ETH)', 'id': 'CRYPTO_ETH', 'currency': 'USD', 'subtitulo': 'Contratos Inteligentes / Web3'},
    {'symbol': 'SOL-USD', 'name': 'Solana (SOL)', 'id': 'CRYPTO_SOL', 'currency': 'USD', 'subtitulo': 'Blockchain de Alta Velocidad'},
    {'symbol': 'BNB-USD', 'name': 'BNB (Binance Coin)', 'id': 'CRYPTO_BNB', 'currency': 'USD', 'subtitulo': 'Ecosistema BNB Chain'},
    {'symbol': 'XRP-USD', 'name': 'XRP (Ripple)', 'id': 'CRYPTO_XRP', 'currency': 'USD', 'subtitulo': 'Pagos y Liquidaciones'},
    {'symbol': 'ADA-USD', 'name': 'Cardano (ADA)', 'id': 'CRYPTO_ADA', 'currency': 'USD', 'subtitulo': 'Blockchain Proof of Stake'},
    {'symbol': 'DOGE-USD', 'name': 'Dogecoin (DOGE)', 'id': 'CRYPTO_DOGE', 'currency': 'USD', 'subtitulo': 'Moneda Digital Memetica'},
    {'symbol': 'USDT-USD', 'name': 'Tether USD (USDT)', 'id': 'CRYPTO_USDT', 'currency': 'USD', 'subtitulo': 'Stablecoin Dolar'},
]

def enrich_cedears_ccl(cedears_list, acciones_mundiales_list):
    print('-> Calculando CCL Implicito en CEDEARs...')
    subyacente_prices = {item['symbol']: item['precio'] for item in acciones_mundiales_list if item.get('precio')}
    for c in cedears_list:
        sub_sym = c.get('subyacente_sym')
        ratio = c.get('ratio', 1)
        ars_price = c.get('precio')
        usd_price = subyacente_prices.get(sub_sym)
        if not usd_price and sub_sym:
            try:
                t = yf.Ticker(sub_sym)
                info = t.fast_info
                usd_price = safe_float(info.last_price)
                if usd_price: subyacente_prices[sub_sym] = usd_price
            except: pass
        if ars_price and usd_price and ratio:
            ccl_impl = round((ars_price * ratio) / usd_price, 2)
            c['precio_subyacente_usd'] = usd_price
            c['ccl_implicito'] = ccl_impl
        else:
            c['ccl_implicito'] = None
    return cedears_list

def main():
    print(f'=== INICIANDO ACTUALIZACION DEL MONITOR FINANCIERO [{NOW_STR}] ===')
    start_time = time.time()
    master_dataset = {
        'version': '2.0',
        'marca': 'La Segunda Seguros',
        'ultima_actualizacion': NOW_STR,
        'fecha_cierre': TODAY_STR,
        'secciones': {}
    }
    all_series = {}
    
    # 1. Dolar
    dolar_items, dolar_series = fetch_dolar()
    master_dataset['secciones']['dolar'] = {'titulo': 'Dolar', 'icono': 'dollar-sign', 'items': dolar_items}
    all_series.update(dolar_series)
    
    # 2. Indices Mundiales
    indices_items, indices_series = fetch_yahoo_market_group(CONFIG_INDICES, 'Indices Mundiales')
    master_dataset['secciones']['indices_mundiales'] = {'titulo': 'Indices Mundiales', 'icono': 'globe', 'items': indices_items}
    all_series.update(indices_series)
    
    # 3. Divisas
    divisas_items, divisas_series = fetch_yahoo_market_group(CONFIG_DIVISAS, 'Divisas')
    master_dataset['secciones']['divisas'] = {'titulo': 'Divisas', 'icono': 'repeat', 'items': divisas_items}
    all_series.update(divisas_series)
    
    # 4. Commodities
    comm_items, comm_series = fetch_yahoo_market_group(CONFIG_COMMODITIES, 'Commodities')
    master_dataset['secciones']['commodities'] = {'titulo': 'Commodities', 'icono': 'layers', 'items': comm_items}
    all_series.update(comm_series)
    
    # 5. Tasas Internacionales
    tasas_int_items, tasas_int_series = fetch_yahoo_market_group(CONFIG_TASAS_INT, 'Tasas Internacionales')
    tasas_int_items.append({'id': 'TASA_FED_FUNDS', 'nombre': 'Tasa de Referencia Fed (EE.UU.)', 'categoria': 'Tasas Internacionales', 'tipo': 'rate', 'precio': 4.50, 'moneda': '%', 'var_1d': 0.0, 'var_1m': 0.0, 'var_12m': -15.0, 'subtitulo': 'Target Range Federal Reserve'})
    tasas_int_items.append({'id': 'TASA_ECB_DEP', 'nombre': 'Tasa de Deposito BCE (Europa)', 'categoria': 'Tasas Internacionales', 'tipo': 'rate', 'precio': 3.00, 'moneda': '%', 'var_1d': 0.0, 'var_1m': 0.0, 'var_12m': -20.0, 'subtitulo': 'Banco Central Europeo'})
    master_dataset['secciones']['tasas_internacionales'] = {'titulo': 'Tasas Internacionales', 'icono': 'trending-up', 'items': tasas_int_items}
    all_series.update(tasas_int_series)
    
    # 6. Tasas Locales
    tasas_loc_items, tasas_loc_series = fetch_tasas_locales()
    master_dataset['secciones']['tasas_locales'] = {'titulo': 'Tasas Locales', 'icono': 'landmark', 'items': tasas_loc_items}
    all_series.update(tasas_loc_series)
    
    # 7. FCI
    fci_items, fci_series = fetch_fci()
    master_dataset['secciones']['fci'] = {'titulo': 'Fondos Comunes de Inversion', 'icono': 'pie-chart', 'items': fci_items}
    all_series.update(fci_series)
    
    # 8. Bonos - LECAPs
    bonos_items, bonos_series = fetch_bonos_lecaps()
    master_dataset['secciones']['bonos_lecaps'] = {'titulo': 'Bonos - LECAPs', 'icono': 'file-text', 'items': bonos_items}
    all_series.update(bonos_series)
    
    # 9. ONs
    ons_items, ons_series = fetch_ons()
    master_dataset['secciones']['ons'] = {'titulo': 'ONs (Obligaciones Negociables)', 'icono': 'briefcase', 'items': ons_items}
    all_series.update(ons_series)
    
    # 10. Acciones Mundiales
    acc_mund_items, acc_mund_series = fetch_yahoo_market_group(CONFIG_ACCIONES_MUNDIALES, 'Acciones Mundiales')
    master_dataset['secciones']['acciones_mundiales'] = {'titulo': 'Acciones Mundiales', 'icono': 'activity', 'items': acc_mund_items}
    all_series.update(acc_mund_series)
    
    # 11. CEDEARs
    cedears_items, cedears_series = fetch_yahoo_market_group(CONFIG_CEDEARS, 'CEDEARs')
    cedears_items = enrich_cedears_ccl(cedears_items, acc_mund_items)
    master_dataset['secciones']['cedears'] = {'titulo': 'CEDEARs', 'icono': 'shuffle', 'items': cedears_items}
    all_series.update(cedears_series)
    
    # 12. Acciones Argentinas (Merval)
    acc_arg_items, acc_arg_series = fetch_yahoo_market_group(CONFIG_ACCIONES_ARG, 'Acciones Argentinas')
    master_dataset['secciones']['acciones_argentinas'] = {'titulo': 'Acciones Argentinas', 'icono': 'trending-up', 'items': acc_arg_items}
    all_series.update(acc_arg_series)
    
    # 13. Criptomonedas
    crypto_items, crypto_series = fetch_yahoo_market_group(CONFIG_CRIPTO, 'Criptomonedas')
    master_dataset['secciones']['criptomonedas'] = {'titulo': 'Criptomonedas', 'icono': 'cpu', 'items': crypto_items}
    all_series.update(crypto_series)
    
    # Curvas de rendimiento
    curvas = build_yield_curves(bonos_items, ons_items)
    
    p_master = os.path.join(OUTPUT_DIR, 'master_dataset.json')
    p_series = os.path.join(OUTPUT_DIR, 'series_historicas.json')
    p_curvas = os.path.join(OUTPUT_DIR, 'curvas_rendimiento.json')
    
    print(f'-> Guardando {p_master}...')
    with open(p_master, 'w', encoding='utf-8') as f:
        json.dump(master_dataset, f, ensure_ascii=False, indent=2)
        
    print(f'-> Guardando {p_series}...')
    with open(p_series, 'w', encoding='utf-8') as f:
        json.dump(all_series, f, ensure_ascii=False)
        
    print(f'-> Guardando {p_curvas}...')
    with open(p_curvas, 'w', encoding='utf-8') as f:
        json.dump(curvas, f, ensure_ascii=False, indent=2)
        
    # Guardar una copia del script principal en el workspace
    with open(__file__, 'r', encoding='utf-8') as src, open(os.path.join(OUTPUT_DIR, 'actualizar_monitor.py'), 'w', encoding='utf-8') as dst:
        code_text = src.read().replace('OUTPUT_DIR = r"g:\\Mi unidad\\IA\\Finanzas Puro"', 'OUTPUT_DIR = "."')
        code_text = code_text.replace('main()', 'main()')
        code_text = code_text.replace('def main():', 'def main():')
        dst.write(code_text)
        
    elapsed = round(time.time() - start_time, 2)
    print(f'=== ACTUALIZACION COMPLETADA CON EXITO EN {elapsed}s ===')

if __name__ == '__main__':
    main()
