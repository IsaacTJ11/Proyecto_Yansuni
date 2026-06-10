"""
app.py - Servidor Flask principal para ASOPRIABET Aromas del Yasuní.
Sistema de Planificación y Control de la Producción.
"""
import os
import json
import base64
import io
import math
import calendar
from datetime import datetime, date
from functools import lru_cache

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import matplotlib.dates as mdates
import matplotlib.lines
import locale
from flask import Flask, render_template, request, jsonify, send_from_directory

from calculos import (
    cargar_demanda, guardar_demanda,
    cargar_productos, guardar_productos,
    cargar_operarios, guardar_operarios,
    cargar_pronosticos, guardar_pronosticos,
    ejecutar_pronostico_completo,
    calcular_pap_todos, resumen_pap,
    obtener_nombres_productos,
    guardar_sesion, cargar_sesion, verificar_login,
    guardar_estado_calculo, cargar_estado_calculo,
    verificar_ceros_demanda_todos, necesita_recalculo,
)

app = Flask(__name__)

# ─── PALETA DE COLORES POR PRODUCTO ───────────────────────────────────────────
PRODUCT_COLORS = [
    '#7B3F00',  # chocolate oscuro
    '#C17817',  # dorado cacao
    '#2D6A2D',  # verde yasuní
    '#D4501A',  # naranja tierra
    '#5C3317',  # café oscuro
    '#8B6914',  # ámbar
    '#1A5C3A',  # verde selva
    '#B84A1A',  # terracota
    '#4A2C6E',  # violeta
    '#1A4A6E',  # azul petróleo
]
FORECAST_COLOR = '#E8A020'   # ámbar pronóstico (no coincide con ningún producto)
ACCENT_COLOR   = '#7B3F00'   # chocolate principal

def color_producto(idx):
    return PRODUCT_COLORS[idx % len(PRODUCT_COLORS)]


def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_b64


def fmt_moneda(val):
    try:
        return f"${val:,.2f}"
    except Exception:
        return str(val)


def fmt_num(val):
    try:
        return f"{int(round(val)):,}"
    except Exception:
        return str(val)


# ─── HELPERS GRÁFICOS ────────────────────────────────────────────────────────

# Configurar locale español para nombres de meses
try:
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252')
    except:
        # Fallback: usar configuración por defecto del sistema
        pass

def estilo_base(ax, title='', xlabel='', ylabel=''):
    ax.set_facecolor('#FAFAF8')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CCCCCC')
    ax.spines['bottom'].set_color('#CCCCCC')
    ax.tick_params(colors='#555555', labelsize=20)  # Doubled from 10
    ax.grid(axis='y', color='#EEEEEE', linewidth=0.7)
    if title:
        ax.set_title(title, fontsize=24, fontweight='bold', color='#3A2000', pad=8)  # Doubled from 12
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=20, color='#555555')  # Doubled from 10
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=20, color='#555555')  # Doubled from 10


def format_fecha_espanol(fecha):
    """Formatea fecha en español."""
    meses_es = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 
                'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    return f"{meses_es[fecha.month - 1]} {fecha.year}"

MESES_ABREV = ['Ene.','Feb.','Mar.','Abr.','May.','Jun.',
               'Jul.','Ago.','Sep.','Oct.','Nov.','Dic.']

def format_mes_abrev(fecha):
    """Formatea fecha como 'Ene. 2026'."""
    return f"{MESES_ABREV[fecha.month - 1]} {fecha.year}"

# ─── RUTAS PRINCIPALES ───────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


# ─── API: DATOS GENERALES ────────────────────────────────────────────────────

@app.route('/api/productos')
def api_productos():
    df = cargar_productos()
    return jsonify(df.to_dict(orient='records'))


@app.route('/api/nombres_productos')
def api_nombres_productos():
    df_dem = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)
    return jsonify(nombres)


@app.route('/api/operarios')
def api_operarios():
    return jsonify(cargar_operarios())


# ─── API: LOGIN & SESIÓN ────────────────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def api_login():
    """Verifica login para modificación de valores."""
    data = request.json
    password = data.get('password', '')
    
    if verificar_login(password):
        sesion = {
            'autenticado': True,
            'timestamp': datetime.now().isoformat()
        }
        guardar_sesion(sesion)
        return jsonify({'success': True, 'message': 'Login exitoso'})
    else:
        return jsonify({'success': False, 'message': 'Contraseña incorrecta'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    """Cierra sesión."""
    try:
        import os
        from calculos import SESSION_DIR
        session_file = os.path.join(SESSION_DIR, 'session.json')
        if os.path.exists(session_file):
            os.remove(session_file)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/sesion')
def api_sesion():
    """Verifica estado de sesión."""
    sesion = cargar_sesion()
    if sesion and sesion.get('autenticado'):
        return jsonify({'autenticado': True})
    return jsonify({'autenticado': False})


# ─── API: MODO Y FECHA ───────────────────────────────────────────────────────────

@app.route('/api/set_modo', methods=['POST'])
def api_set_modo():
    """Establece modo de operación (prueba/producción)."""
    data = request.json
    modo = data.get('modo', 'produccion')
    fecha_actual = data.get('fecha_actual')  # formato YYYY-MM-DD para modo prueba
    
    sesion = cargar_sesion() or {}
    sesion['modo'] = modo
    sesion['fecha_actual'] = fecha_actual
    guardar_sesion(sesion)
    
    return jsonify({'success': True, 'modo': modo, 'fecha_actual': fecha_actual})


@app.route('/api/get_modo')
def api_get_modo():
    """Obtiene modo actual y fecha."""
    sesion = cargar_sesion()
    modo = sesion.get('modo', 'produccion') if sesion else 'produccion'
    fecha_actual = sesion.get('fecha_actual') if sesion else None
    
    return jsonify({
        'modo': modo,
        'fecha_actual': fecha_actual
    })


# ─── API: VERIFICACIÓN DE CEROS Y CÁLCULOS ────────────────────────────────────────

@app.route('/api/verificar_ceros')
def api_verificar_ceros():
    """Verifica si hay demandas = 0 después del periodo 1."""
    fecha_actual = request.args.get('fecha_actual')
    if not fecha_actual:
        hoy = pd.Timestamp.now().normalize()
        fecha_actual = hoy.strftime('%Y-%m-%d')
    
    df_dem = cargar_demanda()
    ceros = verificar_ceros_demanda_todos(df_dem, fecha_actual)
    
    return jsonify({
        'tiene_ceros': len(ceros) > 0,
        'ceros_por_producto': ceros
    })


@app.route('/api/necesita_recalculo')
def api_necesita_recalculo():
    """Verifica si es necesario recalcular."""
    modo = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')
    
    if not fecha_actual:
        hoy = pd.Timestamp.now().normalize()
        fecha_actual = hoy.strftime('%Y-%m-%d')
    
    necesita, razon = necesita_recalculo(modo, fecha_actual)
    
    return jsonify({
        'necesita': necesita,
        'razon': razon
    })


# ─── API: DATOS GENERALES ────────────────────────────────────────────────────


# ─── API: DASHBOARD ──────────────────────────────────────────────────────────

@app.route('/api/dashboard_kpis')
def api_dashboard_kpis():
    modo         = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_dem  = cargar_demanda()
    df_pron = cargar_pronosticos()
    nombres = obtener_nombres_productos(df_dem)
    op      = cargar_operarios()

    if modo == 'prueba' and fecha_actual:
        hoy = pd.Timestamp(fecha_actual).normalize()
    else:
        hoy = pd.Timestamp.now().normalize()
    mes_actual = hoy.replace(day=1)

    # Pronóstico próximos 3 meses desde mes actual del modo
    dem_pronosticada = 0
    if not df_pron.empty:
        fechas_fut = pd.date_range(mes_actual, periods=3, freq='MS')
        for prod in nombres:
            col = f'Pronostico_Demanda_{prod}'
            if col in df_pron.columns:
                filas = df_pron[df_pron['Mes'].isin(fechas_fut)]
                dem_pronosticada += int(filas[col].sum())

    # Inventario total actual
    df_prod   = cargar_productos()
    inv_total = int(df_prod['Inventario'].sum()) if 'Inventario' in df_prod.columns else 0

    # MAPE — usar merge en lugar de join
    mape_vals = []
    if not df_pron.empty:
        for prod in nombres:
            col_real = f'Demanda_{prod}'
            col_pron = f'Pronostico_Demanda_{prod}'
            if col_real in df_dem.columns and col_pron in df_pron.columns:
                df_r = df_dem[['Mes', col_real]].copy()
                df_p = df_pron[['Mes', col_pron]].copy()
                merged = pd.merge(df_r, df_p, on='Mes', how='inner').dropna()
                merged = merged[merged[col_real] > 0]
                if len(merged) > 0:
                    mape = float(
                        (abs(merged[col_real] - merged[col_pron]) / merged[col_real]).mean() * 100
                    )
                    mape_vals.append(mape)
    mape_global = round(float(np.mean(mape_vals)), 2) if mape_vals else 0

    return jsonify({
        'dem_pronosticada': fmt_num(dem_pronosticada),
        'inv_total':        fmt_num(inv_total),
        'operarios':        int(op['operarios']),
        'mape':             f"{mape_global:.2f}%",
        'n_productos':      len(nombres),
        'fecha':            hoy.strftime('%d/%m/%Y'),
    })

@app.route('/api/dashboard_kpis_producto')
def api_dashboard_kpis_producto():
    producto     = request.args.get('producto', 'Todos')
    modo         = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    if producto == 'Todos':
        # Redirigir internamente con los mismos parámetros
        from flask import redirect, url_for
        return api_dashboard_kpis()

    df_dem  = cargar_demanda()
    df_pron = cargar_pronosticos()
    df_prod = cargar_productos()

    if modo == 'prueba' and fecha_actual:
        hoy = pd.Timestamp(fecha_actual).normalize()
    else:
        hoy = pd.Timestamp.now().normalize()
    mes_actual = hoy.replace(day=1)

    col_dem  = f'Demanda_{producto}'
    col_pron = f'Pronostico_Demanda_{producto}'

    dem_pronosticada = 0
    if not df_pron.empty and col_pron in df_pron.columns:
        fechas_fut = pd.date_range(mes_actual, periods=3, freq='MS')
        filas = df_pron[df_pron['Mes'].isin(fechas_fut)]
        dem_pronosticada = int(filas[col_pron].sum())

    inv_producto    = 0
    precio_producto = 3.5
    for _, row in df_prod.iterrows():
        nombre_completo = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
        if nombre_completo == producto:
            inv_producto    = int(row.get('Inventario', 0))
            precio_producto = float(row.get('Precio Unitario ($)', 3.5))
            break

    mape_producto = 0
    if not df_pron.empty and col_dem in df_dem.columns and col_pron in df_pron.columns:
        df_r   = df_dem[['Mes', col_dem]].copy()
        df_p   = df_pron[['Mes', col_pron]].copy()
        merged = pd.merge(df_r, df_p, on='Mes', how='inner').dropna()
        merged = merged[merged[col_dem] > 0]
        if len(merged) > 0:
            mape_producto = float(
                (abs(merged[col_dem] - merged[col_pron]) / merged[col_dem]).mean() * 100
            )

    return jsonify({
        'dem_pronosticada': fmt_num(dem_pronosticada),
        'inv_total':        fmt_num(inv_producto),
        'operarios':        int(cargar_operarios()['operarios']),
        'mape':             f"{mape_producto:.2f}%",
        'n_productos':      1,
        'fecha':            hoy.strftime('%d/%m/%Y'),
        'precio_producto':  fmt_moneda(precio_producto),
    })

# ─── API: GRÁFICOS DASHBOARD ─────────────────────────────────────────────────

@app.route('/api/grafico_demanda_historica')
def api_grafico_demanda_historica():
    producto     = request.args.get('producto', 'Todos')
    meses        = int(request.args.get('meses', 12))
    modo         = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')
    tipo         = request.args.get('tipo', 'demanda')

    df_dem  = cargar_demanda()
    df_pron = cargar_pronosticos()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    if modo == 'prueba' and fecha_actual:
        mes_actual = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_actual = pd.Timestamp.now().normalize().replace(day=1)

    # Histórico: 12 meses ANTES del mes actual del modo
    fecha_inicio_hist = mes_actual - pd.DateOffset(months=12)
    df_hist = df_dem[
        (df_dem['Mes'] >= fecha_inicio_hist) & (df_dem['Mes'] < mes_actual)
    ].copy()

    titulo = 'Ventas Históricas vs Pronóstico' if tipo == 'ventas' else 'Demanda Histórica vs Pronóstico'
    ylabel = 'Ventas ($)' if tipo == 'ventas' else 'Unidades'

    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, titulo, 'Mes', ylabel)

    handles = []
    for i, prod in enumerate(nombres):
        col_hist = f'Ventas_{prod}' if tipo == 'ventas' else f'Demanda_{prod}'
        col_pron = f'Pronostico_Ventas_{prod}' if tipo == 'ventas' else f'Pronostico_Demanda_{prod}'
        color    = color_producto(i)

        # ── Serie histórica (puntos reales, línea continua) ──────────
        if col_hist in df_hist.columns:
            serie = df_hist.set_index('Mes')[col_hist].astype(float)
            if not serie.empty:
                ax.plot(serie.index, serie.values,
                        marker='o', markersize=5, linewidth=2.0,
                        color=color, label=prod)
                handles.append(mpatches.Patch(color=color, label=prod))

        # ── Serie pronóstico (línea discontinua SEPARADA, sin conectar) ─
        if not df_pron.empty and col_pron in df_pron.columns:
            df_pf = df_pron[df_pron['Mes'] >= mes_actual].head(meses)
            if not df_pf.empty:
                pron_serie = df_pf.set_index('Mes')[col_pron].astype(float)
                ax.plot(pron_serie.index, pron_serie.values,
                        '--', marker='o', markersize=4, linewidth=1.8,
                        color=FORECAST_COLOR, alpha=0.95)

    # Línea vertical separando histórico de pronóstico
    ax.axvline(x=mes_actual, color='#AAAAAA', linestyle=':', linewidth=1.5)

    if tipo == 'ventas':
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda v, _: f'${v:,.0f}'))

    pron_patch = mpatches.Patch(color=FORECAST_COLOR, label='Pronóstico')
    if handles:
        ax.legend(handles=handles + [pron_patch], fontsize=14, loc='upper left',
                  framealpha=0.8, ncol=min(len(handles) + 1, 4))

    # Etiquetas de eje X con abreviaturas, sin saltos
    todas_fechas = []
    if not df_hist.empty:
        todas_fechas += list(df_hist['Mes'])
    if not df_pron.empty:
        df_pf_all = df_pron[df_pron['Mes'] >= mes_actual].head(meses)
        if not df_pf_all.empty:
            todas_fechas += list(df_pf_all['Mes'])
    todas_fechas = sorted(set(todas_fechas))

    ax.set_xticks(todas_fechas)
    ax.set_xticklabels([format_mes_abrev(f) for f in todas_fechas],
                       rotation=40, ha='right', fontsize=13)
    fig.tight_layout(pad=1.0)
    return jsonify({'img': fig_to_base64(fig)})

@app.route('/api/grafico_pronostico_barras')
def api_grafico_pronostico_barras():
    producto     = request.args.get('producto', 'Todos')
    meses        = int(request.args.get('meses', 3))
    modo         = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_pron = cargar_pronosticos()
    df_dem  = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    if df_pron.empty:
        fig, ax = plt.subplots(figsize=(20, 6))
        ax.text(0.5, 0.5, 'Sin datos de pronóstico. Ejecute el cálculo.',
                ha='center', va='center')
        return jsonify({'img': fig_to_base64(fig)})

    if modo == 'prueba' and fecha_actual:
        mes_actual = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_actual = pd.Timestamp.now().normalize().replace(day=1)

    fechas_fut = pd.date_range(mes_actual, periods=meses, freq='MS')
    df_fut     = df_pron[df_pron['Mes'].isin(fechas_fut)]

    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, f'Pronóstico de Producción – Próximos {meses} meses', 'Mes', 'Unidades')

    n     = len(nombres)
    width = 0.7 / max(n, 1)
    x     = np.arange(len(fechas_fut))
    etiq  = [format_mes_abrev(f) for f in fechas_fut]

    for i, prod in enumerate(nombres):
        col = f'Pronostico_Demanda_{prod}'
        if col not in df_fut.columns:
            continue
        vals = [
            float(df_fut[df_fut['Mes'] == f][col].values[0])
            if not df_fut[df_fut['Mes'] == f].empty else 0
            for f in fechas_fut
        ]
        offset = (i - (n - 1) / 2) * width
        bars   = ax.bar(x + offset, vals, width=width * 0.9,
                        color=color_producto(i), label=prod,
                        alpha=0.88, edgecolor='white', linewidth=0.5)
        for bar, v in zip(bars, vals):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() / 2,
                        str(int(round(v))),
                        ha='center', va='center',
                        fontsize=20, fontweight='bold', color='white')

    ax.set_xticks(x)
    ax.set_xticklabels(etiq, fontsize=16)
    ax.legend(fontsize=14, framealpha=0.8)
    fig.tight_layout(pad=1.0)
    return jsonify({'img': fig_to_base64(fig)})

@app.route('/api/grafico_ventas_pronostico')
def api_grafico_ventas_pronostico():
    producto = request.args.get('producto', 'Todos')
    meses = int(request.args.get('meses', 6))
    modo = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_pron = cargar_pronosticos()
    df_dem = cargar_demanda()
    df_prod = cargar_productos()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    precios = {}
    for _, row in df_prod.iterrows():
        nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
        precios[nm] = float(row['Precio Unitario ($)'])

    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, f'Pronóstico de Ventas – Próximos {meses} meses', 'Mes', 'Ventas ($)')

    # Determinar fecha actual según modo
    if modo == 'prueba' and fecha_actual:
        hoy = pd.Timestamp(fecha_actual).normalize()
    else:
        hoy = pd.Timestamp.now().normalize()
    
    mes_actual = hoy.replace(day=1)
    # Histórico ventas últimos 12 meses
    fecha_inicio_hist = mes_actual - pd.DateOffset(months=12)
    df_hist = df_dem[df_dem['Mes'] >= fecha_inicio_hist].copy()

    for i, prod in enumerate(nombres):
        col_ven = f'Ventas_{prod}'
        color = color_producto(i)
        if col_ven in df_hist.columns:
            serie_ven = df_hist.set_index('Mes')[col_ven].astype(float)
            ax.plot(serie_ven.index, serie_ven.values, marker='o', markersize=3.5,
                    linewidth=1.6, color=color, label=prod)

        # Pronóstico ventas
        col_pron_ven = f'Pronostico_Ventas_{prod}'
        if not df_pron.empty and col_pron_ven in df_pron.columns:
            fechas_fut = pd.date_range(mes_actual, periods=meses, freq='MS')
            df_fut = df_pron[df_pron['Mes'].isin(fechas_fut)]
            if not df_fut.empty:
                pron_ven = df_fut.set_index('Mes')[col_pron_ven]
                ax.plot(pron_ven.index, pron_ven.values, '--',
                        linewidth=1.5, color=FORECAST_COLOR, alpha=0.85)

    ax.axvline(x=mes_actual, color='#AAAAAA', linestyle=':', linewidth=1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda x, _: f'${x:,.0f}'))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    # ax.set_xticklabels([format_fecha_espanol(date) for date in ax.get_xticks()])
    plt.xticks(rotation=30, ha='right', fontsize=14)
    ax.legend(fontsize=14, framealpha=0.8, ncol=min(len(nombres), 3))
    fig.tight_layout(pad=1.0)
    return jsonify({'img': fig_to_base64(fig)})

@app.route('/api/grafico_pap_resumen')
def api_grafico_pap_resumen():
    producto = request.args.get('producto', 'Todos')
    meses = int(request.args.get('meses', 3))
    modo = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    op = cargar_operarios()
    df_prod = cargar_productos()
    pap_dict = {}
    for prod in nombres:
        inv_ini = 25
        for _, row in df_prod.iterrows():
            nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nm == prod and 'Inventario' in row:
                inv_ini = int(row['Inventario'])
                break
        from calculos import calcular_pap_producto
        pap_dict[prod] = calcular_pap_producto(prod, df_dem, df_pron, op, inv_ini, meses)

    if not pap_dict:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, 'Sin datos', ha='center', va='center')
        return jsonify({'img': fig_to_base64(fig)})

    # Mostrar valores individuales solo cuando: 1 producto O (varios productos Y 3 meses)
    mostrar_vals_individuales = (len(pap_dict) == 1) or (len(pap_dict) > 1 and meses == 3)

    fig, axes = plt.subplots(1, 2, figsize=(28, 8))

    # ── Barras apiladas: costos ──────────────────────────────────────
    ax1 = axes[0]
    estilo_base(ax1, 'Costo Total por Mes', 'Mes', 'Costo ($)')
    all_fechas = sorted(set(
        f for df in pap_dict.values() for f in df['Mes'].tolist()
    ))
    etiq = [format_mes_abrev(f) for f in all_fechas]
    x = np.arange(len(all_fechas))
    bottom = np.zeros(len(all_fechas))

    acum_vals = {j: 0.0 for j in range(len(all_fechas))}

    for i, (prod, df) in enumerate(pap_dict.items()):
        vals = []
        for f in all_fechas:
            row = df[df['Mes'] == f]
            vals.append(float(row['Costo_total'].values[0]) if not row.empty else 0)
        ax1.bar(x, vals, bottom=bottom, color=color_producto(i),
                label=prod, alpha=0.88, edgecolor='white', linewidth=0.5)

        if mostrar_vals_individuales:
            for j, (bar_val, bar_bottom) in enumerate(zip(vals, bottom)):
                mid = bar_bottom + bar_val / 2
                if bar_val > 0:
                    ax1.text(j, mid, f'${int(bar_val):,}',
                             ha='center', va='center', fontsize=18,
                             fontweight='bold', color='white')

        for j, v in enumerate(vals):
            acum_vals[j] += v
        bottom = bottom + np.array(vals)

    # Totales siempre encima
    for j, total_val in acum_vals.items():
        if total_val > 0:
            ax1.text(j, total_val + max(acum_vals.values()) * 0.01,
                     f'${int(total_val):,}',
                     ha='center', va='bottom', fontsize=18,
                     fontweight='bold', color='#333333')

    ax1.set_xticks(x)
    ax1.set_xticklabels(etiq, fontsize=18, rotation=20, ha='right')
    ax1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f'${v:,.0f}'))
    ax1.legend(fontsize=16, framealpha=0.8)

    # ── Producción planificada vs demanda ────────────────────────────
    ax2 = axes[1]
    estilo_base(ax2, 'Producción Planificada vs Demanda', 'Mes', 'Unidades')
    n_prod = len(pap_dict)
    w = 0.6 / max(n_prod, 1)

    all_vals_flat = []
    for prod, df in pap_dict.items():
        for f in all_fechas:
            row = df[df['Mes'] == f]
            if not row.empty:
                all_vals_flat.append(int(row['Demanda'].values[0]))
                all_vals_flat.append(int(row['Unidades_producidas'].values[0]))
    max_val = max(all_vals_flat + [1])

    for i, (prod, df) in enumerate(pap_dict.items()):
        dem_vals = []
        prod_vals = []
        for f in all_fechas:
            row = df[df['Mes'] == f]
            dem_vals.append(int(row['Demanda'].values[0]) if not row.empty else 0)
            prod_vals.append(int(row['Unidades_producidas'].values[0]) if not row.empty else 0)
        off = (i - (n_prod - 1) / 2) * w
        bars = ax2.bar(x + off, prod_vals, w * 0.85, color=color_producto(i),
                       label=prod, alpha=0.85, edgecolor='white')

        if mostrar_vals_individuales:
            for bar, v in zip(bars, prod_vals):
                if v > 0:
                    ax2.text(bar.get_x() + bar.get_width() / 2,
                             bar.get_height() / 2,
                             str(v), ha='center', va='center',
                             fontsize=16, fontweight='bold', color='white')

        for j, (dv, bar) in enumerate(zip(dem_vals, bars)):
            cx = bar.get_x() + bar.get_width() / 2
            half = w * 0.85 / 2 * 1.3
            ax2.plot([cx - half, cx + half], [dv, dv],
                     color='#EE1111', linewidth=3, solid_capstyle='round', zorder=5)
            if mostrar_vals_individuales:
                ax2.text(cx, dv + max_val * 0.015, str(dv),
                         ha='center', va='bottom', fontsize=14,
                         fontweight='bold', color='#CC0000')

    ax2.set_xticks(x)
    ax2.set_xticklabels(etiq, fontsize=18, rotation=20, ha='right')
    ax2.set_ylim(0, max_val * 1.22)
    handles2, labels2 = ax2.get_legend_handles_labels()
    dem_line = matplotlib.lines.Line2D([0], [0], color='#EE1111', linewidth=3, label='Demanda')
    ax2.legend(handles=handles2 + [dem_line], fontsize=16, framealpha=0.8)

    fig.tight_layout(pad=1.5)
    return jsonify({'img': fig_to_base64(fig)})

# ─── API: TABLA PRONÓSTICO ───────────────────────────────────────────────────
@app.route('/api/tabla_pronostico')
def api_tabla_pronostico():
    producto = request.args.get('producto', 'Todos')
    meses    = int(request.args.get('meses', 6))
    tipo     = request.args.get('tipo', 'demanda')
    modo     = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_pron = cargar_pronosticos()
    df_dem  = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    if df_pron.empty:
        return jsonify({'columnas': [], 'filas': []})

    if modo == 'prueba' and fecha_actual:
        mes_actual = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_actual = pd.Timestamp.now().normalize().replace(day=1)

    fechas_fut = pd.date_range(mes_actual, periods=meses, freq='MS')
    df_fut = df_pron[df_pron['Mes'].isin(fechas_fut)].copy()

    filas = []
    for _, row in df_fut.iterrows():
        fila = {'Mes': format_mes_abrev(row['Mes'])}
        for prod in nombres:
            if tipo == 'ventas':
                col = f'Pronostico_Ventas_{prod}'
                if col in row:
                    fila[prod] = fmt_moneda(row[col])
            else:
                col = f'Pronostico_Demanda_{prod}'
                if col in row:
                    fila[prod] = fmt_num(row[col])
        filas.append(fila)

    return jsonify({'columnas': ['Mes'] + nombres, 'filas': filas})

# ─── API: TABLA PAP ──────────────────────────────────────────────────────────

@app.route('/api/tabla_pap')
def api_tabla_pap():
    producto = request.args.get('producto', 'Todos')
    meses = int(request.args.get('meses', 3))
    modo = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    df_prod = cargar_productos()
    op = cargar_operarios()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    from calculos import calcular_pap_producto
    filas = []
    for prod in nombres:
        inv_ini = 25
        precio_prod = 3.5
        for _, row in df_prod.iterrows():
            nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nm == prod and 'Inventario' in row:
                inv_ini = int(row['Inventario'])
                precio_prod = float(row.get('Precio Unitario ($)', 3.5))
                break
        df_pap = calcular_pap_producto(prod, df_dem, df_pron, op, inv_ini, meses, modo, fecha_actual)
        for _, r in df_pap.iterrows():
            filas.append({
                'Mes':                  r['Mes'].strftime('%b %Y'),
                'Costo Total':          fmt_moneda(r['Costo_total']),
                'Costo Mano de Obra':   fmt_moneda(r['Costo_mano_obra']),
                'Costo Almacén':        fmt_moneda(r['Costo_almacenamiento']),
                'Precio Producción':    fmt_moneda(precio_prod),
                'Demanda':              fmt_num(r['Demanda']),
                'Días':                 int(r['Dias']),
                'Unidades/Operario':    int(r['Unidades_por_operario']),
                'Operarios Requeridos': int(r['Operarios_requeridos']),
                'Operarios Actuales':   int(r['Operarios_actuales']),
                'Contratados':          int(r['Operarios_contratados']),
                'Despedidos':           int(r['Operarios_despedidos']),
                'Operarios Utilizados': int(r['Operarios_utilizados']),
                'Unidades Producidas':  fmt_num(r['Unidades_producidas']),
                'Unidades Disponibles': fmt_num(r['Unidades_disponibles']),
                'Inventario Final':     fmt_num(r['Inventario_final']),
                'Costo Contratar':      fmt_moneda(r['Costo_contratar']),
                'Costo Despedir':       fmt_moneda(r['Costo_despedir']),
            })

    cols = ['Mes', 'Costo Total', 'Costo Mano de Obra', 'Costo Almacén',
            'Precio Producción', 'Demanda', 'Días', 'Unidades/Operario',
            'Operarios Requeridos', 'Operarios Actuales', 'Contratados', 'Despedidos',
            'Operarios Utilizados', 'Unidades Producidas', 'Unidades Disponibles',
            'Inventario Final', 'Costo Contratar', 'Costo Despedir']
    return jsonify({'columnas': cols, 'filas': filas})

@app.route('/api/pap_resumen')
def api_pap_resumen():
    """Retorna datos resumen del PAP para los KPI cards."""
    producto = request.args.get('producto', 'Todos')
    meses = int(request.args.get('meses', 3))
    modo = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    df_prod = cargar_productos()
    op = cargar_operarios()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    from calculos import calcular_pap_producto
    resumen = {
        'precio_produccion': 0,
        'unidades_por_operario': 0,
        'operarios_requeridos_max': 0,
        'operarios_contratados_total': 0,
        'operarios_despedidos_total': 0,
        'unidades_producidas': 0,
        'unidades_disponibles': 0,
        'inventario_final': 0,
        'costo_contratar': 0,
        'costo_despedir': 0,
        'costo_mano_obra': 0,
        'costo_mantenimiento': 0,
        'costo_total': 0,
    }
    
    total_unidades = 0
    total_operarios = 0
    
    for prod in nombres:
        inv_ini = 25
        precio_prod = 3.5
        for _, row in df_prod.iterrows():
            nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nm == prod:
                inv_ini = int(row.get('Inventario', 25))
                precio_prod = float(row.get('Precio Unitario ($)', 3.5))
                break
        
        df_pap = calcular_pap_producto(prod, df_dem, df_pron, op, inv_ini, meses, modo, fecha_actual)
        
        if producto != 'Todos':
            resumen['precio_produccion'] = precio_prod
        
        total_unidades += int(df_pap['Unidades_producidas'].sum())
        total_operarios += int(df_pap['Operarios_utilizados'].sum())
        
        resumen['operarios_requeridos_max'] = max(resumen['operarios_requeridos_max'], int(df_pap['Operarios_requeridos'].max()))
        resumen['operarios_contratados_total'] += int(df_pap['Operarios_contratados'].sum())
        resumen['operarios_despedidos_total'] += int(df_pap['Operarios_despedidos'].sum())
        resumen['unidades_producidas'] += int(df_pap['Unidades_producidas'].sum())
        resumen['unidades_disponibles'] += int(df_pap['Unidades_disponibles'].sum())
        resumen['inventario_final'] += int(df_pap['Inventario_final'].iloc[-1])
        resumen['costo_contratar'] += round(df_pap['Costo_contratar'].sum(), 2)
        resumen['costo_despedir'] += round(df_pap['Costo_despedir'].sum(), 2)
        resumen['costo_mano_obra'] += round(df_pap['Costo_mano_obra'].sum(), 2)
        resumen['costo_mantenimiento'] += round(df_pap['Costo_almacenamiento'].sum(), 2)
        resumen['costo_total'] += round(df_pap['Costo_total'].sum(), 2)
    
    if producto == 'Todos':
        resumen['precio_produccion'] = sum([float(row['Precio Unitario ($)']) for _, row in df_prod.iterrows()]) / len(df_prod) if len(df_prod) > 0 else 3.5
    
    resumen['unidades_por_operario'] = round(total_unidades / total_operarios, 2) if total_operarios > 0 else 0
    
    return jsonify(resumen)

@app.route('/api/pap_dashboard_tablas')
def api_pap_dashboard_tablas():
    meses = int(request.args.get('meses', 3))
    modo = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    df_prod = cargar_productos()
    op = cargar_operarios()
    nombres = obtener_nombres_productos(df_dem)

    from calculos import calcular_pap_producto
    tablas_por_producto = {}
    costo_total_horizonte = 0

    for prod in nombres:
        inv_ini = 25
        precio_prod = 3.5
        for _, row in df_prod.iterrows():
            nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nm == prod:
                inv_ini = int(row.get('Inventario', 25))
                precio_prod = float(row.get('Precio Unitario ($)', 3.5))
                break

        df_pap = calcular_pap_producto(prod, df_dem, df_pron, op, inv_ini, meses, modo, fecha_actual)
        df_pap['Precio_Produccion'] = precio_prod
        costo_prod = df_pap['Costo_total'].sum()
        costo_total_horizonte += costo_prod

        filas = []
        for _, r in df_pap.iterrows():
            filas.append({
                'Mes':                  r['Mes'].strftime('%b %Y'),
                'Costo Total':          fmt_moneda(r['Costo_total']),
                'Costo Mano de Obra':   fmt_moneda(r['Costo_mano_obra']),
                'Costo Almacén':        fmt_moneda(r['Costo_almacenamiento']),
                'Precio Producción':    fmt_moneda(precio_prod),
                'Demanda':              fmt_num(r['Demanda']),
                'Días':                 int(r['Dias']),
                'Unidades/Operario':    int(r['Unidades_por_operario']),
                'Operarios Requeridos': int(r['Operarios_requeridos']),
                'Operarios Actuales':   int(r['Operarios_actuales']),
                'Contratados':          int(r['Operarios_contratados']),
                'Despedidos':           int(r['Operarios_despedidos']),
                'Operarios Utilizados': int(r['Operarios_utilizados']),
                'Unidades Producidas':  fmt_num(r['Unidades_producidas']),
                'Unidades Disponibles': fmt_num(r['Unidades_disponibles']),
                'Inventario Final':     fmt_num(r['Inventario_final']),
                'Costo Contratar':      fmt_moneda(r['Costo_contratar']),
                'Costo Despedir':       fmt_moneda(r['Costo_despedir']),
            })

        cols = ['Mes', 'Costo Total', 'Costo Mano de Obra', 'Costo Almacén',
                'Precio Producción', 'Demanda', 'Días', 'Unidades/Operario',
                'Operarios Requeridos', 'Operarios Actuales', 'Contratados', 'Despedidos',
                'Operarios Utilizados', 'Unidades Producidas', 'Unidades Disponibles',
                'Inventario Final', 'Costo Contratar', 'Costo Despedir']

        tablas_por_producto[prod] = {
            'columnas': cols,
            'filas': filas,
            'costo_prod': fmt_moneda(costo_prod),
            'costo_total': fmt_moneda(costo_prod),
        }

    return jsonify({
        'tablas': tablas_por_producto,
        'costo_total_horizonte': fmt_moneda(costo_total_horizonte)
    })

# ─── API: TABLA DEMANDA ──────────────────────────────────────────────────────

@app.route('/api/tabla_demanda')
def api_tabla_demanda():
    producto     = request.args.get('producto', 'Todos')
    modo         = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_dem  = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    if modo == 'prueba' and fecha_actual:
        mes_corte = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_corte = pd.Timestamp.now().normalize().replace(day=1)

    # Solo mostrar hasta el mes anterior al mes actual del modo
    df_filtrado = df_dem[df_dem['Mes'] < mes_corte].copy()

    filas = []
    for _, row in df_filtrado.iterrows():
        fecha = pd.Timestamp(row['Mes'])
        fila = {'Mes': format_mes_abrev(fecha)}
        for prod in nombres:
            col = f'Demanda_{prod}'
            fila[prod] = fmt_num(row[col]) if col in row else '0'
        filas.append(fila)

    return jsonify({'columnas': ['Mes'] + nombres, 'filas': list(reversed(filas))})

@app.route('/api/grafico_demanda_barras')
def api_grafico_demanda_barras():
    producto     = request.args.get('producto', 'Todos')
    modo         = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_dem  = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    if modo == 'prueba' and fecha_actual:
        mes_corte = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_corte = pd.Timestamp.now().normalize().replace(day=1)

    fecha_inicio = mes_corte - pd.DateOffset(months=18)
    rango_meses  = pd.date_range(fecha_inicio, periods=18, freq='MS')
    df_rango     = pd.DataFrame({'Mes': rango_meses})
    df_hist      = pd.merge(df_rango,
                            df_dem[df_dem['Mes'] < mes_corte],
                            on='Mes', how='left').fillna(0)
    df_hist['Mes'] = pd.to_datetime(df_hist['Mes'])

    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, 'Histórico de Demanda por Producto', 'Mes', 'Unidades')

    x    = np.arange(len(df_hist))
    etiq = [format_mes_abrev(pd.Timestamp(m)) for m in df_hist['Mes']]
    n    = len(nombres)
    w    = 0.7 / max(n, 1)

    for i, prod in enumerate(nombres):
        col = f'Demanda_{prod}'
        if col not in df_hist.columns:
            continue
        vals = df_hist[col].fillna(0).values
        off  = (i - (n - 1) / 2) * w
        ax.bar(x + off, vals, w * 0.9, color=color_producto(i),
               label=prod, alpha=0.88, edgecolor='white', linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(etiq, fontsize=14, rotation=40, ha='right')
    ax.legend(fontsize=16, framealpha=0.8)
    fig.tight_layout(pad=1.0)
    return jsonify({'img': fig_to_base64(fig)})


# ─── API: TABLA VENTAS ───────────────────────────────────────────────────────

@app.route('/api/tabla_ventas')
def api_tabla_ventas():
    producto     = request.args.get('producto', 'Todos')
    modo         = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_dem  = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    if modo == 'prueba' and fecha_actual:
        mes_corte = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_corte = pd.Timestamp.now().normalize().replace(day=1)

    df_filtrado = df_dem[df_dem['Mes'] < mes_corte].copy()

    filas = []
    for _, row in df_filtrado.iterrows():
        fecha = pd.Timestamp(row['Mes'])
        fila = {'Mes': format_mes_abrev(fecha)}
        for prod in nombres:
            col = f'Ventas_{prod}'
            fila[prod] = fmt_moneda(row[col]) if col in row else '$0.00'
        filas.append(fila)

    return jsonify({'columnas': ['Mes'] + nombres, 'filas': list(reversed(filas))})

@app.route('/api/grafico_ventas_historico')
def api_grafico_ventas_historico():
    producto     = request.args.get('producto', 'Todos')
    modo         = request.args.get('modo', 'produccion')
    fecha_actual = request.args.get('fecha_actual')

    df_dem  = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != 'Todos':
        nombres = [p for p in nombres if p == producto]

    if modo == 'prueba' and fecha_actual:
        mes_corte = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_corte = pd.Timestamp.now().normalize().replace(day=1)

    fecha_inicio = mes_corte - pd.DateOffset(months=18)
    rango_meses  = pd.date_range(fecha_inicio, periods=18, freq='MS')
    df_rango     = pd.DataFrame({'Mes': rango_meses})
    df_hist      = pd.merge(df_rango,
                            df_dem[df_dem['Mes'] < mes_corte],
                            on='Mes', how='left').fillna(0)
    df_hist['Mes'] = pd.to_datetime(df_hist['Mes'])

    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, 'Histórico de Ventas por Producto', 'Mes', 'Ventas ($)')

    x    = np.arange(len(df_hist))
    etiq = [format_mes_abrev(pd.Timestamp(m)) for m in df_hist['Mes']]
    n    = len(nombres)
    w    = 0.7 / max(n, 1)

    for i, prod in enumerate(nombres):
        col = f'Ventas_{prod}'
        if col not in df_hist.columns:
            continue
        vals = df_hist[col].fillna(0).values
        off  = (i - (n - 1) / 2) * w
        ax.bar(x + off, vals, w * 0.9, color=color_producto(i),
               label=prod, alpha=0.88, edgecolor='white', linewidth=0.5)

    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f'${v:,.0f}'))
    ax.set_xticks(x)
    ax.set_xticklabels(etiq, fontsize=14, rotation=40, ha='right')
    ax.legend(fontsize=16, framealpha=0.8)
    fig.tight_layout(pad=1.0)
    return jsonify({'img': fig_to_base64(fig)})

# ─── API: ACCIONES ───────────────────────────────────────────────────────────

@app.route('/api/recalcular_pronostico', methods=['POST'])
def api_recalcular_pronostico():
    try:
        data = request.json or {}
        n_meses = int(data.get('meses', 12))
        modo = data.get('modo', 'produccion')
        fecha_actual = data.get('fecha_actual')
        
        # Guardar estado del cálculo
        from calculos import guardar_estado_calculo, calcular_hash_valores_demanda
        df_dem = cargar_demanda()
        
        # Determinar fecha actual según modo
        if modo == 'prueba' and fecha_actual:
            fecha_calc = fecha_actual
        else:
            hoy = pd.Timestamp.now().normalize()
            fecha_calc = hoy.strftime('%Y-%m-%d')
        
        hash_valores = calcular_hash_valores_demanda(df_dem, fecha_calc)
        guardar_estado_calculo(modo, fecha_calc, hash_valores)
        
        df_pron = ejecutar_pronostico_completo(n_meses, modo, fecha_actual)
        return jsonify({'ok': True, 'meses': n_meses, 'filas': len(df_pron)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/actualizar_demanda', methods=['POST'])
def api_actualizar_demanda():
    try:
        data = request.json
        mes_str = data.get('mes')  # YYYY-MM-DD
        prod = data.get('producto')
        valor = float(data.get('valor', 0))

        df_dem = cargar_demanda()
        df_prod = cargar_productos()
        mes = pd.Timestamp(mes_str)
        col_dem = f'Demanda_{prod}'
        col_ven = f'Ventas_{prod}'

        if col_dem not in df_dem.columns:
            return jsonify({'ok': False, 'error': f'Producto no encontrado: {prod}'}), 400

        # Obtener precio automáticamente de la base de datos
        ventas_precio = 3.5  # default
        for _, row in df_prod.iterrows():
            nombre_completo = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nombre_completo == prod:
                ventas_precio = float(row['Precio Unitario ($)'])
                break

        mask = df_dem['Mes'] == mes
        if mask.any():
            df_dem.loc[mask, col_dem] = valor
            df_dem.loc[mask, col_ven] = valor * ventas_precio
        else:
            nueva_fila = {'Mes': mes}
            for c in df_dem.columns:
                if c != 'Mes':
                    nueva_fila[c] = 0
            nueva_fila[col_dem] = valor
            nueva_fila[col_ven] = valor * ventas_precio
            df_dem = pd.concat([df_dem, pd.DataFrame([nueva_fila])], ignore_index=True)
            df_dem = df_dem.sort_values('Mes').reset_index(drop=True)

        guardar_demanda(df_dem)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/agregar_producto', methods=['POST'])
def api_agregar_producto():
    try:
        data = request.json
        nombre = data.get('nombre', '').strip()
        tamano = int(data.get('tamano', 170))
        precio = float(data.get('precio', 3.5))
        inventario = int(data.get('inventario', 0))
        prod_por_op = int(data.get('prod_por_op', 3))
        lote = int(data.get('lote', 100))

        df_prod = cargar_productos()
        nombre_completo = f"{nombre} {tamano} g"

        nueva_fila = {
            'Nombre': nombre,
            'Tamaño (g)': tamano,
            'Descripción': nombre_completo,
            'Precio Unitario ($)': precio,
            'Lote': lote,
            'Inventario': inventario,
            'Produccion promedio (por operario)': prod_por_op,
        }
        # Rellenar insumos con 0
        for col in df_prod.columns:
            if col not in nueva_fila:
                nueva_fila[col] = 0

        df_prod = pd.concat([df_prod, pd.DataFrame([nueva_fila])], ignore_index=True)
        guardar_productos(df_prod)

        # Agregar columnas en demanda
        df_dem = cargar_demanda()
        col_dem = f'Demanda_{nombre_completo}'
        col_ven = f'Ventas_{nombre_completo}'
        if col_dem not in df_dem.columns:
            df_dem[col_dem] = 0
            df_dem[col_ven] = 0
            guardar_demanda(df_dem)

        return jsonify({'ok': True, 'nombre': nombre_completo})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/actualizar_operarios', methods=['POST'])
def api_actualizar_operarios():
    try:
        data = request.json
        op = cargar_operarios()
        for k in ['operarios', 'costo_contratar', 'costo_despedir',
                  'costo_almacenamiento', 'costo_hora_extra',
                  'costo_hora_normal', 'jornada_normal']:
            if k in data:
                op[k] = float(data[k])
        guardar_operarios(op)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/meses_disponibles')
def api_meses_disponibles():
    df_dem = cargar_demanda()
    meses = [pd.Timestamp(m).strftime('%Y-%m-%d') for m in df_dem['Mes']]
    return jsonify(meses)


if __name__ == '__main__':
    # Inicializar pronóstico si no existe
    import os as _os
    if not _os.path.exists(_os.path.join('data', 'pronosticos.csv')):
        print("Calculando pronóstico inicial...")
        ejecutar_pronostico_completo(12)

    app.run(debug=False, host='0.0.0.0', port=5050)
