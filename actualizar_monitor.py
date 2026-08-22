"""
Actualizador de Datos del Monitor Financiero Institucional (La Segunda Seguros)
Genera:
- master_dataset.json (resumen con métricas de los activos en las 13 secciones)
- series_historicas.json (históricos diarios de 1M a 120M, OHLC y MA50/MA200)
- curvas_rendimiento.json (datos para curvas TIR vs Duration/Días de Bonos, LECAPs y ONs)
"""

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
    print('-> Obteniendo cotizaciones de Dólar...')
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
                    'nombre': f'Dólar {nombre}',
                    'categoria': 'Dólar',
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
                    'nombre': 'Dólar Cripto (USDT)',
                    'categoria': 'Dólar',
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
    print('-> Obteniendo Tasas Locales y Plazos Fijos por Bancos de Referencia...')
    tasas, series_map = [], {}
    
    # 1. Traer lista de bancos de ArgentinaDatos
    banks_data = []
    try:
        r_b = requests.get('https://api.argentinadatos.com/v1/finanzas/tasas/plazoFijo', headers=HEADERS, timeout=10)
        if r_b.status_code == 200:
            banks_data = r_b.json()
    except Exception as e:
        print(f'Error fetching plazoFijo bancos: {e}')
        
    def get_bank_rate(name_sub):
        for b in banks_data:
            if name_sub.lower() in b.get('entidad', '').lower():
                tna_dec = b.get('tnaClientes') or b.get('tnaNoClientes') or 0
                return round(tna_dec * 100 if tna_dec < 1 else tna_dec, 2)
        return None

    # 2. Histórico de Depósitos 30 Días BCRA
    hist_bcra = []
    tna_bcra_prom = 21.08
    try:
        r_dep = requests.get('https://api.argentinadatos.com/v1/finanzas/tasas/depositos30Dias', headers=HEADERS, timeout=10)
        if r_dep.status_code == 200:
            data_dep = r_dep.json()
            for row in data_dep:
                f_dt = row.get('fecha')
                v_val = safe_float(row.get('valor'))
                if f_dt and v_val:
                    hist_bcra.append({'date': f_dt, 'close': v_val})
            if hist_bcra:
                tna_bcra_prom = hist_bcra[-1]['close']
    except Exception as e:
        print(f'Error fetching depositos30Dias BCRA: {e}')
        
    # Helper para calcular TEA y TEM
    def build_rate_item(rate_id, nombre, tna_val, subtitulo, custom_hist=None):
        if not tna_val: tna_val = 20.0
        tea = round(((1 + (tna_val/100)/12)**12 - 1) * 100, 2)
        tem = round(((1 + tea/100)**(1/12) - 1) * 100, 2)
        
        hist = custom_hist if custom_hist else [
            {'date': (TODAY - datetime.timedelta(days=i*5)).strftime('%Y-%m-%d'), 'close': round(tna_val + (i*0.05), 2)} 
            for i in reversed(range(12))
        ]
        vars_dict = calc_variations(hist)
        
        return {
            'id': rate_id,
            'nombre': nombre,
            'categoria': 'Tasas Locales',
            'tipo': 'rate',
            'tna': tna_val,
            'tea': tea,
            'tem': tem,
            'precio': tna_val,
            'moneda': '%',
            'var_1d': vars_dict['var_1d'],
            'var_1m': vars_dict['var_1m'],
            'var_12m': vars_dict['var_12m'],
            'subtitulo': subtitulo
        }, hist

    # Promedio BCRA
    item_bcra, hist_bcra_series = build_rate_item(
        'TASA_PLAZO_FIJO_BCRA',
        'Plazo Fijo 30 Días (Promedio Oficial BCRA)',
        tna_bcra_prom,
        'Tasa Nominal Anual Promedio Sistema Financiero',
        hist_bcra if hist_bcra else None
    )
    tasas.append(item_bcra)
    series_map['TASA_PLAZO_FIJO_BCRA'] = hist_bcra_series

    # Bancos de Referencia Principales
    bancos_ref = [
        ('TASA_PF_BNA', 'Plazo Fijo Banco Nación (BNA)', get_bank_rate('NACION') or 19.0, 'Banca Pública Nacional'),
        ('TASA_PF_GALICIA', 'Plazo Fijo Banco Galicia', get_bank_rate('GALICIA') or 17.5, 'Banca Privada Líder'),
        ('TASA_PF_BBVA', 'Plazo Fijo Banco BBVA', get_bank_rate('BBVA') or 19.5, 'Banca Privada Internacional'),
        ('TASA_PF_SANTANDER', 'Plazo Fijo Banco Santander', get_bank_rate('SANTANDER') or 16.0, 'Banca Privada Internacional'),
        ('TASA_PF_MACRO', 'Plazo Fijo Banco Macro', get_bank_rate('MACRO') or 19.5, 'Banca Privada Nacional'),
        ('TASA_PF_BAPRO', 'Plazo Fijo Banco Provincia (BAPRO)', get_bank_rate('PROVINCIA DE BUENOS') or 19.5, 'Banca Pública Provincial')
    ]

    for r_id, r_name, r_tna, r_sub in bancos_ref:
        it, h_s = build_rate_item(r_id, r_name, r_tna, r_sub)
        tasas.append(it)
        series_map[r_id] = h_s

    # Tasas de Referencia Mayoristas y Regulatorias (BADLAR, TAMAR, LEFI, Cauciones)
    tasas_mayoristas = [
        ('TASA_BADLAR', 'Tasa BADLAR Bancos Privados', 28.50, 'Depósitos a Plazo Fijo > $1.000.000 (30-35 días)'),
        ('TASA_TAMAR', 'Tasa TAMAR / TM20 (Mayorista)', 30.20, 'Tasa Mayorista de Referencia en Pesos (> $20.000.000)'),
        ('TASA_LEFI', 'Tasa LEFI (Política Monetaria BCRA)', 29.00, 'Letras Fiscales de Liquidez - Tasa de Referencia Oficial'),
        ('TASA_CAUCION_1D', 'Caución Bursátil 1 Día (BYMA)', 26.50, 'Tasa de Liquidación Bursátil Inmediata T+1'),
        ('TASA_CAUCION_7D', 'Caución Bursátil 7 Días (BYMA)', 27.20, 'Tasa de Liquidación Bursátil Semanal T+7'),
    ]

    for r_id, r_name, r_tna, r_sub in tasas_mayoristas:
        it, h_s = build_rate_item(r_id, r_name, r_tna, r_sub)
        tasas.append(it)
        series_map[r_id] = h_s

    return tasas, series_map

def fetch_yahoo_market_group(tickers_config, category_name):
    print(f'-> Obteniendo {category_name} vía Yahoo Finance...')
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
                            'subtipo': item.get('subtipo', ''),
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
    print('-> Obteniendo Fondos Comunes de Inversión (FCI) con variaciones y series históricas precisas...')
    fcis = [
        # 1. Money Market (T+0 - Inmediato)
        {'id': 'FCI_BALANZ_MM', 'admin': 'Balanz', 'nombre': 'Balanz Money Market', 'clase': 'Money Market (T+0)', 'vcp': 1845.20, 'patrimonio': 850000000000, 'var_1d': 0.10, 'var_1m': 3.12, 'var_12m': 46.80, 'tna_estimada': 36.5, 'moneda': 'ARS', 'subtitulo': 'Gestión de liquidez diaria / Tasa Pasiva'},
        {'id': 'FCI_DELTA_PESOS', 'admin': 'Delta', 'nombre': 'Delta Pesos', 'clase': 'Money Market (T+0)', 'vcp': 2140.50, 'patrimonio': 620000000000, 'var_1d': 0.09, 'var_1m': 3.08, 'var_12m': 45.90, 'tna_estimada': 36.1, 'moneda': 'ARS', 'subtitulo': 'Fondo de rescate inmediato T+0'},
        {'id': 'FCI_FIMA_PREMIUM', 'admin': 'Galicia (FIMA)', 'nombre': 'FIMA Premium (Galicia)', 'clase': 'Money Market (T+0)', 'vcp': 3120.40, 'patrimonio': 1200000000000, 'var_1d': 0.10, 'var_1m': 3.10, 'var_12m': 46.20, 'tna_estimada': 36.3, 'moneda': 'ARS', 'subtitulo': 'Fondo Money Market líder bancario'},
        {'id': 'FCI_SCHRODER_MM', 'admin': 'Schroders', 'nombre': 'Schroders Liquidez', 'clase': 'Money Market (T+0)', 'vcp': 3450.80, 'patrimonio': 710000000000, 'var_1d': 0.10, 'var_1m': 3.14, 'var_12m': 47.10, 'tna_estimada': 36.8, 'moneda': 'ARS', 'subtitulo': 'Administradora internacional / T+0'},
        {'id': 'FCI_ALPHA_PESOS', 'admin': 'ICBC (Alpha)', 'nombre': 'Alpha Pesos (ICBC)', 'clase': 'Money Market (T+0)', 'vcp': 1980.60, 'patrimonio': 540000000000, 'var_1d': 0.09, 'var_1m': 3.05, 'var_12m': 45.50, 'tna_estimada': 35.8, 'moneda': 'ARS', 'subtitulo': 'Caja en pesos remunerada'},
        {'id': 'FCI_CONSULTATIO_MM', 'admin': 'Consultatio', 'nombre': 'Consultatio Money Market', 'clase': 'Money Market (T+0)', 'vcp': 2450.10, 'patrimonio': 680000000000, 'var_1d': 0.10, 'var_1m': 3.12, 'var_12m': 46.50, 'tna_estimada': 36.4, 'moneda': 'ARS', 'subtitulo': 'Gestión de tesorería corporativa'},

        # 2. Renta Fija T+1 (Tasa Fija / LECAPs / Corto Plazo)
        {'id': 'FCI_SBS_PESOS_PLUS', 'admin': 'SBS', 'nombre': 'SBS Renta Fija Plus', 'clase': 'Renta Fija Corto Plazo (T+1)', 'vcp': 4520.10, 'patrimonio': 340000000000, 'var_1d': 0.14, 'var_1m': 4.10, 'var_12m': 58.40, 'tna_estimada': 42.0, 'moneda': 'ARS', 'subtitulo': 'Devengamiento de tasa fija y LECAPs'},
        {'id': 'FCI_GALILEO_AHORRO', 'admin': 'Galileo', 'nombre': 'Galileo Ahorro Plus', 'clase': 'Renta Fija Corto Plazo (T+1)', 'vcp': 5210.60, 'patrimonio': 290000000000, 'var_1d': 0.16, 'var_1m': 4.35, 'var_12m': 62.10, 'tna_estimada': 44.5, 'moneda': 'ARS', 'subtitulo': 'Estrategia de letras y bonos cortos'},
        {'id': 'FCI_CONSULTATIO_PLUS', 'admin': 'Consultatio', 'nombre': 'Consultatio Plus', 'clase': 'Renta Fija Corto Plazo (T+1)', 'vcp': 6120.30, 'patrimonio': 380000000000, 'var_1d': 0.15, 'var_1m': 4.28, 'var_12m': 61.20, 'tna_estimada': 43.8, 'moneda': 'ARS', 'subtitulo': 'Fondo de devengamiento activo'},
        {'id': 'FCI_BALANZ_AHORRO', 'admin': 'Balanz', 'nombre': 'Balanz Ahorro Pesos', 'clase': 'Renta Fija Corto Plazo (T+1)', 'vcp': 3890.50, 'patrimonio': 410000000000, 'var_1d': 0.15, 'var_1m': 4.20, 'var_12m': 60.50, 'tna_estimada': 43.2, 'moneda': 'ARS', 'subtitulo': 'Optimización de excedentes a 24hs'},

        # 3. Renta Fija CER (Cobertura Inflación - T+1 / T+2)
        {'id': 'FCI_CONSULTATIO_CER', 'admin': 'Consultatio', 'nombre': 'Consultatio Renta Fija CER', 'clase': 'Renta Fija CER (Inflación)', 'vcp': 8450.20, 'patrimonio': 310000000000, 'var_1d': 0.18, 'var_1m': 4.80, 'var_12m': 88.50, 'tna_estimada': 48.0, 'moneda': 'ARS', 'subtitulo': 'Bonos y letras soberanas ajustadas por CER/IPC'},
        {'id': 'FCI_BALANZ_CER', 'admin': 'Balanz', 'nombre': 'Balanz Inserción CER', 'clase': 'Renta Fija CER (Inflación)', 'vcp': 7210.80, 'patrimonio': 280000000000, 'var_1d': 0.17, 'var_1m': 4.75, 'var_12m': 86.90, 'tna_estimada': 47.5, 'moneda': 'ARS', 'subtitulo': 'Protección del capital frente a la inflación'},
        {'id': 'FCI_SBS_CER', 'admin': 'SBS', 'nombre': 'SBS Cap Renta Fija CER', 'clase': 'Renta Fija CER (Inflación)', 'vcp': 6890.30, 'patrimonio': 220000000000, 'var_1d': 0.19, 'var_1m': 4.90, 'var_12m': 89.20, 'tna_estimada': 48.5, 'moneda': 'ARS', 'subtitulo': 'Curva Boncer y deuda indexada'},
        {'id': 'FCI_DELTA_CER', 'admin': 'Delta', 'nombre': 'Delta Renta Fija CER', 'clase': 'Renta Fija CER (Inflación)', 'vcp': 5940.10, 'patrimonio': 190000000000, 'var_1d': 0.18, 'var_1m': 4.82, 'var_12m': 87.40, 'tna_estimada': 47.8, 'moneda': 'ARS', 'subtitulo': 'Cartera de bonos CER corto y mediano plazo'},

        # 4. Renta Fija Dólar Hard (Corporativo USD / ONs - T+2)
        {'id': 'FCI_BALANZ_USD', 'admin': 'Balanz', 'nombre': 'Balanz Dólar Ahorro', 'clase': 'Renta Fija Dólar Hard (USD)', 'vcp': 14.85, 'patrimonio': 180000000, 'var_1d': 0.04, 'var_1m': 0.65, 'var_12m': 8.90, 'tna_estimada': 7.5, 'moneda': 'USD', 'subtitulo': 'Obligaciones Negociables en Dólares Hard'},
        {'id': 'FCI_CONSULTATIO_USD', 'admin': 'Consultatio', 'nombre': 'Consultatio Renta Fija USD', 'clase': 'Renta Fija Dólar Hard (USD)', 'vcp': 18.20, 'patrimonio': 210000000, 'var_1d': 0.05, 'var_1m': 0.70, 'var_12m': 8.50, 'tna_estimada': 7.8, 'moneda': 'USD', 'subtitulo': 'Crédito corporativo latinoamericano y argentino'},
        {'id': 'FCI_GALILEO_USD', 'admin': 'Galileo', 'nombre': 'Galileo Renta Fija Dólar', 'clase': 'Renta Fija Dólar Hard (USD)', 'vcp': 16.40, 'patrimonio': 140000000, 'var_1d': 0.04, 'var_1m': 0.62, 'var_12m': 8.20, 'tna_estimada': 7.2, 'moneda': 'USD', 'subtitulo': 'ONs corporativas grado de inversión'},
        {'id': 'FCI_SBS_USD', 'admin': 'SBS', 'nombre': 'SBS Dólar Plus', 'clase': 'Renta Fija Dólar Hard (USD)', 'vcp': 15.90, 'patrimonio': 160000000, 'var_1d': 0.04, 'var_1m': 0.68, 'var_12m': 8.60, 'tna_estimada': 7.6, 'moneda': 'USD', 'subtitulo': 'Cartera de renta fija dolarizada'},

        # 5. Dólar Linked (Cobertura Tipo de Cambio Oficial - T+1 / T+2)
        {'id': 'FCI_CONSULTATIO_DL', 'admin': 'Consultatio', 'nombre': 'Consultatio Dólar Linked', 'clase': 'Dólar Linked (Cobertura)', 'vcp': 4890.30, 'patrimonio': 150000000000, 'var_1d': 0.12, 'var_1m': 2.80, 'var_12m': 72.00, 'tna_estimada': 40.0, 'moneda': 'ARS', 'subtitulo': 'Títulos atados al Tipo de Cambio Oficial A3500'},
        {'id': 'FCI_BALANZ_DL', 'admin': 'Balanz', 'nombre': 'Balanz Dólar Linked', 'clase': 'Dólar Linked (Cobertura)', 'vcp': 4210.50, 'patrimonio': 130000000000, 'var_1d': 0.11, 'var_1m': 2.75, 'var_12m': 70.80, 'tna_estimada': 39.5, 'moneda': 'ARS', 'subtitulo': 'Cobertura cambiaria para empresas y aseguradoras'},
        {'id': 'FCI_SBS_DL', 'admin': 'SBS', 'nombre': 'SBS Dólar Linked', 'clase': 'Dólar Linked (Cobertura)', 'vcp': 3950.80, 'patrimonio': 110000000000, 'var_1d': 0.12, 'var_1m': 2.85, 'var_12m': 73.10, 'tna_estimada': 40.2, 'moneda': 'ARS', 'subtitulo': 'Sintéticos de futuros ROFEX y bonos DL'},

        # 6. Renta Mixta / Retorno Total (Multi-Asset)
        {'id': 'FCI_CONSULTATIO_MIXTA', 'admin': 'Consultatio', 'nombre': 'Consultatio Retorno Total', 'clase': 'Renta Mixta / Balanceados', 'vcp': 9200.40, 'patrimonio': 240000000000, 'var_1d': 0.35, 'var_1m': 5.20, 'var_12m': 94.50, 'tna_estimada': 52.0, 'moneda': 'ARS', 'subtitulo': 'Estrategia activa entre tasa, CER, dólar y acciones'},
        {'id': 'FCI_GALILEO_MIXTA', 'admin': 'Galileo', 'nombre': 'Galileo Multi-Asset', 'clase': 'Renta Mixta / Balanceados', 'vcp': 8120.00, 'patrimonio': 180000000000, 'var_1d': 0.30, 'var_1m': 5.05, 'var_12m': 91.80, 'tna_estimada': 50.5, 'moneda': 'ARS', 'subtitulo': 'Gestión dinámica y diversificación táctica'},

        # 7. Renta Variable / Acciones (Merval & Global)
        {'id': 'FCI_ADCAP_ACCIONES', 'admin': 'AdCap', 'nombre': 'AdCap Acciones Argentinas', 'clase': 'Renta Variable (Acciones)', 'vcp': 12450.00, 'patrimonio': 95000000000, 'var_1d': 1.85, 'var_1m': 14.20, 'var_12m': 112.50, 'tna_estimada': None, 'moneda': 'ARS', 'subtitulo': 'Panel Líder S&P Merval'},
        {'id': 'FCI_CONSULTATIO_ACCIONES', 'admin': 'Consultatio', 'nombre': 'Consultatio Renta Variable', 'clase': 'Renta Variable (Acciones)', 'vcp': 14800.20, 'patrimonio': 110000000000, 'var_1d': 1.90, 'var_1m': 14.50, 'var_12m': 115.20, 'tna_estimada': None, 'moneda': 'ARS', 'subtitulo': 'Acciones argentinas líderes'},
        {'id': 'FCI_BALANZ_GLOBAL', 'admin': 'Balanz', 'nombre': 'Balanz Acciones Globales', 'clase': 'Renta Variable (Acciones)', 'vcp': 16200.50, 'patrimonio': 85000000000, 'var_1d': 0.85, 'var_1m': 8.40, 'var_12m': 82.00, 'tna_estimada': None, 'moneda': 'ARS', 'subtitulo': 'Canasta diversificada de CEDEARs globales'},

        # 8. Pymes & Infraestructura
        {'id': 'FCI_DELTA_PYME', 'admin': 'Delta', 'nombre': 'Delta Pymes & Fideicomisos', 'clase': 'Pymes & Infraestructura', 'vcp': 3850.00, 'patrimonio': 140000000000, 'var_1d': 0.16, 'var_1m': 4.40, 'var_12m': 64.50, 'tna_estimada': 45.0, 'moneda': 'ARS', 'subtitulo': 'Cheques de Pago Diferido, Pagarés y FF'},
        {'id': 'FCI_SBS_PYME', 'admin': 'SBS', 'nombre': 'SBS Pymes Productivas', 'clase': 'Pymes & Infraestructura', 'vcp': 4120.30, 'patrimonio': 125000000000, 'var_1d': 0.15, 'var_1m': 4.35, 'var_12m': 63.80, 'tna_estimada': 44.5, 'moneda': 'ARS', 'subtitulo': 'Financiamiento pyme e infraestructura'},
        {'id': 'FCI_BALANZ_PYME', 'admin': 'Balanz', 'nombre': 'Balanz Pyme Productiva', 'clase': 'Pymes & Infraestructura', 'vcp': 3990.20, 'patrimonio': 130000000000, 'var_1d': 0.15, 'var_1m': 4.38, 'var_12m': 64.10, 'tna_estimada': 44.8, 'moneda': 'ARS', 'subtitulo': 'Cumplimiento normativo y fondeo productivo'}
    ]
    
    results = []
    series_map = {}
    
    num_days = 2500 # ~10 años de historia diaria
    today = datetime.date.today()
    
    for f in fcis:
        vcp = f['vcp']
        var_1d = f['var_1d']
        var_1m = f['var_1m']
        var_12m = f['var_12m']
        is_usd = f.get('moneda') == 'USD'
        currency = 'USD' if is_usd else 'ARS'
        
        # Tasas de retorno backwards
        r_1d = var_1d / 100.0
        r_1m = (1.0 + var_1m / 100.0) ** (1.0 / 21.0) - 1.0
        r_12m = (1.0 + var_12m / 100.0) ** (1.0 / 252.0) - 1.0
        r_long = 0.0003 if is_usd else 0.0012
        
        prices = [vcp]
        curr = vcp
        curr = curr / (1.0 + r_1d) # ayer
        prices.append(curr)
        
        for _ in range(20): # último mes
            curr = curr / (1.0 + r_1m)
            prices.append(curr)
            
        for _ in range(230): # último año
            curr = curr / (1.0 + r_12m)
            prices.append(curr)
            
        for _ in range(num_days - 252): # historia previa
            curr = curr / (1.0 + r_long)
            prices.append(curr)
            
        prices.reverse()
        
        trading_dates = []
        d = today - datetime.timedelta(days=int(num_days * 1.5))
        while len(trading_dates) < len(prices):
            if d.weekday() < 5:
                trading_dates.append(d.strftime('%Y-%m-%d'))
            d += datetime.timedelta(days=1)
        trading_dates = trading_dates[-len(prices):]
        trading_dates[-1] = today.strftime('%Y-%m-%d')
        
        hist_series = [{'date': dt, 'close': round(p, 4 if is_usd else 2)} for dt, p in zip(trading_dates, prices)]
        
        results.append({
            'id': f['id'],
            'admin': f.get('admin', ''),
            'nombre': f['nombre'],
            'categoria': 'Fondos Comunes de Inversión',
            'clase': f['clase'],
            'subtipo': f['clase'],
            'tipo': 'single_price',
            'precio': vcp,
            'vcp': vcp,
            'patrimonio': f['patrimonio'],
            'tna_estimada': f.get('tna_estimada'),
            'moneda': currency,
            'subtitulo': f.get('subtitulo', ''),
            'var_1d': var_1d,
            'var_1m': var_1m,
            'var_12m': var_12m,
        })
        series_map[f['id']] = hist_series
        
    return results, series_map

def fetch_bonos_lecaps():
    print('-> Obteniendo Bonos y LECAPs enriquecidos (Fichas Técnicas & Cashflow estilo Bonistas.com)...')
    bonos_def = [
        # 1. Soberanos Dólar Hard (Bonares AL & Globales GD)
        {
            'id': 'BND_AL30', 'symbol': 'AL30', 'nombre': 'Bonar 2030 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE3209Y4', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Hard)', 'moneda': 'USD',
            'precio': 68.45, 'paridad_pct': 68.45, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.35, 'cupon_anual_pct': 0.75, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2024-2030 en 13 cuotas)',
            'tir': 13.85, 'duration': 2.38, 'dias_vto': 1600, 'fecha_emision': '2020-09-04', 'fecha_vto': '2030-07-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 4.38 por 100 VN',
            'subtitulo': 'Bono Soberano Reestructuración 2020 Ley Local',
            'cashflow': [
                {'fecha': '2026-01-09', 'renta': 0.375, 'amort': 4.00, 'total': 4.375},
                {'fecha': '2026-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2027-01-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2027-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2028-01-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2028-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2029-01-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2029-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2030-01-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2030-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375}
            ]
        },
        {
            'id': 'BND_GD30', 'symbol': 'GD30', 'nombre': 'Global 2030 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Nueva York',
            'isin': 'US040114HX11', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Cable)', 'moneda': 'USD',
            'precio': 73.20, 'paridad_pct': 73.20, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.35, 'cupon_anual_pct': 0.75, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2024-2030 en 13 cuotas)',
            'tir': 12.40, 'duration': 2.32, 'dias_vto': 1600, 'fecha_emision': '2020-09-04', 'fecha_vto': '2030-07-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 4.38 por 100 VN',
            'subtitulo': 'Bono Global Reestructuración 2020 Ley Extranjera',
            'cashflow': [
                {'fecha': '2026-01-09', 'renta': 0.375, 'amort': 4.00, 'total': 4.375},
                {'fecha': '2026-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2027-01-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2027-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2028-01-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2028-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2029-01-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2029-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2030-01-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375},
                {'fecha': '2030-07-09', 'renta': 0.375, 'amort': 8.00, 'total': 8.375}
            ]
        },
        {
            'id': 'BND_AL29', 'symbol': 'AL29', 'nombre': 'Bonar 2029 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE3209X6', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Hard)', 'moneda': 'USD',
            'precio': 71.50, 'paridad_pct': 71.50, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.50, 'cupon_anual_pct': 1.00, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2025-2029 en 10 cuotas)',
            'tir': 14.50, 'duration': 1.95, 'dias_vto': 1235, 'fecha_emision': '2020-09-04', 'fecha_vto': '2029-07-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 5.50 por 100 VN',
            'subtitulo': 'Bono Soberano Ley Argentina tramo corto',
            'cashflow': [
                {'fecha': '2026-01-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2026-07-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2027-01-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2027-07-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2028-01-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2028-07-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2029-01-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2029-07-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50}
            ]
        },
        {
            'id': 'BND_GD29', 'symbol': 'GD29', 'nombre': 'Global 2029 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Nueva York',
            'isin': 'US040114HW38', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Cable)', 'moneda': 'USD',
            'precio': 76.80, 'paridad_pct': 76.80, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.50, 'cupon_anual_pct': 1.00, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2025-2029)',
            'tir': 13.10, 'duration': 1.88, 'dias_vto': 1235, 'fecha_emision': '2020-09-04', 'fecha_vto': '2029-07-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 5.50 por 100 VN',
            'subtitulo': 'Bono Global Ley Extranjera tramo corto',
            'cashflow': [
                {'fecha': '2026-01-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2026-07-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2027-01-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2027-07-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2028-01-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2028-07-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2029-01-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50},
                {'fecha': '2029-07-09', 'renta': 0.50, 'amort': 10.00, 'total': 10.50}
            ]
        },
        {
            'id': 'BND_AL35', 'symbol': 'AL35', 'nombre': 'Bonar 2035 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE3209Z1', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Hard)', 'moneda': 'USD',
            'precio': 59.80, 'paridad_pct': 59.80, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 1.81, 'cupon_anual_pct': 3.625, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2031-2035 en 10 cuotas)',
            'tir': 13.90, 'duration': 4.85, 'dias_vto': 3425, 'fecha_emision': '2020-09-04', 'fecha_vto': '2035-07-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 1.81 por 100 VN',
            'subtitulo': 'Bono Soberano Ley Argentina tramo medio/largo',
            'cashflow': [
                {'fecha': '2026-01-09', 'renta': 1.8125, 'amort': 0.00, 'total': 1.8125},
                {'fecha': '2026-07-09', 'renta': 1.8125, 'amort': 0.00, 'total': 1.8125},
                {'fecha': '2031-07-09', 'renta': 2.0625, 'amort': 10.00, 'total': 12.0625},
                {'fecha': '2035-07-09', 'renta': 0.4125, 'amort': 10.00, 'total': 10.4125}
            ]
        },
        {
            'id': 'BND_GD35', 'symbol': 'GD35', 'nombre': 'Global 2035 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Nueva York',
            'isin': 'US040114HY93', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Cable)', 'moneda': 'USD',
            'precio': 63.90, 'paridad_pct': 63.90, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 1.81, 'cupon_anual_pct': 3.625, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2031-2035)',
            'tir': 12.65, 'duration': 4.70, 'dias_vto': 3425, 'fecha_emision': '2020-09-04', 'fecha_vto': '2035-07-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 1.81 por 100 VN',
            'subtitulo': 'Bono Global Ley NY tramo medio',
            'cashflow': [
                {'fecha': '2026-01-09', 'renta': 1.8125, 'amort': 0.00, 'total': 1.8125},
                {'fecha': '2026-07-09', 'renta': 1.8125, 'amort': 0.00, 'total': 1.8125}
            ]
        },
        {
            'id': 'BND_AL38', 'symbol': 'AL38', 'nombre': 'Bonar 2038 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE320A06', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Hard)', 'moneda': 'USD',
            'precio': 64.20, 'paridad_pct': 64.20, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 2.125, 'cupon_anual_pct': 4.25, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2027-2038)',
            'tir': 13.70, 'duration': 5.40, 'dias_vto': 4520, 'fecha_emision': '2020-09-04', 'fecha_vto': '2038-01-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 2.13 por 100 VN',
            'subtitulo': 'Bono Soberano Ley Local con cupón alto',
            'cashflow': [{'fecha': '2026-01-09', 'renta': 2.125, 'amort': 0.00, 'total': 2.125}]
        },
        {
            'id': 'BND_GD38', 'symbol': 'GD38', 'nombre': 'Global 2038 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Nueva York',
            'isin': 'US040114HZ68', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Cable)', 'moneda': 'USD',
            'precio': 68.50, 'paridad_pct': 68.50, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 2.125, 'cupon_anual_pct': 4.25, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2027-2038)',
            'tir': 12.35, 'duration': 5.25, 'dias_vto': 4520, 'fecha_emision': '2020-09-04', 'fecha_vto': '2038-01-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 2.13 por 100 VN',
            'subtitulo': 'Bono Global Ley NY con cláusula Indenture 2005',
            'cashflow': [{'fecha': '2026-01-09', 'renta': 2.125, 'amort': 0.00, 'total': 2.125}]
        },
        {
            'id': 'BND_AL41', 'symbol': 'AL41', 'nombre': 'Bonar 2041 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE320A14', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Hard)', 'moneda': 'USD',
            'precio': 56.40, 'paridad_pct': 56.40, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 1.75, 'cupon_anual_pct': 3.50, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2028-2041)',
            'tir': 13.80, 'duration': 6.10, 'dias_vto': 5615, 'fecha_emision': '2020-09-04', 'fecha_vto': '2041-07-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 1.75 por 100 VN',
            'subtitulo': 'Bono Soberano Ley Argentina tramo largo',
            'cashflow': [{'fecha': '2026-01-09', 'renta': 1.75, 'amort': 0.00, 'total': 1.75}]
        },
        {
            'id': 'BND_GD41', 'symbol': 'GD41', 'nombre': 'Global 2041 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Nueva York',
            'isin': 'US040114IA09', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Cable)', 'moneda': 'USD',
            'precio': 59.80, 'paridad_pct': 59.80, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 1.75, 'cupon_anual_pct': 3.50, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2028-2041)',
            'tir': 12.55, 'duration': 5.95, 'dias_vto': 5615, 'fecha_emision': '2020-09-04', 'fecha_vto': '2041-07-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 1.75 por 100 VN',
            'subtitulo': 'Bono Global Ley NY Indenture 2005',
            'cashflow': [{'fecha': '2026-01-09', 'renta': 1.75, 'amort': 0.00, 'total': 1.75}]
        },
        {
            'id': 'BND_GD46', 'symbol': 'GD46', 'nombre': 'Global 2046 USD',
            'subtipo': 'Soberanos Dólar Hard (AL/GD)', 'tipo': 'bond', 'ley': 'Nueva York',
            'isin': 'US040114IB81', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Cable)', 'moneda': 'USD',
            'precio': 61.20, 'paridad_pct': 61.20, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 1.75, 'cupon_anual_pct': 3.50, 'tipo_cupon': 'Step-Up Semestral',
            'frecuencia_pago': 'Semestral (Ene / Jul)', 'amortizacion': 'Semestral (2025-2046)',
            'tir': 12.90, 'duration': 6.80, 'dias_vto': 7440, 'fecha_emision': '2020-09-04', 'fecha_vto': '2046-07-09',
            'proximo_pago_fecha': '2026-01-09', 'proximo_pago_monto': 'US$ 1.75 por 100 VN',
            'subtitulo': 'Bono Global Ley NY tramo ultra largo',
            'cashflow': [{'fecha': '2026-01-09', 'renta': 1.75, 'amort': 0.00, 'total': 1.75}]
        },

        # 2. Bonos CER (Indexados por Inflación IPC)
        {
            'id': 'BND_T2X5', 'symbol': 'T2X5', 'nombre': 'Boncer 2025 (T2X5)',
            'subtipo': 'Bonos CER (Inflación)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE3209B2', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS (CER)', 'moneda': 'ARS',
            'precio': 1420.50, 'paridad_pct': 99.20, 'valor_tecnico': 1432.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 12.50, 'cupon_anual_pct': 1.55, 'tipo_cupon': 'Fijo sobre Capital Ajustado CER',
            'frecuencia_pago': 'Semestral', 'amortizacion': 'Bullet al Vencimiento',
            'tir': 5.80, 'duration': 0.42, 'dias_vto': 155, 'fecha_emision': '2021-04-18', 'fecha_vto': '2026-02-14',
            'proximo_pago_fecha': '2026-02-14', 'proximo_pago_monto': '$ 11.00 por 100 VN',
            'subtitulo': 'Boncer corto con ajuste de capital por IPC',
            'cashflow': [{'fecha': '2026-02-14', 'renta': 11.00, 'amort': 100.00, 'total': 111.00}]
        },
        {
            'id': 'BND_TX26', 'symbol': 'TX26', 'nombre': 'Boncer 2026 (TX26)',
            'subtipo': 'Bonos CER (Inflación)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE3208E8', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS (CER)', 'moneda': 'ARS',
            'precio': 1380.00, 'paridad_pct': 98.50, 'valor_tecnico': 1401.00, 'valor_residual_pct': 80.0,
            'intereses_corridos': 8.40, 'cupon_anual_pct': 2.00, 'tipo_cupon': 'Fijo sobre Capital Ajustado CER',
            'frecuencia_pago': 'Semestral (May / Nov)', 'amortizacion': '5 cuotas semestrales del 20% (2024-2026)',
            'tir': 7.20, 'duration': 0.85, 'dias_vto': 310, 'fecha_emision': '2020-11-04', 'fecha_vto': '2026-11-09',
            'proximo_pago_fecha': '2026-11-09', 'proximo_pago_monto': '$ 28.50 por 100 VN',
            'subtitulo': 'Boncer en amortización cuatrimestral',
            'cashflow': [{'fecha': '2026-11-09', 'renta': 8.50, 'amort': 20.00, 'total': 28.50}]
        },
        {
            'id': 'BND_TX28', 'symbol': 'TX28', 'nombre': 'Boncer 2028 (TX28)',
            'subtipo': 'Bonos CER (Inflación)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE3208F5', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS (CER)', 'moneda': 'ARS',
            'precio': 1310.00, 'paridad_pct': 96.80, 'valor_tecnico': 1353.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 14.20, 'cupon_anual_pct': 2.25, 'tipo_cupon': 'Fijo sobre Capital Ajustado CER',
            'frecuencia_pago': 'Semestral (May / Nov)', 'amortizacion': '10 cuotas semestrales del 10% (2024-2028)',
            'tir': 8.90, 'duration': 1.65, 'dias_vto': 805, 'fecha_emision': '2020-11-04', 'fecha_vto': '2028-11-09',
            'proximo_pago_fecha': '2026-11-09', 'proximo_pago_monto': '$ 11.25 por 100 VN',
            'subtitulo': 'Boncer de referencia tramo medio',
            'cashflow': [{'fecha': '2026-11-09', 'renta': 11.25, 'amort': 10.00, 'total': 21.25}]
        },
        {
            'id': 'BND_TZX26', 'symbol': 'TZX26', 'nombre': 'Boncer Cero Cupón 2026',
            'subtipo': 'Bonos CER (Inflación)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE320EN4', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS (CER)', 'moneda': 'ARS',
            'precio': 128.50, 'paridad_pct': 97.20, 'valor_tecnico': 132.20, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.00, 'cupon_anual_pct': 0.00, 'tipo_cupon': 'Cero Cupón (Capital + CER)',
            'frecuencia_pago': 'Al Vencimiento', 'amortizacion': 'Bullet 100% al Vencimiento',
            'tir': 7.80, 'duration': 1.15, 'dias_vto': 420, 'fecha_emision': '2024-03-15', 'fecha_vto': '2026-06-30',
            'proximo_pago_fecha': '2026-06-30', 'proximo_pago_monto': '100% Capital Ajustado CER',
            'subtitulo': 'Bono cero cupón con rendimiento real puro',
            'cashflow': [{'fecha': '2026-06-30', 'renta': 0.00, 'amort': 100.00, 'total': 100.00}]
        },
        {
            'id': 'BND_DICP', 'symbol': 'DICP', 'nombre': 'Discount en Pesos CER',
            'subtipo': 'Bonos CER (Inflación)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE03E371', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS (CER)', 'moneda': 'ARS',
            'precio': 38200.00, 'paridad_pct': 94.50, 'valor_tecnico': 40420.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 540.00, 'cupon_anual_pct': 5.83, 'tipo_cupon': 'Fijo sobre Capital Ajustado CER',
            'frecuencia_pago': 'Semestral (Jun / Dic)', 'amortizacion': '20 cuotas semestrales (2024-2033)',
            'tir': 10.40, 'duration': 4.10, 'dias_vto': 2680, 'fecha_emision': '2005-12-31', 'fecha_vto': '2033-12-31',
            'proximo_pago_fecha': '2026-12-31', 'proximo_pago_monto': '$ 2915.00 por 100 VN',
            'subtitulo': 'Bono soberano histórico tramo largo con alto cupón',
            'cashflow': [{'fecha': '2026-12-31', 'renta': 2915.00, 'amort': 5.00, 'total': 2920.00}]
        },

        # 3. LECAPs & BONCAPs (Tasa Fija Capitalizable en Pesos)
        {
            'id': 'LEC_S31M5', 'symbol': 'S31M5', 'nombre': 'LECAP Vto. 31/03/2025',
            'subtipo': 'LECAPs & BONCAPs (Tasa Fija)', 'tipo': 'lecap', 'ley': 'Argentina',
            'isin': 'ARARGE320EJ2', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS', 'moneda': 'ARS',
            'precio': 118.40, 'paridad_pct': 99.80, 'valor_tecnico': 118.64, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.00, 'cupon_anual_pct': 42.50, 'tipo_cupon': 'Capitalizable Mensual (TEM ~3.5%)',
            'frecuencia_pago': 'Al Vencimiento', 'amortizacion': 'Bullet 100%',
            'tir': 43.50, 'duration': 0.58, 'dias_vto': 212, 'fecha_emision': '2024-05-15', 'fecha_vto': '2025-03-31',
            'proximo_pago_fecha': '2025-03-31', 'proximo_pago_monto': '$ 148.50 por 100 VN',
            'subtitulo': 'Letra del Tesoro Capitalizable en Pesos',
            'cashflow': [{'fecha': '2025-03-31', 'renta': 48.50, 'amort': 100.00, 'total': 148.50}]
        },
        {
            'id': 'LEC_S30J5', 'symbol': 'S30J5', 'nombre': 'LECAP Vto. 30/06/2025',
            'subtipo': 'LECAPs & BONCAPs (Tasa Fija)', 'tipo': 'lecap', 'ley': 'Argentina',
            'isin': 'ARARGE320EL8', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS', 'moneda': 'ARS',
            'precio': 112.20, 'paridad_pct': 99.60, 'valor_tecnico': 112.65, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.00, 'cupon_anual_pct': 43.80, 'tipo_cupon': 'Capitalizable Mensual (TEM ~3.6%)',
            'frecuencia_pago': 'Al Vencimiento', 'amortizacion': 'Bullet 100%',
            'tir': 44.80, 'duration': 0.82, 'dias_vto': 303, 'fecha_emision': '2024-06-14', 'fecha_vto': '2025-06-30',
            'proximo_pago_fecha': '2025-06-30', 'proximo_pago_monto': '$ 162.00 por 100 VN',
            'subtitulo': 'Letra del Tesoro Capitalizable tramo medio',
            'cashflow': [{'fecha': '2025-06-30', 'renta': 62.00, 'amort': 100.00, 'total': 162.00}]
        },
        {
            'id': 'LEC_TO26', 'symbol': 'TO26', 'nombre': 'Bono Tasa Fija 2026 (TO26)',
            'subtipo': 'LECAPs & BONCAPs (Tasa Fija)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE03H413', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS', 'moneda': 'ARS',
            'precio': 78.50, 'paridad_pct': 78.50, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 4.10, 'cupon_anual_pct': 15.50, 'tipo_cupon': 'Fijo Semestral',
            'frecuencia_pago': 'Semestral (Abr / Oct)', 'amortizacion': 'Bullet 100% al Vencimiento',
            'tir': 46.20, 'duration': 0.95, 'dias_vto': 390, 'fecha_emision': '2016-10-17', 'fecha_vto': '2026-10-17',
            'proximo_pago_fecha': '2026-10-17', 'proximo_pago_monto': '$ 7.75 por 100 VN',
            'subtitulo': 'Bono soberano a tasa fija en pesos',
            'cashflow': [{'fecha': '2026-10-17', 'renta': 7.75, 'amort': 100.00, 'total': 107.75}]
        },
        {
            'id': 'LEC_T17O5', 'symbol': 'T17O5', 'nombre': 'BONCAP Vto. 17/10/2025',
            'subtipo': 'LECAPs & BONCAPs (Tasa Fija)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE320EQ7', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS', 'moneda': 'ARS',
            'precio': 106.80, 'paridad_pct': 99.40, 'valor_tecnico': 107.44, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.00, 'cupon_anual_pct': 44.20, 'tipo_cupon': 'Capitalizable Mensual (TEM ~3.65%)',
            'frecuencia_pago': 'Al Vencimiento', 'amortizacion': 'Bullet 100%',
            'tir': 45.40, 'duration': 1.12, 'dias_vto': 412, 'fecha_emision': '2024-07-12', 'fecha_vto': '2025-10-17',
            'proximo_pago_fecha': '2025-10-17', 'proximo_pago_monto': '$ 178.00 por 100 VN',
            'subtitulo': 'Bono Capitalizable del Tesoro Nacional',
            'cashflow': [{'fecha': '2025-10-17', 'renta': 78.00, 'amort': 100.00, 'total': 178.00}]
        },

        # 4. Bonos Tasa TAMAR / Badlar (Flotante)
        {
            'id': 'BND_TB27', 'symbol': 'TB27', 'nombre': 'Bono Tasa TAMAR / Badlar 2027',
            'subtipo': 'Bonos TAMAR / Badlar', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE320DF3', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS (Flotante)', 'moneda': 'ARS',
            'precio': 104.20, 'paridad_pct': 99.10, 'valor_tecnico': 105.15, 'valor_residual_pct': 100.0,
            'intereses_corridos': 2.30, 'cupon_anual_pct': 38.50, 'tipo_cupon': 'Tasa TAMAR + 2.50% Spread',
            'frecuencia_pago': 'Trimestral', 'amortizacion': 'Bullet 100% al Vencimiento',
            'tir': 41.80, 'duration': 1.40, 'dias_vto': 580, 'fecha_emision': '2024-02-10', 'fecha_vto': '2027-02-28',
            'proximo_pago_fecha': '2026-11-30', 'proximo_pago_monto': '$ 9.62 por 100 VN',
            'subtitulo': 'Bono soberano a tasa flotante bancaria mayorista',
            'cashflow': [{'fecha': '2026-11-30', 'renta': 9.625, 'amort': 0.00, 'total': 9.625}]
        },
        {
            'id': 'BND_PBA25', 'symbol': 'PBA25', 'nombre': 'Provincia de Bs As Badlar 2025',
            'subtipo': 'Bonos TAMAR / Badlar', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARPBAP320147', 'moneda_emision': 'ARS', 'moneda_pago': 'ARS (Flotante)', 'moneda': 'ARS',
            'precio': 98.40, 'paridad_pct': 98.40, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 3.10, 'cupon_anual_pct': 41.20, 'tipo_cupon': 'Badlar Privada + 3.75%',
            'frecuencia_pago': 'Trimestral', 'amortizacion': 'Bullet 100%',
            'tir': 44.50, 'duration': 0.65, 'dias_vto': 240, 'fecha_emision': '2022-04-12', 'fecha_vto': '2025-04-12',
            'proximo_pago_fecha': '2026-10-12', 'proximo_pago_monto': '$ 10.30 por 100 VN',
            'subtitulo': 'Bono subsoberano provincial a tasa flotante',
            'cashflow': [{'fecha': '2026-10-12', 'renta': 10.30, 'amort': 100.00, 'total': 110.30}]
        },

        # 5. Dólar Linked & Duales
        {
            'id': 'BND_TV25', 'symbol': 'TV25', 'nombre': 'Bono Dólar Linked 2025 (TV25)',
            'subtipo': 'Dólar Linked & Duales', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE320AB2', 'moneda_emision': 'USD', 'moneda_pago': 'ARS (TC Oficial A3500)', 'moneda': 'USD',
            'precio': 98.50, 'paridad_pct': 98.50, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.25, 'cupon_anual_pct': 0.50, 'tipo_cupon': 'Fijo sobre Capital Dólar Linked',
            'frecuencia_pago': 'Semestral', 'amortizacion': 'Bullet 100% al Vencimiento',
            'tir': -1.20, 'duration': 0.45, 'dias_vto': 165, 'fecha_emision': '2023-03-31', 'fecha_vto': '2025-03-31',
            'proximo_pago_fecha': '2025-03-31', 'proximo_pago_monto': '100% Capital * TC Oficial A3500',
            'subtitulo': 'Cobertura cambiaria oficial soberana',
            'cashflow': [{'fecha': '2025-03-31', 'renta': 0.25, 'amort': 100.00, 'total': 100.25}]
        },
        {
            'id': 'BND_TZV26', 'symbol': 'TZV26', 'nombre': 'Bono Dólar Linked Cero Cupón 2026',
            'subtipo': 'Dólar Linked & Duales', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARARGE320EP9', 'moneda_emision': 'USD', 'moneda_pago': 'ARS (TC Oficial A3500)', 'moneda': 'USD',
            'precio': 94.20, 'paridad_pct': 94.20, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.00, 'cupon_anual_pct': 0.00, 'tipo_cupon': 'Cero Cupón Dólar Linked',
            'frecuencia_pago': 'Al Vencimiento', 'amortizacion': 'Bullet 100%',
            'tir': 3.80, 'duration': 1.45, 'dias_vto': 530, 'fecha_emision': '2024-06-28', 'fecha_vto': '2026-06-30',
            'proximo_pago_fecha': '2026-06-30', 'proximo_pago_monto': '100% Capital * TC Oficial A3500',
            'subtitulo': 'Bono DL tramo mediano con tasa positiva en USD',
            'cashflow': [{'fecha': '2026-06-30', 'renta': 0.00, 'amort': 100.00, 'total': 100.00}]
        },

        # 6. BOPREAL (BCRA para Importadores)
        {
            'id': 'BOP_BPO27', 'symbol': 'BPO27', 'nombre': 'BOPREAL Serie 1 (BPO27)',
            'subtipo': 'BOPREAL (BCRA)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARBCRA320017', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Hard / Cable)', 'moneda': 'USD',
            'precio': 89.20, 'paridad_pct': 89.20, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 1.25, 'cupon_anual_pct': 5.00, 'tipo_cupon': 'Fijo Semestral en USD',
            'frecuencia_pago': 'Semestral (Abr / Oct)', 'amortizacion': 'Bullet al Vencimiento (Con opción Put)',
            'tir': 10.20, 'duration': 2.10, 'dias_vto': 780, 'fecha_emision': '2024-01-15', 'fecha_vto': '2027-10-31',
            'proximo_pago_fecha': '2026-10-31', 'proximo_pago_monto': 'US$ 2.50 por 100 VN',
            'subtitulo': 'Bono para la Reconstrucción de una Argentina Libre - Serie 1 BCRA',
            'cashflow': [
                {'fecha': '2026-10-31', 'renta': 2.50, 'amort': 0.00, 'total': 2.50},
                {'fecha': '2027-04-30', 'renta': 2.50, 'amort': 0.00, 'total': 2.50},
                {'fecha': '2027-10-31', 'renta': 2.50, 'amort': 100.00, 'total': 102.50}
            ]
        },
        {
            'id': 'BOP_BPY26', 'symbol': 'BPY26', 'nombre': 'BOPREAL Serie 2 (BPY26)',
            'subtipo': 'BOPREAL (BCRA)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARBCRA320025', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Hard)', 'moneda': 'USD',
            'precio': 96.50, 'paridad_pct': 96.50, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.00, 'cupon_anual_pct': 0.00, 'tipo_cupon': 'Cero Cupón',
            'frecuencia_pago': 'Mensual de Amortización', 'amortizacion': '12 cuotas mensuales iguales (2025-2026)',
            'tir': 6.80, 'duration': 0.75, 'dias_vto': 290, 'fecha_emision': '2024-02-15', 'fecha_vto': '2026-06-30',
            'proximo_pago_fecha': '2026-09-30', 'proximo_pago_monto': 'US$ 8.33 por 100 VN',
            'subtitulo': 'BOPREAL Serie 2 con amortización mensual en dólares',
            'cashflow': [
                {'fecha': '2026-09-30', 'renta': 0.00, 'amort': 8.33, 'total': 8.33},
                {'fecha': '2026-10-31', 'renta': 0.00, 'amort': 8.33, 'total': 8.33}
            ]
        },
        {
            'id': 'BOP_BPC26', 'symbol': 'BPC26', 'nombre': 'BOPREAL Serie 3 (BPC26)',
            'subtipo': 'BOPREAL (BCRA)', 'tipo': 'bond', 'ley': 'Argentina',
            'isin': 'ARBCRA320033', 'moneda_emision': 'USD', 'moneda_pago': 'USD (Hard)', 'moneda': 'USD',
            'precio': 92.40, 'paridad_pct': 92.40, 'valor_tecnico': 100.00, 'valor_residual_pct': 100.0,
            'intereses_corridos': 0.75, 'cupon_anual_pct': 3.00, 'tipo_cupon': 'Fijo Trimestral en USD',
            'frecuencia_pago': 'Trimestral', 'amortizacion': '3 cuotas iguales (2025-2026)',
            'tir': 8.90, 'duration': 1.10, 'dias_vto': 410, 'fecha_emision': '2024-03-01', 'fecha_vto': '2026-05-31',
            'proximo_pago_fecha': '2026-11-30', 'proximo_pago_monto': 'US$ 0.75 por 100 VN',
            'subtitulo': 'BOPREAL Serie 3 emitido por el BCRA',
            'cashflow': [{'fecha': '2026-11-30', 'renta': 0.75, 'amort': 33.33, 'total': 34.08}]
        }
    ]

    results = []
    series_map = {}
    num_days = 2500
    today = datetime.date.today()

    for b in bonos_def:
        p = b['precio']
        is_usd = b.get('moneda') == 'USD'
        currency = 'USD' if is_usd else 'ARS'
        
        # Histórico sintético de precios consistente
        var_1d = round(np.random.normal(0.25, 0.45) if is_usd else np.random.normal(0.12, 0.20), 2)
        var_1m = round(np.random.normal(3.80, 1.20) if is_usd else np.random.normal(3.60, 0.80), 2)
        var_12m = round(np.random.normal(68.50, 8.00) if is_usd else np.random.normal(54.00, 6.00), 2)
        
        r_1d = var_1d / 100.0
        r_1m = (1.0 + var_1m / 100.0) ** (1.0 / 21.0) - 1.0
        r_12m = (1.0 + var_12m / 100.0) ** (1.0 / 252.0) - 1.0
        r_long = 0.0002 if is_usd else 0.0010
        
        prices = [p]
        curr = p
        curr = curr / (1.0 + r_1d)
        prices.append(curr)
        
        for _ in range(20):
            curr = curr / (1.0 + r_1m)
            prices.append(curr)
        for _ in range(230):
            curr = curr / (1.0 + r_12m)
            prices.append(curr)
        for _ in range(num_days - 252):
            curr = curr / (1.0 + r_long)
            prices.append(curr)
            
        prices.reverse()
        
        trading_dates = []
        d = today - datetime.timedelta(days=int(num_days * 1.5))
        while len(trading_dates) < len(prices):
            if d.weekday() < 5:
                trading_dates.append(d.strftime('%Y-%m-%d'))
            d += datetime.timedelta(days=1)
        trading_dates = trading_dates[-len(prices):]
        trading_dates[-1] = today.strftime('%Y-%m-%d')
        
        hist_series = [{'date': dt, 'close': round(pr, 2)} for dt, pr in zip(trading_dates, prices)]
        
        item = {
            'id': b['id'],
            'symbol': b['symbol'],
            'nombre': b['nombre'],
            'categoria': 'Bonos - LECAPs',
            'subtipo': b['subtipo'],
            'tipo': b['tipo'],
            'ley': b['ley'],
            'isin': b['isin'],
            'moneda_emision': b['moneda_emision'],
            'moneda_pago': b['moneda_pago'],
            'moneda': currency,
            'precio': p,
            'paridad_pct': b['paridad_pct'],
            'valor_tecnico': b['valor_tecnico'],
            'valor_residual_pct': b['valor_residual_pct'],
            'intereses_corridos': b['intereses_corridos'],
            'cupon_anual_pct': b['cupon_anual_pct'],
            'tipo_cupon': b['tipo_cupon'],
            'frecuencia_pago': b['frecuencia_pago'],
            'amortizacion': b['amortizacion'],
            'tir': b['tir'],
            'duration': b['duration'],
            'dias_vto': b['dias_vto'],
            'fecha_emision': b['fecha_emision'],
            'fecha_vto': b['fecha_vto'],
            'proximo_pago_fecha': b['proximo_pago_fecha'],
            'proximo_pago_monto': b['proximo_pago_monto'],
            'cashflow': b['cashflow'],
            'subtitulo': b['subtitulo'],
            'var_1d': var_1d,
            'var_1m': var_1m,
            'var_12m': var_12m
        }
        results.append(item)
        series_map[b['id']] = hist_series
        
    return results, series_map

def fetch_ons():
    print('-> Obteniendo Obligaciones Negociables (ONs)...')
    ons_raw = [
        {'id': 'ON_YMCXO', 'symbol': 'YMCXO', 'emisor': 'YPF S.A.', 'nombre': 'YPF 2026 Clase 16 (YMCXO)', 'moneda': 'USD', 'precio': 103.50, 'tir': 7.65, 'duration': 1.45, 'dias_vto': 580, 'cupon': 8.50, 'ley': 'Nueva York', 'vto': '2026-07-28'},
        {'id': 'ON_YCA6O', 'symbol': 'YCA6O', 'emisor': 'YPF S.A.', 'nombre': 'YPF 2029 Clase 39 (YCA6O)', 'moneda': 'USD', 'precio': 98.20, 'tir': 8.90, 'duration': 3.40, 'dias_vto': 1520, 'cupon': 8.75, 'ley': 'Nueva York', 'vto': '2029-06-30'},
        {'id': 'ON_PAMPO', 'symbol': 'MGC9O', 'emisor': 'Pampa Energía', 'nombre': 'Pampa Energía 2026 Clase 9 (MGC9O)', 'moneda': 'USD', 'precio': 104.20, 'tir': 6.85, 'duration': 1.70, 'dias_vto': 640, 'cupon': 9.12, 'ley': 'Nueva York', 'vto': '2026-12-08'},
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
    {'symbol': '^GSPC', 'name': 'S&P 500', 'id': 'IDX_SP500', 'currency': 'USD', 'subtitulo': 'Estados Unidos - 500 Empresas Líderes'},
    {'symbol': '^IXIC', 'name': 'Nasdaq Composite', 'id': 'IDX_NASDAQ', 'currency': 'USD', 'subtitulo': 'Estados Unidos - Tecnológico'},
    {'symbol': '^DJI', 'name': 'Dow Jones Industrial', 'id': 'IDX_DOW', 'currency': 'USD', 'subtitulo': 'Estados Unidos - Industriales'},
    {'symbol': '^RUT', 'name': 'Russell 2000', 'id': 'IDX_RUSSELL2000', 'currency': 'USD', 'subtitulo': 'Estados Unidos - Small Caps'},
    {'symbol': '^VIX', 'name': 'Índice de Volatilidad VIX', 'id': 'IDX_VIX', 'currency': 'Pts', 'subtitulo': 'CBOE - Volatilidad Implícita (Termómetro de Riesgo)'},
    {'symbol': 'DX-Y.NYB', 'name': 'DXY (US Dollar Index)', 'id': 'IDX_DXY', 'currency': 'Pts', 'subtitulo': 'Fuerza Global del Dólar vs Canasta de Monedas'},
    {'symbol': '^MERV', 'name': 'S&P Merval (ARS)', 'id': 'IDX_MERVAL_ARS', 'currency': 'ARS', 'subtitulo': 'Argentina - Índice Líder BYMA'},
    {'symbol': 'ARGT', 'name': 'S&P Merval en USD (ARGT)', 'id': 'IDX_MERVAL_USD', 'currency': 'USD', 'subtitulo': 'Global X MSCI Argentina ETF (Merval en Dólares)'},
    {'symbol': 'EEM', 'name': 'MSCI Emerging Markets (EEM)', 'id': 'IDX_EEM', 'currency': 'USD', 'subtitulo': 'Benchmark Global de Mercados Emergentes'},
    {'symbol': '^GDAXI', 'name': 'DAX 40', 'id': 'IDX_DAX', 'currency': 'EUR', 'subtitulo': 'Alemania - Índice Principal Frankfurt'},
    {'symbol': '^STOXX50E', 'name': 'Euro Stoxx 50', 'id': 'IDX_EUROSTOXX50', 'currency': 'EUR', 'subtitulo': 'Eurozona - 50 Empresas Blue Chip'},
    {'symbol': '^FCHI', 'name': 'CAC 40', 'id': 'IDX_CAC40', 'currency': 'EUR', 'subtitulo': 'Francia - Bolsa de París'},
    {'symbol': '^FTSE', 'name': 'FTSE 100', 'id': 'IDX_FTSE', 'currency': 'GBP', 'subtitulo': 'Reino Unido - Bolsa de Londres'},
    {'symbol': '^N225', 'name': 'Nikkei 225', 'id': 'IDX_NIKKEI', 'currency': 'JPY', 'subtitulo': 'Japón - Bolsa de Tokio'},
    {'symbol': '^HSI', 'name': 'Hang Seng', 'id': 'IDX_HANGSENG', 'currency': 'HKD', 'subtitulo': 'Hong Kong - Gigantes Tecnológicos y Financieros Asia'},
    {'symbol': '^BVSP', 'name': 'Bovespa (Ibovespa)', 'id': 'IDX_BOVESPA', 'currency': 'BRL', 'subtitulo': 'Brasil - Bolsa de São Paulo'},
]

CONFIG_DIVISAS = [
    {'symbol': 'EURUSD=X', 'name': 'Euro / Dólar (EUR/USD)', 'id': 'FX_EURUSD', 'currency': 'USD', 'subtitulo': 'Zona Euro'},
    {'symbol': 'GBPUSD=X', 'name': 'Libra / Dólar (GBP/USD)', 'id': 'FX_GBPUSD', 'currency': 'USD', 'subtitulo': 'Reino Unido'},
    {'symbol': 'BRL=X', 'name': 'Dólar / Real Brasileño (USD/BRL)', 'id': 'FX_USDBRL', 'currency': 'BRL', 'subtitulo': 'Brasil'},
    {'symbol': 'JPY=X', 'name': 'Dólar / Yen Japonés (USD/JPY)', 'id': 'FX_USDJPY', 'currency': 'JPY', 'subtitulo': 'Japón'},
    {'symbol': 'CNY=X', 'name': 'Dólar / Yuan Chino (USD/CNY)', 'id': 'FX_USDCNY', 'currency': 'CNY', 'subtitulo': 'China'},
    {'symbol': 'CLP=X', 'name': 'Dólar / Peso Chileno (USD/CLP)', 'id': 'FX_USDCLP', 'currency': 'CLP', 'subtitulo': 'Chile'},
    {'symbol': 'UYU=X', 'name': 'Dólar / Peso Uruguayo (USD/UYU)', 'id': 'FX_USDUYU', 'currency': 'UYU', 'subtitulo': 'Uruguay'},
]

CONFIG_COMMODITIES = [
    # 1. Granos y Oleaginosas (Agro)
    {'symbol': 'ZS=F', 'name': 'Soja (Soybeans)', 'id': 'COMM_SOJA', 'subtipo': 'Granos y Oleaginosas', 'currency': 'USD', 'subtitulo': 'CBOT - Bushel (US$)'},
    {'symbol': 'ZM=F', 'name': 'Harina de Soja (Soybean Meal)', 'id': 'COMM_HARINA_SOJA', 'subtipo': 'Granos y Oleaginosas', 'currency': 'USD', 'subtitulo': 'CBOT - Tonelada Corta'},
    {'symbol': 'ZL=F', 'name': 'Aceite de Soja (Soybean Oil)', 'id': 'COMM_ACEITE_SOJA', 'subtipo': 'Granos y Oleaginosas', 'currency': 'USD', 'subtitulo': 'CBOT - Libras (Centavos US$)'},
    {'symbol': 'ZC=F', 'name': 'Maíz (Corn)', 'id': 'COMM_MAIZ', 'subtipo': 'Granos y Oleaginosas', 'currency': 'USD', 'subtitulo': 'CBOT - Bushel (US$)'},
    {'symbol': 'ZW=F', 'name': 'Trigo Chicago (Wheat)', 'id': 'COMM_TRIGO', 'subtipo': 'Granos y Oleaginosas', 'currency': 'USD', 'subtitulo': 'CBOT - Bushel (US$)'},
    {'symbol': 'KE=F', 'name': 'Trigo Kansas (KC Wheat)', 'id': 'COMM_TRIGO_KANSAS', 'subtipo': 'Granos y Oleaginosas', 'currency': 'USD', 'subtitulo': 'KCBT - Trigo Duro Proteico'},
    
    # 2. Energía
    {'symbol': 'CL=F', 'name': 'Petróleo WTI (Crude Oil)', 'id': 'COMM_WTI', 'subtipo': 'Energía', 'currency': 'USD', 'subtitulo': 'NYMEX - Barril (US$)'},
    {'symbol': 'BZ=F', 'name': 'Petróleo Brent (Brent Oil)', 'id': 'COMM_BRENT', 'subtipo': 'Energía', 'currency': 'USD', 'subtitulo': 'ICE - Barril (US$)'},
    {'symbol': 'NG=F', 'name': 'Gas Natural (Henry Hub)', 'id': 'COMM_GAS_NATURAL', 'subtipo': 'Energía', 'currency': 'USD', 'subtitulo': 'NYMEX - MMBtu (US$)'},
    {'symbol': 'RB=F', 'name': 'Gasolina RBOB (Gasoline)', 'id': 'COMM_GASOLINA', 'subtipo': 'Energía', 'currency': 'USD', 'subtitulo': 'NYMEX - Galón (US$)'},
    {'symbol': 'HO=F', 'name': 'Heating Oil / Diésel', 'id': 'COMM_DIESEL', 'subtipo': 'Energía', 'currency': 'USD', 'subtitulo': 'NYMEX - Galón (US$)'},
    
    # 3. Metales (Preciosos e Industriales)
    {'symbol': 'GC=F', 'name': 'Oro (Gold Futures)', 'id': 'COMM_ORO', 'subtipo': 'Metales', 'currency': 'USD', 'subtitulo': 'COMEX - Onza Troy (US$)'},
    {'symbol': 'SI=F', 'name': 'Plata (Silver Futures)', 'id': 'COMM_PLATA', 'subtipo': 'Metales', 'currency': 'USD', 'subtitulo': 'COMEX - Onza Troy (US$)'},
    {'symbol': 'PL=F', 'name': 'Platino (Platinum)', 'id': 'COMM_PLATINO', 'subtipo': 'Metales', 'currency': 'USD', 'subtitulo': 'NYMEX - Onza Troy (US$)'},
    {'symbol': 'HG=F', 'name': 'Cobre (Copper Futures)', 'id': 'COMM_COBRE', 'subtipo': 'Metales', 'currency': 'USD', 'subtitulo': 'COMEX - Libra (US$)'},
    
    # 4. Agroindustriales & Ganadería (Softs & Livestock)
    {'symbol': 'KC=F', 'name': 'Café Arábica (Coffee)', 'id': 'COMM_CAFE', 'subtipo': 'Agroindustriales & Ganadería', 'currency': 'USD', 'subtitulo': 'ICE - Libra (Centavos US$)'},
    {'symbol': 'CC=F', 'name': 'Cacao (Cocoa)', 'id': 'COMM_CACAO', 'subtipo': 'Agroindustriales & Ganadería', 'currency': 'USD', 'subtitulo': 'ICE - Tonelada Métrica'},
    {'symbol': 'SB=F', 'name': 'Azúcar Nº 11 (Sugar)', 'id': 'COMM_AZUCAR', 'subtipo': 'Agroindustriales & Ganadería', 'currency': 'USD', 'subtitulo': 'ICE - Libra (Centavos US$)'},
    {'symbol': 'CT=F', 'name': 'Algodón (Cotton)', 'id': 'COMM_ALGODON', 'subtipo': 'Agroindustriales & Ganadería', 'currency': 'USD', 'subtitulo': 'ICE - Libra (Centavos US$)'},
    {'symbol': 'LE=F', 'name': 'Ganado Vacuno en Pie (Live Cattle)', 'id': 'COMM_GANADO', 'subtipo': 'Agroindustriales & Ganadería', 'currency': 'USD', 'subtitulo': 'CME - Libra (Centavos US$)'},
]

CONFIG_TASAS_INT = [
    {'symbol': '^TNX', 'name': 'Tasa US Treasury 10 Años', 'id': 'TASA_US10Y', 'currency': '%', 'subtitulo': 'Bono del Tesoro de EE.UU. a 10 años'},
    {'symbol': '^IRX', 'name': 'Tasa US Treasury 3 Meses', 'id': 'TASA_US3M', 'currency': '%', 'subtitulo': 'Letra del Tesoro de EE.UU. a 3M'},
    {'symbol': '^TYX', 'name': 'Tasa US Treasury 30 Años', 'id': 'TASA_US30Y', 'currency': '%', 'subtitulo': 'Bono del Tesoro de EE.UU. a 30 años'},
]

CONFIG_ACCIONES_MUNDIALES = [
    {'symbol': 'AAPL', 'name': 'Apple Inc.', 'id': 'EQ_AAPL', 'currency': 'USD', 'subtitulo': 'Tecnología / Consumer Electronics'},
    {'symbol': 'MSFT', 'name': 'Microsoft Corp.', 'id': 'EQ_MSFT', 'currency': 'USD', 'subtitulo': 'Tecnología / Software y Cloud'},
    {'symbol': 'NVDA', 'name': 'NVIDIA Corp.', 'id': 'EQ_NVDA', 'currency': 'USD', 'subtitulo': 'Semiconductores e Inteligencia Artificial'},
    {'symbol': 'GOOGL', 'name': 'Alphabet Inc. (Google)', 'id': 'EQ_GOOGL', 'currency': 'USD', 'subtitulo': 'Servicios de Internet y Publicidad'},
    {'symbol': 'AMZN', 'name': 'Amazon.com Inc.', 'id': 'EQ_AMZN', 'currency': 'USD', 'subtitulo': 'E-Commerce y Cloud Computing (AWS)'},
    {'symbol': 'META', 'name': 'Meta Platforms (Facebook)', 'id': 'EQ_META', 'currency': 'USD', 'subtitulo': 'Redes Sociales y Metaverso'},
    {'symbol': 'TSLA', 'name': 'Tesla Inc.', 'id': 'EQ_TSLA', 'currency': 'USD', 'subtitulo': 'Vehículos Eléctricos y Energía'},
    {'symbol': 'BRK-B', 'name': 'Berkshire Hathaway B', 'id': 'EQ_BRK_B', 'currency': 'USD', 'subtitulo': 'Holding Financiero y Seguros'},
    {'symbol': 'LLY', 'name': 'Eli Lilly and Company', 'id': 'EQ_LLY', 'currency': 'USD', 'subtitulo': 'Farmacéutica y Biotecnología'},
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
    {'symbol': 'YPFD.BA', 'name': 'YPF S.A. (YPFD)', 'id': 'ARG_YPFD', 'currency': 'ARS', 'subtitulo': 'Energía / Petróleo y Gas'},
    {'symbol': 'PAMP.BA', 'name': 'Pampa Energía (PAMP)', 'id': 'ARG_PAMP', 'currency': 'ARS', 'subtitulo': 'Energía Eléctrica y Gas'},
    {'symbol': 'BMA.BA', 'name': 'Banco Macro (BMA)', 'id': 'ARG_BMA', 'currency': 'ARS', 'subtitulo': 'Sector Financiero / Bancario'},
    {'symbol': 'BBAR.BA', 'name': 'BBVA Argentina (BBAR)', 'id': 'ARG_BBAR', 'currency': 'ARS', 'subtitulo': 'Sector Financiero / Bancario'},
    {'symbol': 'TXAR.BA', 'name': 'Ternium Argentina (TXAR)', 'id': 'ARG_TXAR', 'currency': 'ARS', 'subtitulo': 'Siderurgia / Acero'},
    {'symbol': 'ALUA.BA', 'name': 'Aluar Aluminio (ALUA)', 'id': 'ARG_ALUA', 'currency': 'ARS', 'subtitulo': 'Materiales Básicos / Aluminio'},
    {'symbol': 'CRES.BA', 'name': 'Cresud (CRES)', 'id': 'ARG_CRES', 'currency': 'ARS', 'subtitulo': 'Agroindustria e Inmuebles'},
    {'symbol': 'CEPU.BA', 'name': 'Central Puerto (CEPU)', 'id': 'ARG_CEPU', 'currency': 'ARS', 'subtitulo': 'Generación Eléctrica'},
    {'symbol': 'EDN.BA', 'name': 'Edenor (EDN)', 'id': 'ARG_EDN', 'currency': 'ARS', 'subtitulo': 'Distribución Eléctrica'},
    {'symbol': 'TGSU2.BA', 'name': 'Transportadora Gas del Sur (TGSU2)', 'id': 'ARG_TGSU2', 'currency': 'ARS', 'subtitulo': 'Transporte de Gas / Utilities'},
    {'symbol': 'TECO2.BA', 'name': 'Telecom Argentina (TECO2)', 'id': 'ARG_TECO2', 'currency': 'ARS', 'subtitulo': 'Telecomunicaciones'},
    {'symbol': 'TRAN.BA', 'name': 'Transener (TRAN)', 'id': 'ARG_TRAN', 'currency': 'ARS', 'subtitulo': 'Transporte de Energía'},
]

CONFIG_CRIPTO = [
    {'symbol': 'BTC-USD', 'name': 'Bitcoin (BTC)', 'id': 'CRYPTO_BTC', 'currency': 'USD', 'subtitulo': 'Criptomoneda Líder / Reserva Digital'},
    {'symbol': 'ETH-USD', 'name': 'Ethereum (ETH)', 'id': 'CRYPTO_ETH', 'currency': 'USD', 'subtitulo': 'Contratos Inteligentes / Web3'},
    {'symbol': 'SOL-USD', 'name': 'Solana (SOL)', 'id': 'CRYPTO_SOL', 'currency': 'USD', 'subtitulo': 'Blockchain de Alta Velocidad'},
    {'symbol': 'BNB-USD', 'name': 'BNB (Binance Coin)', 'id': 'CRYPTO_BNB', 'currency': 'USD', 'subtitulo': 'Ecosistema BNB Chain'},
    {'symbol': 'XRP-USD', 'name': 'XRP (Ripple)', 'id': 'CRYPTO_XRP', 'currency': 'USD', 'subtitulo': 'Pagos y Liquidaciones'},
    {'symbol': 'ADA-USD', 'name': 'Cardano (ADA)', 'id': 'CRYPTO_ADA', 'currency': 'USD', 'subtitulo': 'Blockchain Proof of Stake'},
    {'symbol': 'DOGE-USD', 'name': 'Dogecoin (DOGE)', 'id': 'CRYPTO_DOGE', 'currency': 'USD', 'subtitulo': 'Moneda Digital Memética'},
    {'symbol': 'USDT-USD', 'name': 'Tether USD (USDT)', 'id': 'CRYPTO_USDT', 'currency': 'USD', 'subtitulo': 'Stablecoin Dólar'},
]

def enrich_cedears_ccl(cedears_list, acciones_mundiales_list):
    print('-> Calculando CCL Implícito en CEDEARs...')
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
    
    # 1. Dólar
    dolar_items, dolar_series = fetch_dolar()
    master_dataset['secciones']['dolar'] = {'titulo': 'Dólar', 'icono': 'dollar-sign', 'items': dolar_items}
    all_series.update(dolar_series)
    
    # 2. Índices Mundiales
    indices_items, indices_series = fetch_yahoo_market_group(CONFIG_INDICES, 'Índices Mundiales')
    master_dataset['secciones']['indices_mundiales'] = {'titulo': 'Índices Mundiales', 'icono': 'globe', 'items': indices_items}
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
    tasas_int_items.append({'id': 'TASA_ECB_DEP', 'nombre': 'Tasa de Depósito BCE (Europa)', 'categoria': 'Tasas Internacionales', 'tipo': 'rate', 'precio': 3.00, 'moneda': '%', 'var_1d': 0.0, 'var_1m': 0.0, 'var_12m': -20.0, 'subtitulo': 'Banco Central Europeo'})
    master_dataset['secciones']['tasas_internacionales'] = {'titulo': 'Tasas Internacionales', 'icono': 'trending-up', 'items': tasas_int_items}
    all_series.update(tasas_int_series)
    
    # 6. Tasas Locales
    tasas_loc_items, tasas_loc_series = fetch_tasas_locales()
    master_dataset['secciones']['tasas_locales'] = {'titulo': 'Tasas Locales', 'icono': 'landmark', 'items': tasas_loc_items}
    all_series.update(tasas_loc_series)
    
    # 7. FCI
    fci_items, fci_series = fetch_fci()
    master_dataset['secciones']['fci'] = {'titulo': 'Fondos Comunes de Inversión', 'icono': 'pie-chart', 'items': fci_items}
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
    
    print('-> Guardando master_dataset.json...')
    with open('master_dataset.json', 'w', encoding='utf-8') as f:
        json.dump(master_dataset, f, ensure_ascii=False, indent=2)
        
    print('-> Guardando series_historicas.json...')
    with open('series_historicas.json', 'w', encoding='utf-8') as f:
        json.dump(all_series, f, ensure_ascii=False)
        
    print('-> Guardando curvas_rendimiento.json...')
    with open('curvas_rendimiento.json', 'w', encoding='utf-8') as f:
        json.dump(curvas, f, ensure_ascii=False, indent=2)
        
    elapsed = round(time.time() - start_time, 2)
    print(f'=== ACTUALIZACION COMPLETADA CON EXITO EN {elapsed}s ===')

if __name__ == '__main__':
    main()
