"""
app.py - Servidor Flask principal para ASOPRIABET Aromas del Yasuní.
Sistema de Planificación y Control de la Producción.
"""

import base64
import calendar
import io
import json
import math
import os
from datetime import date, datetime
from functools import lru_cache
import hashlib as _hashlib

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import locale

import matplotlib.dates as mdates
import matplotlib.lines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from flask import Flask, jsonify, render_template, request, send_from_directory
from matplotlib.gridspec import GridSpec

from calculos import (
    calcular_pap_todos,
    cargar_demanda,
    cargar_estado_calculo,
    cargar_operarios,
    cargar_productos,
    cargar_pronosticos,
    cargar_sesion,
    ejecutar_pronostico_completo,
    guardar_demanda,
    guardar_estado_calculo,
    guardar_operarios,
    guardar_productos,
    guardar_pronosticos,
    guardar_sesion,
    necesita_recalculo,
    obtener_nombres_productos,
    resumen_pap,
    verificar_ceros_demanda_todos,
    verificar_login,
)

app = Flask(__name__)

# ─── CACHE DE GRÁFICOS ───────────────────────────────────────────────────────

_graph_cache = {}  # {cache_key: img_b64}

def _cache_key(*args):
    """Genera clave de cache a partir de argumentos."""
    raw = json.dumps(args, sort_keys=True, default=str)
    return _hashlib.md5(raw.encode()).hexdigest()

def _get_cache(key):
    return _graph_cache.get(key)

def _set_cache(key, value):
    _graph_cache[key] = value

def _fmt_miles(val):
    """Formatea valor en miles: $5,450 → $5.5k"""
    if val >= 1000:
        return f"${val/1000:.1f}k"
    return f"${int(round(val))}"

# ─── PALETA DE COLORES POR PRODUCTO ───────────────────────────────────────────
PRODUCT_COLORS = [
    "#7B3F00",  # chocolate oscuro
    "#C17817",  # dorado cacao
    "#2D6A2D",  # verde yasuní
    "#D4501A",  # naranja tierra
    "#5C3317",  # café oscuro
    "#8B6914",  # ámbar
    "#1A5C3A",  # verde selva
    "#B84A1A",  # terracota
    "#4A2C6E",  # violeta
    "#1A4A6E",  # azul petróleo
]
FORECAST_COLOR = "#E8A020"  # ámbar pronóstico (no coincide con ningún producto)
ACCENT_COLOR = "#7B3F00"  # chocolate principal


def color_producto(idx):
    return PRODUCT_COLORS[idx % len(PRODUCT_COLORS)]


def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=130,
        bbox_inches="tight",
        facecolor="white",
        edgecolor="none",
    )
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode("utf-8")
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


def calcular_limite_superior_escala(max_val):
    if max_val <= 0:
        return 1
    magnitud = 10 ** int(np.floor(np.log10(max_val)))
    return int(np.ceil(max_val / magnitud) * magnitud)

# ─── HELPERS GRÁFICOS ────────────────────────────────────────────────────────

# Configurar locale español para nombres de meses
try:
    locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")
except:
    try:
        locale.setlocale(locale.LC_TIME, "Spanish_Spain.1252")
    except:
        # Fallback: usar configuración por defecto del sistema
        pass


def estilo_base(ax, title="", xlabel="", ylabel=""):
    ax.set_facecolor("#FAFAF8")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CCCCCC")
    ax.spines["bottom"].set_color("#CCCCCC")
    ax.tick_params(colors="#555555", labelsize=20)  # Doubled from 10
    ax.grid(axis="y", color="#EEEEEE", linewidth=0.7)
    if title:
        ax.set_title(
            title, fontsize=24, fontweight="bold", color="#3A2000", pad=8
        )  # Doubled from 12
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=20, color="#555555")  # Doubled from 10
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=20, color="#555555")  # Doubled from 10


def format_fecha_espanol(fecha):
    """Formatea fecha en español."""
    meses_es = [
        "Enero",
        "Febrero",
        "Marzo",
        "Abril",
        "Mayo",
        "Junio",
        "Julio",
        "Agosto",
        "Septiembre",
        "Octubre",
        "Noviembre",
        "Diciembre",
    ]
    return f"{meses_es[fecha.month - 1]} {fecha.year}"


MESES_ABREV = [
    "Ene.",
    "Feb.",
    "Mar.",
    "Abr.",
    "May.",
    "Jun.",
    "Jul.",
    "Ago.",
    "Sep.",
    "Oct.",
    "Nov.",
    "Dic.",
]


def format_mes_abrev(fecha):
    """Formatea fecha como 'Ene. 2026'."""
    return f"{MESES_ABREV[fecha.month - 1]} {fecha.year}"


# ─── RUTAS PRINCIPALES ───────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


# ─── API: DATOS GENERALES ────────────────────────────────────────────────────


@app.route("/api/productos")
def api_productos():
    df = cargar_productos()
    return jsonify(df.to_dict(orient="records"))


@app.route("/api/nombres_productos")
def api_nombres_productos():
    df_dem = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)
    return jsonify(nombres)


@app.route("/api/operarios")
def api_operarios():
    return jsonify(cargar_operarios())


# ─── API: LOGIN & SESIÓN ────────────────────────────────────────────────────────


@app.route("/api/login", methods=["POST"])
def api_login():
    """Verifica login para modificación de valores."""
    data = request.json
    password = data.get("password", "")

    if verificar_login(password):
        sesion = {"autenticado": True, "timestamp": datetime.now().isoformat()}
        guardar_sesion(sesion)
        return jsonify({"success": True, "message": "Login exitoso"})
    else:
        return jsonify({"success": False, "message": "Contraseña incorrecta"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """Cierra sesión."""
    try:
        import os

        from calculos import SESSION_DIR

        session_file = os.path.join(SESSION_DIR, "session.json")
        if os.path.exists(session_file):
            os.remove(session_file)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/sesion")
def api_sesion():
    """Verifica estado de sesión."""
    sesion = cargar_sesion()
    if sesion and sesion.get("autenticado"):
        return jsonify({"autenticado": True})
    return jsonify({"autenticado": False})


# ─── API: MODO Y FECHA ───────────────────────────────────────────────────────────


@app.route("/api/set_modo", methods=["POST"])
def api_set_modo():
    """Establece modo de operación (prueba/producción)."""
    data = request.json
    modo = data.get("modo", "produccion")
    fecha_actual = data.get("fecha_actual")  # formato YYYY-MM-DD para modo prueba

    sesion = cargar_sesion() or {}
    sesion["modo"] = modo
    sesion["fecha_actual"] = fecha_actual
    guardar_sesion(sesion)

    return jsonify({"success": True, "modo": modo, "fecha_actual": fecha_actual})


@app.route("/api/get_modo")
def api_get_modo():
    """Obtiene modo actual y fecha."""
    sesion = cargar_sesion()
    modo = sesion.get("modo", "produccion") if sesion else "produccion"
    fecha_actual = sesion.get("fecha_actual") if sesion else None

    return jsonify({"modo": modo, "fecha_actual": fecha_actual})


# ─── API: VERIFICACIÓN DE CEROS Y CÁLCULOS ────────────────────────────────────────


@app.route("/api/verificar_ceros")
def api_verificar_ceros():
    """Verifica si hay demandas = 0 después del periodo 1."""
    fecha_actual = request.args.get("fecha_actual")
    if not fecha_actual:
        hoy = pd.Timestamp.now().normalize()
        fecha_actual = hoy.strftime("%Y-%m-%d")

    df_dem = cargar_demanda()
    ceros = verificar_ceros_demanda_todos(df_dem, fecha_actual)

    return jsonify({"tiene_ceros": len(ceros) > 0, "ceros_por_producto": ceros})


@app.route("/api/necesita_recalculo")
def api_necesita_recalculo():
    """Verifica si es necesario recalcular."""
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    if not fecha_actual:
        hoy = pd.Timestamp.now().normalize()
        fecha_actual = hoy.strftime("%Y-%m-%d")

    necesita, razon = necesita_recalculo(modo, fecha_actual)

    return jsonify({"necesita": necesita, "razon": razon})


# ─── API: DATOS GENERALES ────────────────────────────────────────────────────


# ─── API: DASHBOARD ──────────────────────────────────────────────────────────


@app.route("/api/dashboard_kpis")
def api_dashboard_kpis():
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")
    meses = int(request.args.get("meses", 3))

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    nombres = obtener_nombres_productos(df_dem)
    op = cargar_operarios()

    if modo == "prueba" and fecha_actual:
        hoy = pd.Timestamp(fecha_actual).normalize()
    else:
        hoy = pd.Timestamp.now().normalize()
    mes_actual = hoy.replace(day=1)

    # Pronóstico próximos N meses desde mes actual del modo
    dem_pronosticada = 0
    if not df_pron.empty:
        fechas_fut = pd.date_range(mes_actual, periods=meses, freq="MS")
        for prod in nombres:
            col = f"Pronostico_Demanda_{prod}"
            if col in df_pron.columns:
                filas = df_pron[df_pron["Mes"].isin(fechas_fut)]
                dem_pronosticada += int(filas[col].sum())

    # Inventario total actual
    df_prod = cargar_productos()
    inv_total = (
        int(df_prod["Inventario"].sum()) if "Inventario" in df_prod.columns else 0
    )

    # MAPE — usar merge en lugar de join
    mape_vals = []
    if not df_pron.empty:
        for prod in nombres:
            col_real = f"Demanda_{prod}"
            col_pron = f"Pronostico_Demanda_{prod}"
            if col_real in df_dem.columns and col_pron in df_pron.columns:
                df_r = df_dem[["Mes", col_real]].copy()
                df_p = df_pron[["Mes", col_pron]].copy()
                merged = pd.merge(df_r, df_p, on="Mes", how="inner").dropna()
                merged = merged[merged[col_real] > 0]
                if len(merged) > 0:
                    mape = float(
                        (
                            abs(merged[col_real] - merged[col_pron]) / merged[col_real]
                        ).mean()
                        * 100
                    )
                    mape_vals.append(mape)
    mape_global = round(float(np.mean(mape_vals)), 2) if mape_vals else 0

    return jsonify(
        {
            "dem_pronosticada": fmt_num(dem_pronosticada),
            "inv_total": fmt_num(inv_total),
            "operarios": int(op["operarios"]),
            "mape": f"{mape_global:.2f}%",
            "n_productos": len(nombres),
        }
    )


@app.route("/api/dashboard_kpis_producto")
def api_dashboard_kpis_producto():
    producto = request.args.get("producto", "Todos")
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")
    meses = int(request.args.get("meses", 3))

    if producto == "Todos":
        return api_dashboard_kpis()

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    df_prod = cargar_productos()

    if modo == "prueba" and fecha_actual:
        hoy = pd.Timestamp(fecha_actual).normalize()
    else:
        hoy = pd.Timestamp.now().normalize()
    mes_actual = hoy.replace(day=1)

    col_dem = f"Demanda_{producto}"
    col_pron = f"Pronostico_Demanda_{producto}"

    dem_pronosticada = 0
    if not df_pron.empty and col_pron in df_pron.columns:
        fechas_fut = pd.date_range(mes_actual, periods=meses, freq="MS")
        filas = df_pron[df_pron["Mes"].isin(fechas_fut)]
        dem_pronosticada = int(filas[col_pron].sum())

    inv_producto = 0
    precio_producto = 3.5
    for _, row in df_prod.iterrows():
        nombre_completo = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
        if nombre_completo == producto:
            inv_producto = int(row.get("Inventario", 0))
            precio_producto = float(row.get("Precio Unitario ($)", 3.5))
            break

    mape_producto = 0
    if not df_pron.empty and col_dem in df_dem.columns and col_pron in df_pron.columns:
        df_r = df_dem[["Mes", col_dem]].copy()
        df_p = df_pron[["Mes", col_pron]].copy()
        merged = pd.merge(df_r, df_p, on="Mes", how="inner").dropna()
        merged = merged[merged[col_dem] > 0]
        if len(merged) > 0:
            mape_producto = float(
                (abs(merged[col_dem] - merged[col_pron]) / merged[col_dem]).mean() * 100
            )

    return jsonify(
        {
            "dem_pronosticada": fmt_num(dem_pronosticada),
            "inv_total": fmt_num(inv_producto),
            "operarios": int(cargar_operarios()["operarios"]),
            "mape": f"{mape_producto:.2f}%",
            "n_productos": 1,
            "precio_producto": fmt_moneda(precio_producto),
        }
    )


# ─── API: GRÁFICOS DASHBOARD ─────────────────────────────────────────────────

@app.route("/api/grafico_demanda_historica")
def api_grafico_demanda_historica():
    producto = request.args.get("producto", "Todos")
    meses = int(request.args.get("meses", 12))
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")
    tipo = request.args.get("tipo", "demanda")

    ck = _cache_key("grafico_demanda_historica", producto, meses, modo, fecha_actual, tipo)
    cached = _get_cache(ck)
    if cached:
        return jsonify({"img": cached})

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    if modo == "prueba" and fecha_actual:
        mes_actual = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_actual = pd.Timestamp.now().normalize().replace(day=1)

    fecha_inicio_hist = mes_actual - pd.DateOffset(months=12)
    df_hist = df_dem[
        (df_dem["Mes"] >= fecha_inicio_hist) & (df_dem["Mes"] <= mes_actual)
    ].copy()

    titulo = (
        "Ventas Históricas vs Pronóstico"
        if tipo == "ventas"
        else "Demanda Histórica vs Pronóstico"
    )
    ylabel = "Ventas ($)" if tipo == "ventas" else "Unidades"

    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, titulo, "Mes", ylabel)

    handles = []
    all_vals = []

    for i, prod in enumerate(nombres):
        col_hist = f"Ventas_{prod}" if tipo == "ventas" else f"Demanda_{prod}"
        col_pron = (
            f"Pronostico_Ventas_{prod}"
            if tipo == "ventas"
            else f"Pronostico_Demanda_{prod}"
        )
        color = color_producto(i)

        if col_hist in df_hist.columns:
            serie = df_hist.set_index("Mes")[col_hist].astype(float)
            if not serie.empty:
                ax.plot(
                    serie.index,
                    serie.values,
                    marker="o",
                    markersize=7.5,
                    linewidth=2.0,
                    color=color,
                    label=prod,
                )
                handles.append(mpatches.Patch(color=color, label=prod))
                all_vals.extend(serie.values.tolist())

        if not df_pron.empty and col_pron in df_pron.columns:
            df_pf = df_pron[df_pron["Mes"] >= mes_actual].head(meses)
            if not df_pf.empty:
                pron_serie = df_pf.set_index("Mes")[col_pron].astype(float)
                ax.plot(
                    pron_serie.index,
                    pron_serie.values,
                    "--",
                    marker="o",
                    markersize=6,
                    linewidth=1.8,
                    color=color,
                    alpha=0.95,
                )
                all_vals.extend(pron_serie.values.tolist())

    ax.axvline(x=mes_actual, color="#AAAAAA", linestyle=":", linewidth=1.5)

    # Tolerancia: 1 escalón adicional al valor máximo
    max_val = max(all_vals) if all_vals else 0
    if max_val > 0:
        magnitud = 10 ** int(np.floor(np.log10(max_val)))
        escalon = magnitud if magnitud >= 100 else 100
        y_max = int(np.ceil(max_val / escalon) * escalon) + escalon
        ax.set_ylim(0, y_max)

    if tipo == "ventas":
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
        )

    if handles:
        ax.legend(
            handles=handles,
            fontsize=14,
            loc="upper left",
            framealpha=0.8,
            ncol=1,  # series una sobre otra
        )

    todas_fechas = []
    if not df_hist.empty:
        todas_fechas += list(df_hist["Mes"])
    if not df_pron.empty:
        df_pf_all = df_pron[df_pron["Mes"] >= mes_actual].head(meses)
        if not df_pf_all.empty:
            todas_fechas += list(df_pf_all["Mes"])
    todas_fechas = sorted(set(todas_fechas))

    ax.set_xticks(todas_fechas)
    ax.set_xticklabels(
        [format_mes_abrev(f) for f in todas_fechas],
        rotation=20,
        ha="right",
        fontsize=13,
    )
    fig.tight_layout(pad=1.0)
    img = fig_to_base64(fig)
    _set_cache(ck, img)
    return jsonify({"img": img})

@app.route("/api/grafico_pronostico_barras")
def api_grafico_pronostico_barras():
    producto = request.args.get("producto", "Todos")
    meses = int(request.args.get("meses", 3))
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")
    tipo = request.args.get("tipo", "demanda")

    ck = _cache_key("grafico_pronostico_barras", producto, meses, modo, fecha_actual, tipo)
    cached = _get_cache(ck)
    if cached:
        return jsonify({"img": cached})

    df_pron = cargar_pronosticos()
    df_dem = cargar_demanda()
    df_prod = cargar_productos()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    if df_pron.empty:
        fig, ax = plt.subplots(figsize=(20, 6))
        ax.text(
            0.5, 0.5,
            "Sin datos de pronóstico. Ejecute el cálculo.",
            ha="center", va="center",
        )
        return jsonify({"img": fig_to_base64(fig)})

    if modo == "prueba" and fecha_actual:
        mes_actual = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_actual = pd.Timestamp.now().normalize().replace(day=1)

    precios = {}
    for _, row in df_prod.iterrows():
        nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
        precios[nm] = float(row.get("Precio Unitario ($)", 0))

    fechas_fut = pd.date_range(mes_actual, periods=meses, freq="MS")
    df_fut = df_pron[df_pron["Mes"].isin(fechas_fut)]

    ylabel = "Ventas ($)" if tipo == "ventas" else "Unidades"
    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, "", "Mes", ylabel)

    x = np.arange(len(fechas_fut))
    etiq = [format_mes_abrev(f) for f in fechas_fut]

    bottoms = np.zeros(len(fechas_fut))
    # vals_por_prod[prod] = lista de valores por fecha
    vals_por_prod = {}

    for i, prod in enumerate(nombres):
        if tipo == "ventas":
            col_ventas = f"Pronostico_Ventas_{prod}"
            col_demanda = f"Pronostico_Demanda_{prod}"
            vals = []
            for f in fechas_fut:
                fila = df_fut[df_fut["Mes"] == f]
                if fila.empty:
                    vals.append(0)
                    continue
                if col_ventas in fila.columns:
                    vals.append(float(fila[col_ventas].values[0]))
                elif col_demanda in fila.columns:
                    vals.append(float(fila[col_demanda].values[0]) * precios.get(prod, 0))
                else:
                    vals.append(0)
        else:
            col = f"Pronostico_Demanda_{prod}"
            if col not in df_fut.columns:
                continue
            vals = [
                float(df_fut[df_fut["Mes"] == f][col].values[0])
                if not df_fut[df_fut["Mes"] == f].empty
                else 0
                for f in fechas_fut
            ]

        vals_por_prod[prod] = vals
        bars = ax.bar(
            x,
            vals,
            bottom=bottoms,
            width=0.7,
            color=color_producto(i),
            label=prod,
            alpha=0.88,
            edgecolor="white",
            linewidth=0.5,
        )
        # Valores dentro de las barras solo si Todos + (3 o 6 meses)
        mostrar_dentro = (producto == "Todos") and (meses in [3, 6])
        if mostrar_dentro:
            for j, (bar_val, bar_bottom) in enumerate(zip(vals, bottoms)):
                if bar_val > 0:
                    mid = bar_bottom + bar_val / 2
                    if tipo == "ventas":
                        label_in = _fmt_miles(bar_val)
                    else:
                        label_in = str(int(round(bar_val)))
                    ax.text(
                        j, mid, label_in,
                        ha="center", va="center",
                        fontsize=18, fontweight="bold", color="white",
                    )

        bottoms += np.array(vals)

    # Totales sobre las barras — siempre con formato $X.Xk para ventas
    for bar_idx, total in enumerate(bottoms):
        if total > 0:
            if tipo == "ventas":
                label_top = _fmt_miles(total)
            else:
                label_top = str(int(round(total)))
            ax.text(
                x[bar_idx],
                total + (max(bottoms) * 0.02),
                label_top,
                ha="center", va="bottom",
                fontsize=20, fontweight="bold", color="#333333",
            )

    # Tolerancia: 1 escalón adicional al valor máximo
    max_val = max(bottoms) if len(bottoms) > 0 else 0
    if max_val > 0:
        magnitud = 10 ** int(np.floor(np.log10(max_val)))
        escalon = magnitud if magnitud >= 100 else 100
        y_max = int(np.ceil(max_val / escalon) * escalon) + escalon
        ax.set_ylim(0, y_max)

    if tipo == "ventas":
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
        )

    ax.set_xticks(x)
    ax.set_xticklabels(etiq, fontsize=16, rotation=20, ha="right")
    ax.legend(fontsize=14, framealpha=0.8, loc="upper left", ncol=1)
    fig.tight_layout(pad=1.0)
    img = fig_to_base64(fig)
    _set_cache(ck, img)
    return jsonify({"img": img})

@app.route("/api/grafico_ventas_pronostico")
def api_grafico_ventas_pronostico():
    producto = request.args.get("producto", "Todos")
    meses = int(request.args.get("meses", 3))
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    ck = _cache_key("grafico_ventas_pronostico", producto, meses, modo, fecha_actual)
    cached = _get_cache(ck)
    if cached:
        return jsonify({"img": cached})

    df_pron = cargar_pronosticos()
    df_dem = cargar_demanda()
    df_prod = cargar_productos()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    if df_pron.empty:
        fig, ax = plt.subplots(figsize=(20, 6))
        ax.text(
            0.5, 0.5,
            "Sin datos de pronóstico. Ejecute el cálculo.",
            ha="center", va="center",
        )
        return jsonify({"img": fig_to_base64(fig)})

    if modo == "prueba" and fecha_actual:
        mes_actual = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_actual = pd.Timestamp.now().normalize().replace(day=1)

    precios = {}
    for _, row in df_prod.iterrows():
        nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
        precios[nm] = float(row.get("Precio Unitario ($)", 0))

    fechas_fut = pd.date_range(mes_actual, periods=meses, freq="MS")
    df_fut = df_pron[df_pron["Mes"].isin(fechas_fut)]

    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, "", "Mes", "Ventas ($)")

    x = np.arange(len(fechas_fut))
    etiq = [format_mes_abrev(f) for f in fechas_fut]

    bottoms = np.zeros(len(fechas_fut))

    for i, prod in enumerate(nombres):
        col_ventas = f"Pronostico_Ventas_{prod}"
        col_demanda = f"Pronostico_Demanda_{prod}"
        vals = []
        for f in fechas_fut:
            fila = df_fut[df_fut["Mes"] == f]
            if fila.empty:
                vals.append(0)
                continue
            if col_ventas in fila.columns:
                vals.append(float(fila[col_ventas].values[0]))
            elif col_demanda in fila.columns:
                vals.append(float(fila[col_demanda].values[0]) * precios.get(prod, 0))
            else:
                vals.append(0)

        ax.bar(
            x,
            vals,
            bottom=bottoms,
            width=0.7,
            color=color_producto(i),
            label=prod,
            alpha=0.88,
            edgecolor="white",
            linewidth=0.5,
        )
        # Valores dentro de las barras solo si Todos + (3 o 6 meses)
        mostrar_dentro = (producto == "Todos") and (meses in [3, 6])
        if mostrar_dentro:
            for j, (bar_val, bar_bottom) in enumerate(zip(vals, bottoms)):
                if bar_val > 0:
                    mid = bar_bottom + bar_val / 2
                    ax.text(
                        j, mid, _fmt_miles(bar_val),
                        ha="center", va="center",
                        fontsize=18, fontweight="bold", color="white",
                    )

        bottoms += np.array(vals)

    # Totales sobre barras — siempre $X.Xk
    for bar_idx, total in enumerate(bottoms):
        if total > 0:
            ax.text(
                x[bar_idx],
                total + (max(bottoms) * 0.02),
                _fmt_miles(total),
                ha="center", va="bottom",
                fontsize=20, fontweight="bold", color="#333333",
            )

    # Tolerancia: 1 escalón adicional al valor máximo
    max_val = max(bottoms) if len(bottoms) > 0 else 0
    if max_val > 0:
        magnitud = 10 ** int(np.floor(np.log10(max_val)))
        escalon = magnitud if magnitud >= 100 else 100
        y_max = int(np.ceil(max_val / escalon) * escalon) + escalon
        ax.set_ylim(0, y_max)

    ax.set_xticks(x)
    ax.set_xticklabels(etiq, fontsize=16, rotation=20, ha="right")
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
    )
    ax.legend(fontsize=14, framealpha=0.8, loc="upper left", ncol=1)
    fig.tight_layout(pad=1.0)
    img = fig_to_base64(fig)
    _set_cache(ck, img)
    return jsonify({"img": img})

@app.route("/api/dashboard_pronostico_resumen")
def api_dashboard_pronostico_resumen():
    producto = request.args.get("producto", "Todos")
    meses = int(request.args.get("meses", 3))
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    df_pron = cargar_pronosticos()
    df_dem = cargar_demanda()
    df_prod = cargar_productos()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    if modo == "prueba" and fecha_actual:
        mes_actual = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_actual = pd.Timestamp.now().normalize().replace(day=1)

    fechas_fut = pd.date_range(mes_actual, periods=meses, freq="MS")
    df_fut = (
        df_pron[df_pron["Mes"].isin(fechas_fut)]
        if not df_pron.empty
        else pd.DataFrame()
    )

    precios = {}
    for _, row in df_prod.iterrows():
        nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
        precios[nm] = float(row.get("Precio Unitario ($)", 0))

    productos_resumen = []
    total_demanda = 0
    total_ventas = 0

    for prod in nombres:
        col_dem = f"Pronostico_Demanda_{prod}"
        col_ven = f"Pronostico_Ventas_{prod}"

        demanda = float(df_fut[col_dem].sum()) if col_dem in df_fut.columns else 0.0
        if col_ven in df_fut.columns:
            ventas = float(df_fut[col_ven].sum())
        else:
            ventas = demanda * precios.get(prod, 0)

        total_demanda += demanda
        total_ventas += ventas
        productos_resumen.append(
            {
                "producto": prod,
                "demanda_total": demanda,
                "demanda_total_fmt": fmt_num(demanda),
                "ventas_total": ventas,
                "ventas_total_fmt": fmt_moneda(ventas),
            }
        )

    return jsonify(
        {
            "meses": meses,
            "demanda_total": total_demanda,
            "demanda_total_fmt": fmt_num(total_demanda),
            "ventas_total": total_ventas,
            "ventas_total_fmt": fmt_moneda(total_ventas),
            "productos": productos_resumen,
        }
    )

@app.route("/api/grafico_pap_resumen")
def api_grafico_pap_resumen():
    producto = request.args.get("producto", "Todos")
    meses = int(request.args.get("meses", 3))
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    ck = _cache_key("grafico_pap_resumen", producto, meses, modo, fecha_actual)
    cached = _get_cache(ck)
    if cached:
        return jsonify({"img": cached})

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    op = cargar_operarios()
    df_prod = cargar_productos()
    pap_dict = {}
    for prod in nombres:
        inv_ini = 25
        for _, row in df_prod.iterrows():
            nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nm == prod and "Inventario" in row:
                inv_ini = int(row["Inventario"])
                break
        from calculos import calcular_pap_producto
        pap_dict[prod] = calcular_pap_producto(
            prod, df_dem, df_pron, op, inv_ini, meses, modo, fecha_actual
        )

    if not pap_dict:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "Sin datos", ha="center", va="center")
        return jsonify({"img": fig_to_base64(fig)})

    # Valores dentro de barras: solo Todos + 3 o 6 meses
    mostrar_dentro = (producto == "Todos") and (meses in [3, 6])

    fig, axes = plt.subplots(1, 2, figsize=(28, 8))

    # ── Barras apiladas: costos ──────────────────────────────────────
    ax1 = axes[0]
    estilo_base(ax1, "Costo Total por Mes", "Mes", "Costo ($)")
    all_fechas = sorted(set(f for df in pap_dict.values() for f in df["Mes"].tolist()))
    etiq = [format_mes_abrev(f) for f in all_fechas]
    x = np.arange(len(all_fechas))
    bottom = np.zeros(len(all_fechas))
    acum_vals = {j: 0.0 for j in range(len(all_fechas))}

    for i, (prod, df) in enumerate(pap_dict.items()):
        vals = []
        for f in all_fechas:
            row = df[df["Mes"] == f]
            vals.append(float(row["Costo_total"].values[0]) if not row.empty else 0)
        ax1.bar(
            x, vals, bottom=bottom,
            color=color_producto(i), label=prod,
            alpha=0.88, edgecolor="white", linewidth=0.5,
        )
        if mostrar_dentro:
            for j, (bar_val, bar_bottom) in enumerate(zip(vals, bottom)):
                if bar_val > 0:
                    ax1.text(
                        j, bar_bottom + bar_val / 2,
                        f"${int(bar_val):,}",
                        ha="center", va="center",
                        fontsize=18, fontweight="bold", color="white",
                    )
        for j, v in enumerate(vals):
            acum_vals[j] += v
        bottom = bottom + np.array(vals)

    # Totales encima solo si mostrar_dentro
    if mostrar_dentro:
        max_acum = max(acum_vals.values()) if acum_vals else 0
        for j, total_val in acum_vals.items():
            if total_val > 0:
                ax1.text(
                    j, total_val + max_acum * 0.01,
                    f"${int(total_val):,}",
                    ha="center", va="bottom",
                    fontsize=18, fontweight="bold", color="#333333",
                )

    ax1.set_xticks(x)
    ax1.set_xticklabels(etiq, fontsize=18, rotation=20, ha="right")
    ax1.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
    )
    # Tolerancia: 1 escalón adicional
    max_costos = max(acum_vals.values()) if acum_vals else 0
    if max_costos > 0:
        magnitud = 10 ** int(np.floor(np.log10(max_costos)))
        escalon = magnitud if magnitud >= 100 else 100
        y_max_costos = int(np.ceil(max_costos / escalon) * escalon) + escalon
    else:
        y_max_costos = 1
    ax1.set_ylim(0, y_max_costos)
    ax1.legend(fontsize=16, framealpha=0.8, loc="upper left", ncol=1)

    # ── Producción planificada vs demanda ────────────────────────────
    ax2 = axes[1]
    estilo_base(ax2, "Producción Planificada vs Demanda", "Mes", "Unidades")
    n_prod = len(pap_dict)
    w = 0.6 / max(n_prod, 1)

    all_vals_flat = []
    for prod, df in pap_dict.items():
        for f in all_fechas:
            row = df[df["Mes"] == f]
            if not row.empty:
                all_vals_flat.append(int(row["Demanda"].values[0]))
                all_vals_flat.append(int(row["Unidades_producidas"].values[0]))
    max_val = max(all_vals_flat + [1])

    for i, (prod, df) in enumerate(pap_dict.items()):
        dem_vals = []
        prod_vals = []
        for f in all_fechas:
            row = df[df["Mes"] == f]
            dem_vals.append(int(row["Demanda"].values[0]) if not row.empty else 0)
            prod_vals.append(int(row["Unidades_producidas"].values[0]) if not row.empty else 0)
        off = (i - (n_prod - 1) / 2) * w
        bars = ax2.bar(
            x + off, prod_vals, w * 0.85,
            color=color_producto(i), label=prod,
            alpha=0.85, edgecolor="white",
        )
        if mostrar_dentro:
            for bar, v in zip(bars, prod_vals):
                if v > 0:
                    ax2.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() / 2,
                        str(v),
                        ha="center", va="center",
                        fontsize=16, fontweight="bold", color="white",
                    )
        for j, (dv, bar) in enumerate(zip(dem_vals, bars)):
            cx = bar.get_x() + bar.get_width() / 2
            half = w * 0.85 / 2 * 1.3
            ax2.plot(
                [cx - half, cx + half], [dv, dv],
                color="#EE1111", linewidth=3,
                solid_capstyle="round", zorder=5,
            )
            if mostrar_dentro:
                ax2.text(
                    cx, dv + max_val * 0.015,
                    str(dv),
                    ha="center", va="bottom",
                    fontsize=14, fontweight="bold", color="#CC0000",
                )

    ax2.set_xticks(x)
    ax2.set_xticklabels(etiq, fontsize=18, rotation=20, ha="right")
    # Tolerancia: 1 escalón adicional
    if max_val > 0:
        magnitud2 = 10 ** int(np.floor(np.log10(max_val)))
        escalon2 = magnitud2 if magnitud2 >= 100 else 100
        y_max_unid = int(np.ceil(max_val / escalon2) * escalon2) + escalon2
    else:
        y_max_unid = 1
    ax2.set_ylim(0, y_max_unid)

    handles2, labels2 = ax2.get_legend_handles_labels()
    dem_line = matplotlib.lines.Line2D(
        [0], [0], color="#EE1111", linewidth=3, label="Demanda"
    )
    ax2.legend(
        handles=handles2 + [dem_line],
        fontsize=16, framealpha=0.8, loc="upper left", ncol=1,
    )

    fig.tight_layout(pad=1.5)
    img = fig_to_base64(fig)
    _set_cache(ck, img)
    return jsonify({"img": img})

# ─── API: TABLA PRONÓSTICO ───────────────────────────────────────────────────
@app.route("/api/tabla_pronostico")
def api_tabla_pronostico():
    producto = request.args.get("producto", "Todos")
    meses = int(request.args.get("meses", 6))
    tipo = request.args.get("tipo", "demanda")
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    df_pron = cargar_pronosticos()
    df_dem = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    if df_pron.empty:
        return jsonify({"columnas": [], "filas": []})

    if modo == "prueba" and fecha_actual:
        mes_actual = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_actual = pd.Timestamp.now().normalize().replace(day=1)

    fechas_fut = pd.date_range(mes_actual, periods=meses, freq="MS")
    df_fut = df_pron[df_pron["Mes"].isin(fechas_fut)].copy()

    filas = []
    for _, row in df_fut.iterrows():
        fila = {"Mes": format_mes_abrev(row["Mes"])}
        for prod in nombres:
            if tipo == "ventas":
                col = f"Pronostico_Ventas_{prod}"
                if col in row:
                    fila[prod] = fmt_moneda(row[col])
            else:
                col = f"Pronostico_Demanda_{prod}"
                if col in row:
                    fila[prod] = fmt_num(row[col])
        filas.append(fila)

    return jsonify({"columnas": ["Mes"] + nombres, "filas": filas})


# ─── API: TABLA PAP ──────────────────────────────────────────────────────────

@app.route("/api/tabla_pap")
def api_tabla_pap():
    producto = request.args.get("producto", "Todos")
    meses = int(request.args.get("meses", 3))
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    df_prod = cargar_productos()
    op = cargar_operarios()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    from calculos import calcular_pap_producto

    filas = []
    for prod in nombres:
        inv_ini = 25
        precio_prod = 3.5
        for _, row in df_prod.iterrows():
            nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nm == prod and "Inventario" in row:
                inv_ini = int(row["Inventario"])
                precio_prod = float(row.get("Precio Unitario ($)", 3.5))
                break
        df_pap = calcular_pap_producto(
            prod, df_dem, df_pron, op, inv_ini, meses, modo, fecha_actual
        )
        for _, r in df_pap.iterrows():
            filas.append({
                "Mes": r["Mes"].strftime("%b %Y"),
                "Costo Total": fmt_moneda(r["Costo_total"]),
                "Unidades Prod.": fmt_num(r["Unidades_producidas"]),
                "Unidades Disp.": fmt_num(r["Unidades_disponibles"]),
                "Inventario Final": fmt_num(r["Inventario_final"]),
                "Días": int(r["Dias"]),
                "Demanda": fmt_num(r["Demanda"]),
                "Und./Operario": int(r["Unidades_por_operario"]),
                "Operarios Req.": int(r["Operarios_requeridos"]),
                "Operarios Act.": int(r["Operarios_actuales"]),
                "Operarios Contr.": int(r["Operarios_contratados"]),
                "Operarios Desp.": int(r["Operarios_despedidos"]),
                "Operarios Util.": int(r["Operarios_utilizados"]),
                "Costo Contratar": fmt_moneda(r["Costo_contratar"]),
                "Costo Despedir": fmt_moneda(r["Costo_despedir"]),
                "Costo Mano de Obra": fmt_moneda(r["Costo_mano_obra"]),
                "Costo Almacén": fmt_moneda(r["Costo_almacenamiento"]),
            })

    cols = [
        "Mes",
        "Costo Total",
        "Unidades Prod.",
        "Unidades Disp.",
        "Inventario Final",
        "Días",
        "Demanda",
        "Und./Operario",
        "Operarios Req.",
        "Operarios Act.",
        "Operarios Contr.",
        "Operarios Desp.",
        "Operarios Util.",
        "Costo Contratar",
        "Costo Despedir",
        "Costo Mano de Obra",
        "Costo Almacén",
    ]
    return jsonify({"columnas": cols, "filas": filas})

@app.route("/api/pap_resumen")
def api_pap_resumen():
    producto = request.args.get("producto", "Todos")
    meses = int(request.args.get("meses", 3))
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    df_prod = cargar_productos()
    op = cargar_operarios()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    from calculos import calcular_pap_producto

    resumen = {
        "inventario_inicial": 0,
        "operarios_requeridos_max": 0,
        "operarios_contratados_total": 0,
        "operarios_despedidos_total": 0,
        "unidades_disponibles_ultimo": 0,
        "inventario_final": 0,
        "costo_contratar": 0,
        "costo_despedir": 0,
        "costo_mano_obra": 0,
        "costo_mantenimiento": 0,
        "costo_total": 0,
    }

    for prod in nombres:
        inv_ini = 25
        precio_prod = 3.5
        for _, row in df_prod.iterrows():
            nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nm == prod:
                inv_ini = int(row.get("Inventario", 25))
                precio_prod = float(row.get("Precio Unitario ($)", 3.5))
                break

        df_pap = calcular_pap_producto(
            prod, df_dem, df_pron, op, inv_ini, meses, modo, fecha_actual
        )

        resumen["inventario_inicial"] += inv_ini
        resumen["operarios_requeridos_max"] = max(
            resumen["operarios_requeridos_max"],
            int(df_pap["Operarios_requeridos"].max()),
        )
        resumen["operarios_contratados_total"] += int(df_pap["Operarios_contratados"].sum())
        resumen["operarios_despedidos_total"] += int(df_pap["Operarios_despedidos"].sum())
        # Unidades disponibles del último mes
        resumen["unidades_disponibles_ultimo"] += int(df_pap["Unidades_disponibles"].iloc[-1])
        resumen["inventario_final"] += int(df_pap["Inventario_final"].iloc[-1])
        resumen["costo_contratar"] += round(df_pap["Costo_contratar"].sum(), 2)
        resumen["costo_despedir"] += round(df_pap["Costo_despedir"].sum(), 2)
        resumen["costo_mano_obra"] += round(df_pap["Costo_mano_obra"].sum(), 2)
        resumen["costo_mantenimiento"] += round(df_pap["Costo_almacenamiento"].sum(), 2)
        resumen["costo_total"] += round(df_pap["Costo_total"].sum(), 2)

    return jsonify(resumen)

@app.route("/api/pap_dashboard_tablas")
def api_pap_dashboard_tablas():
    producto = request.args.get("producto", "Todos")
    meses = int(request.args.get("meses", 3))
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    df_prod = cargar_productos()
    op = cargar_operarios()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    from calculos import calcular_pap_producto

    tablas_por_producto = {}
    costo_total_horizonte = 0

    for prod in nombres:
        inv_ini = 25
        precio_prod = 3.5
        for _, row in df_prod.iterrows():
            nm = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nm == prod:
                inv_ini = int(row.get("Inventario", 25))
                precio_prod = float(row.get("Precio Unitario ($)", 3.5))
                break

        df_pap = calcular_pap_producto(
            prod, df_dem, df_pron, op, inv_ini, meses, modo, fecha_actual
        )
        df_pap["Precio_Produccion"] = precio_prod
        costo_prod = df_pap["Costo_total"].sum()
        costo_total_horizonte += costo_prod

        filas = []
        for _, r in df_pap.iterrows():
            filas.append({
                "Mes": r["Mes"].strftime("%b %Y"),
                "Costo Total": fmt_moneda(r["Costo_total"]),
                "Unidades Prod.": fmt_num(r["Unidades_producidas"]),
                "Unidades Disp.": fmt_num(r["Unidades_disponibles"]),
                "Inventario Final": fmt_num(r["Inventario_final"]),
                "Días": int(r["Dias"]),
                "Demanda": fmt_num(r["Demanda"]),
                "Und./Operario": int(r["Unidades_por_operario"]),
                "Operarios Req.": int(r["Operarios_requeridos"]),
                "Operarios Act.": int(r["Operarios_actuales"]),
                "Operarios Contr.": int(r["Operarios_contratados"]),
                "Operarios Desp.": int(r["Operarios_despedidos"]),
                "Operarios Util.": int(r["Operarios_utilizados"]),
                "Costo Contratar": fmt_moneda(r["Costo_contratar"]),
                "Costo Despedir": fmt_moneda(r["Costo_despedir"]),
                "Costo Mano de Obra": fmt_moneda(r["Costo_mano_obra"]),
                "Costo Almacén": fmt_moneda(r["Costo_almacenamiento"]),
            })

        cols = [
            "Mes",
            "Costo Total",
            "Unidades Prod.",
            "Unidades Disp.",
            "Inventario Final",
            "Días",
            "Demanda",
            "Und./Operario",
            "Operarios Req.",
            "Operarios Act.",
            "Operarios Contr.",
            "Operarios Desp.",
            "Operarios Util.",
            "Costo Contratar",
            "Costo Despedir",
            "Costo Mano de Obra",
            "Costo Almacén",
        ]

        tablas_por_producto[prod] = {
            "columnas": cols,
            "filas": filas,
            "costo_prod": fmt_moneda(costo_prod),
            "costo_total": fmt_moneda(costo_prod),
        }

    return jsonify({
        "tablas": tablas_por_producto,
        "costo_total_horizonte": fmt_moneda(costo_total_horizonte),
    })

# ─── API: TABLA DEMANDA ──────────────────────────────────────────────────────


@app.route("/api/tabla_demanda")
def api_tabla_demanda():
    producto = request.args.get("producto", "Todos")
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    df_dem = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    if modo == "prueba" and fecha_actual:
        mes_corte = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_corte = pd.Timestamp.now().normalize().replace(day=1)

    # Mostrar hasta el mes actual del modo, incluyendo el mes corte aunque no exista en datos
    df_filtrado = df_dem[df_dem["Mes"] <= mes_corte].copy()
    if df_filtrado.empty or mes_corte not in set(pd.to_datetime(df_filtrado["Mes"])):
        nueva_fila = {col: 0 for col in df_dem.columns if col != "Mes"}
        nueva_fila["Mes"] = mes_corte
        df_filtrado = pd.concat(
            [df_filtrado, pd.DataFrame([nueva_fila])], ignore_index=True
        )
    df_filtrado = df_filtrado.sort_values("Mes").reset_index(drop=True)

    filas = []
    for _, row in df_filtrado.iterrows():
        fecha = pd.Timestamp(row["Mes"])
        fila = {"Mes": format_mes_abrev(fecha)}
        for prod in nombres:
            col = f"Demanda_{prod}"
            fila[prod] = fmt_num(row[col]) if col in row else "0"
        filas.append(fila)

    return jsonify({"columnas": ["Mes"] + nombres, "filas": list(reversed(filas))})


@app.route("/api/grafico_demanda_barras")
def api_grafico_demanda_barras():
    producto = request.args.get("producto", "Todos")
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    df_dem = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    if modo == "prueba" and fecha_actual:
        mes_corte = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_corte = pd.Timestamp.now().normalize().replace(day=1)

    fecha_inicio = mes_corte - pd.DateOffset(months=17)
    rango_meses = pd.date_range(fecha_inicio, periods=18, freq="MS")
    df_rango = pd.DataFrame({"Mes": rango_meses})
    df_hist = pd.merge(
        df_rango, df_dem[df_dem["Mes"] <= mes_corte], on="Mes", how="left"
    ).fillna(0)
    df_hist["Mes"] = pd.to_datetime(df_hist["Mes"])

    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, "Histórico de Demanda por Producto", "Mes", "Unidades")

    x = np.arange(len(df_hist))
    etiq = [format_mes_abrev(pd.Timestamp(m)) for m in df_hist["Mes"]]
    n = len(nombres)
    w = 0.7 / max(n, 1)

    for i, prod in enumerate(nombres):
        col = f"Demanda_{prod}"
        if col not in df_hist.columns:
            continue
        vals = df_hist[col].fillna(0).values
        off = (i - (n - 1) / 2) * w
        ax.bar(
            x + off,
            vals,
            w * 0.9,
            color=color_producto(i),
            label=prod,
            alpha=0.88,
            edgecolor="white",
            linewidth=0.5,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(etiq, fontsize=14, rotation=20, ha="right")
    ax.legend(fontsize=16, framealpha=0.8)
    fig.tight_layout(pad=1.0)
    return jsonify({"img": fig_to_base64(fig)})


# ─── API: TABLA VENTAS ───────────────────────────────────────────────────────


@app.route("/api/tabla_ventas")
def api_tabla_ventas():
    producto = request.args.get("producto", "Todos")
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    df_dem = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    if modo == "prueba" and fecha_actual:
        mes_corte = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_corte = pd.Timestamp.now().normalize().replace(day=1)

    # Mostrar hasta el mes actual del modo, incluyendo el mes corte aunque no exista en datos
    df_filtrado = df_dem[df_dem["Mes"] <= mes_corte].copy()
    if df_filtrado.empty or mes_corte not in set(pd.to_datetime(df_filtrado["Mes"])):
        nueva_fila = {col: 0 for col in df_dem.columns if col != "Mes"}
        nueva_fila["Mes"] = mes_corte
        df_filtrado = pd.concat(
            [df_filtrado, pd.DataFrame([nueva_fila])], ignore_index=True
        )
    df_filtrado = df_filtrado.sort_values("Mes").reset_index(drop=True)

    filas = []
    for _, row in df_filtrado.iterrows():
        fecha = pd.Timestamp(row["Mes"])
        fila = {"Mes": format_mes_abrev(fecha)}
        for prod in nombres:
            col = f"Ventas_{prod}"
            fila[prod] = fmt_moneda(row[col]) if col in row else "$0.00"
        filas.append(fila)

    return jsonify({"columnas": ["Mes"] + nombres, "filas": list(reversed(filas))})


@app.route("/api/grafico_ventas_historico")
def api_grafico_ventas_historico():
    producto = request.args.get("producto", "Todos")
    modo = request.args.get("modo", "produccion")
    fecha_actual = request.args.get("fecha_actual")

    df_dem = cargar_demanda()
    nombres = obtener_nombres_productos(df_dem)

    if producto != "Todos":
        nombres = [p for p in nombres if p == producto]

    if modo == "prueba" and fecha_actual:
        mes_corte = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        mes_corte = pd.Timestamp.now().normalize().replace(day=1)

    fecha_inicio = mes_corte - pd.DateOffset(months=17)
    rango_meses = pd.date_range(fecha_inicio, periods=18, freq="MS")
    df_rango = pd.DataFrame({"Mes": rango_meses})
    df_hist = pd.merge(
        df_rango, df_dem[df_dem["Mes"] <= mes_corte], on="Mes", how="left"
    ).fillna(0)
    df_hist["Mes"] = pd.to_datetime(df_hist["Mes"])

    fig, ax = plt.subplots(figsize=(20, 6))
    estilo_base(ax, "Histórico de Ventas por Producto", "Mes", "Ventas ($)")

    x = np.arange(len(df_hist))
    etiq = [format_mes_abrev(pd.Timestamp(m)) for m in df_hist["Mes"]]
    n = len(nombres)
    w = 0.7 / max(n, 1)

    for i, prod in enumerate(nombres):
        col = f"Ventas_{prod}"
        if col not in df_hist.columns:
            continue
        vals = df_hist[col].fillna(0).values
        off = (i - (n - 1) / 2) * w
        ax.bar(
            x + off,
            vals,
            w * 0.9,
            color=color_producto(i),
            label=prod,
            alpha=0.88,
            edgecolor="white",
            linewidth=0.5,
        )

    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
    )
    ax.set_xticks(x)
    ax.set_xticklabels(etiq, fontsize=14, rotation=20, ha="right")
    ax.legend(fontsize=16, framealpha=0.8)
    fig.tight_layout(pad=1.0)
    return jsonify({"img": fig_to_base64(fig)})


# ─── API: ACCIONES ───────────────────────────────────────────────────────────

@app.route("/api/recalcular_pronostico", methods=["POST"])
def api_recalcular_pronostico():
    try:
        data = request.json or {}
        n_meses = int(data.get("meses", 12))
        modo = data.get("modo", "produccion")
        fecha_actual = data.get("fecha_actual")

        from calculos import calcular_hash_valores_demanda, guardar_estado_calculo

        df_dem = cargar_demanda()

        if modo == "prueba" and fecha_actual:
            fecha_calc = fecha_actual
        else:
            hoy = pd.Timestamp.now().normalize()
            fecha_calc = hoy.strftime("%Y-%m-%d")

        hash_valores = calcular_hash_valores_demanda(df_dem, fecha_calc)
        guardar_estado_calculo(modo, fecha_calc, hash_valores)

        df_pron = ejecutar_pronostico_completo(n_meses, modo, fecha_actual)
        _graph_cache.clear()  # invalidar cache tras recalcular
        return jsonify({"ok": True, "meses": n_meses, "filas": len(df_pron)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/actualizar_demanda", methods=["POST"])
def api_actualizar_demanda():
    try:
        data = request.json
        mes_str = data.get("mes")
        prod = data.get("producto")
        valor = float(data.get("valor", 0))

        df_dem = cargar_demanda()
        df_prod = cargar_productos()
        mes = pd.Timestamp(mes_str)
        col_dem = f"Demanda_{prod}"
        col_ven = f"Ventas_{prod}"

        if col_dem not in df_dem.columns:
            return jsonify(
                {"ok": False, "error": f"Producto no encontrado: {prod}"}
            ), 400

        ventas_precio = 3.5
        for _, row in df_prod.iterrows():
            nombre_completo = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nombre_completo == prod:
                ventas_precio = float(row["Precio Unitario ($)"])
                break

        mask = df_dem["Mes"] == mes
        if mask.any():
            df_dem.loc[mask, col_dem] = valor
            df_dem.loc[mask, col_ven] = valor * ventas_precio
        else:
            nueva_fila = {"Mes": mes}
            for c in df_dem.columns:
                if c != "Mes":
                    nueva_fila[c] = 0
            nueva_fila[col_dem] = valor
            nueva_fila[col_ven] = valor * ventas_precio
            df_dem = pd.concat([df_dem, pd.DataFrame([nueva_fila])], ignore_index=True)
            df_dem = df_dem.sort_values("Mes").reset_index(drop=True)

        guardar_demanda(df_dem)
        _graph_cache.clear()  # invalidar cache tras cambio de demanda
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
        
@app.route("/api/agregar_producto", methods=["POST"])
def api_agregar_producto():
    try:
        data = request.json
        nombre = data.get("nombre", "").strip()
        tamano = int(data.get("tamano", 170))
        precio = float(data.get("precio", 3.5))
        inventario = int(data.get("inventario", 0))
        prod_por_op = int(data.get("prod_por_op", 3))
        lote = int(data.get("lote", 100))

        df_prod = cargar_productos()
        nombre_completo = f"{nombre} {tamano} g"

        nueva_fila = {
            "Nombre": nombre,
            "Tamaño (g)": tamano,
            "Descripción": nombre_completo,
            "Precio Unitario ($)": precio,
            "Lote": lote,
            "Inventario": inventario,
            "Produccion promedio (por operario)": prod_por_op,
        }
        # Rellenar insumos con 0
        for col in df_prod.columns:
            if col not in nueva_fila:
                nueva_fila[col] = 0

        df_prod = pd.concat([df_prod, pd.DataFrame([nueva_fila])], ignore_index=True)
        guardar_productos(df_prod)

        # Agregar columnas en demanda
        df_dem = cargar_demanda()
        col_dem = f"Demanda_{nombre_completo}"
        col_ven = f"Ventas_{nombre_completo}"
        if col_dem not in df_dem.columns:
            df_dem[col_dem] = 0
            df_dem[col_ven] = 0
            guardar_demanda(df_dem)

        return jsonify({"ok": True, "nombre": nombre_completo})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/actualizar_operarios", methods=["POST"])
def api_actualizar_operarios():
    try:
        data = request.json
        op = cargar_operarios()
        for k in [
            "operarios",
            "costo_contratar",
            "costo_despedir",
            "costo_almacenamiento",
            "costo_hora_extra",
            "costo_hora_normal",
            "jornada_normal",
        ]:
            if k in data:
                op[k] = float(data[k])
        guardar_operarios(op)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/meses_disponibles")
def api_meses_disponibles():
    df_dem = cargar_demanda()
    meses = [pd.Timestamp(m).strftime("%Y-%m-%d") for m in df_dem["Mes"]]
    return jsonify(meses)


if __name__ == "__main__":
    # Inicializar pronóstico si no existe
    import os as _os

    if not _os.path.exists(_os.path.join("data", "pronosticos.csv")):
        print("Calculando pronóstico inicial...")
        ejecutar_pronostico_completo(12)

    app.run(debug=False, host="0.0.0.0", port=5050)
