"""
calculos.py - Módulo central de cálculos para ASOPRIABET Aromas del Yasuní.
Pronóstico por descomposición estacional y Plan Agregado de Producción (PAP).
"""
import os
import json
import hashlib
import pandas as pd
import numpy as np
from datetime import datetime, date
import calendar
import math

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
SESSION_DIR = os.path.join(os.path.dirname(__file__), 'sessions')


# ─────────────────────────────────────────────
# SESIÓN Y LOGIN
# ─────────────────────────────────────────────

def crear_sesion_dir():
    """Crea directorio de sesiones si no existe."""
    if not os.path.exists(SESSION_DIR):
        os.makedirs(SESSION_DIR)


def guardar_sesion(datos_sesion):
    """Guarda datos de sesión en JSON."""
    crear_sesion_dir()
    path = os.path.join(SESSION_DIR, 'session.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(datos_sesion, f, ensure_ascii=False, indent=2)


def cargar_sesion():
    """Carga datos de sesión desde JSON."""
    path = os.path.join(SESSION_DIR, 'session.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def verificar_login(password):
    """Verifica contraseña para modificación de valores."""
    # Contraseña por defecto: admin123
    # Esta contraseña se usa solo para modificar valores de demanda y operarios
    # No se requiere para cálculos ni cambio de modo
    # En producción, esto debería estar en configuración segura
    return password == 'admin123'


def guardar_estado_calculo(modo, fecha_actual, hash_valores):
    """Guarda estado del último cálculo para detectar cambios."""
    crear_sesion_dir()
    path = os.path.join(SESSION_DIR, 'calc_state.json')
    estado = {
        'modo': modo,
        'fecha_actual': fecha_actual,
        'hash_valores': hash_valores,
        'timestamp': datetime.now().isoformat()
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def cargar_estado_calculo():
    """Carga estado del último cálculo."""
    path = os.path.join(SESSION_DIR, 'calc_state.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def calcular_hash_valores_demanda(df_dem, fecha_actual):
    """Calcula hash de los valores de demanda para detectar cambios."""
    # Filtrar solo datos hasta la fecha actual
    df_filtrado = df_dem[df_dem['Mes'] <= pd.Timestamp(fecha_actual)]
    # Crear string con todos los valores
    valores_str = df_filtrado.to_csv(index=False)
    return hashlib.md5(valores_str.encode()).hexdigest()


# ─────────────────────────────────────────────
# CARGA Y GUARDADO DE DATOS
# ─────────────────────────────────────────────

def cargar_demanda():
    path = os.path.join(DATA_DIR, 'demanda.csv')
    df = pd.read_csv(path, parse_dates=['Mes'])
    df = df.sort_values('Mes').reset_index(drop=True)
    return df


def guardar_demanda(df):
    path = os.path.join(DATA_DIR, 'demanda.csv')
    df.to_csv(path, index=False, date_format='%Y-%m-%d')


def cargar_productos():
    path = os.path.join(DATA_DIR, 'productos.csv')
    return pd.read_csv(path)


def guardar_productos(df):
    path = os.path.join(DATA_DIR, 'productos.csv')
    df.to_csv(path, index=False)


def cargar_operarios():
    path = os.path.join(DATA_DIR, 'operarios.csv')
    return pd.read_csv(path).iloc[0].to_dict()


def guardar_operarios(datos):
    path = os.path.join(DATA_DIR, 'operarios.csv')
    pd.DataFrame([datos]).to_csv(path, index=False)


def cargar_pronosticos():
    path = os.path.join(DATA_DIR, 'pronosticos.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=['Mes'])


def guardar_pronosticos(df):
    path = os.path.join(DATA_DIR, 'pronosticos.csv')
    df.to_csv(path, index=False, date_format='%Y-%m-%d')


def cargar_pap():
    path = os.path.join(DATA_DIR, 'pap.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=['Mes'])


def guardar_pap(df):
    path = os.path.join(DATA_DIR, 'pap.csv')
    df.to_csv(path, index=False, date_format='%Y-%m-%d')


# ─────────────────────────────────────────────
# NOMBRES DE PRODUCTOS
# ─────────────────────────────────────────────

def obtener_columnas_demanda(df_dem):
    """Devuelve lista de nombres de columnas de demanda."""
    return [c for c in df_dem.columns if c.startswith('Demanda_')]


def obtener_nombres_productos(df_dem):
    """Devuelve lista de nombres de productos (sin prefijo 'Demanda_')."""
    return [c.replace('Demanda_', '') for c in obtener_columnas_demanda(df_dem)]


# ─────────────────────────────────────────────
# PRONÓSTICO POR DESCOMPOSICIÓN ESTACIONAL
# ─────────────────────────────────────────────

import pandas as pd
import numpy as np
import math


import pandas as pd
import numpy as np
import math


def roundup_excel(valor):
    """
    Equivalente a ROUNDUP(valor,0) de Excel.
    """

    if pd.isna(valor):
        return np.nan

    if valor >= 0:
        return math.ceil(valor)

    return math.floor(valor)


def calcular_pronostico_descomposicion(
    serie,
    n_periodos=12
):
    """
    Método de Descomposición.

    IE = Promedio mensual / Promedio global
    IE ajustado = IE / SUM(IE) * 12
    DD = Demanda / IE ajustado

    Regresión lineal:
        DD = a + b*t

    Pronóstico:
        T = ROUNDUP(a + b*t)
        Ft = ROUNDUP(T * IE ajustado)

    Regla:
    - Excluir únicamente los ceros iniciales consecutivos
      de la regresión.
    - Mantener cualquier cero posterior.
    """

    serie = serie.dropna().copy()

    if len(serie) == 0:
        return pd.Series(dtype=float)

    # --------------------------------------------------
    # Buscar primer dato positivo
    # --------------------------------------------------

    primer_idx = None

    for i, valor in enumerate(serie.values):

        if valor > 0:
            primer_idx = i
            break

    # Serie completamente en cero

    if primer_idx is None:

        fechas_fut = pd.date_range(
            start=(
                serie.index[-1]
                + pd.DateOffset(months=1)
            ),
            periods=n_periodos,
            freq="MS"
        )

        return pd.Series(
            [0] * n_periodos,
            index=fechas_fut
        )

    # --------------------------------------------------
    # Serie utilizada para IE
    # (incluye todos los datos reales)
    # --------------------------------------------------

    serie_ie = serie.iloc[primer_idx:]

    # --------------------------------------------------
    # Promedios mensuales
    # --------------------------------------------------

    promedios_mes = {}

    for mes in range(1, 13):

        datos_mes = serie_ie[
            serie_ie.index.month == mes
        ]
        if len(datos_mes) > 0:
            promedios_mes[mes] = (
                datos_mes.mean()
            )

    # --------------------------------------------------
    # Promedio global
    # Promedio de los promedios mensuales
    # --------------------------------------------------

    promedio_global = np.mean(
        list(promedios_mes.values())
    )

    # --------------------------------------------------
    # PROMEDIOS MENSUALES
    # --------------------------------------------------

    serie_ie = serie.iloc[primer_idx:]

    promedios_mes = {}

    for mes in range(1, 13):

        datos_mes = serie_ie[
            serie_ie.index.month == mes
        ]

        if len(datos_mes) > 0:

            promedios_mes[mes] = (
                datos_mes.mean()
            )

    # --------------------------------------------------
    # PROMEDIO GLOBAL
    # Excel:
    # PROMEDIO(promedios mensuales)
    # --------------------------------------------------

    promedio_global = np.mean(
        list(promedios_mes.values())
    )

    # --------------------------------------------------
    # IE
    # --------------------------------------------------

    ie = {}

    for mes in range(1, 13):

        if mes in promedios_mes:

            ie[mes] = (
                promedios_mes[mes]
                / promedio_global
            )

        else:

            ie[mes] = 1.0

    # --------------------------------------------------
    # IE AJUSTADO
    # Excel:
    # IE / SUMA(IE) * 12
    # --------------------------------------------------

    suma_ie = sum(ie.values())

    estacional = {}

    for mes in range(1, 13):

        estacional[mes] = (
            ie[mes]
            / suma_ie
            * 12
        )
        
    # --------------------------------------------------
    # DD
    # --------------------------------------------------

    desest = pd.Series(
        [
            round(
                valor
                / estacional[fecha.month],
                0
            )
            for fecha, valor
            in serie.items()
        ],
        index=serie.index
    )

    # --------------------------------------------------
    # Regresión
    # Excluir solo ceros iniciales
    # --------------------------------------------------

    desest_reg = desest.iloc[primer_idx:]

    x_reg = np.arange(
        1,
        len(desest_reg) + 1
    )

    pendiente, intercepto = np.polyfit(
        x_reg,
        desest_reg.values,
        1
    )

    # --------------------------------------------------
    # Fechas futuras
    # --------------------------------------------------

    fechas_fut = pd.date_range(
        start=(
            serie.index[-1]
            + pd.DateOffset(months=1)
        ),
        periods=n_periodos,
        freq="MS"
    )

    resultados = []

    for i, fecha in enumerate(
        fechas_fut
    ):

        # Continuación natural de t

        t_reg = (
            len(desest_reg)
            + i
            + 1
        )

        # Tendencia

        T = roundup_excel(
            intercepto
            + pendiente * t_reg
        )

        # Pronóstico

        Ft = roundup_excel(
            T
            * estacional[fecha.month]
        )

        resultados.append(
            max(Ft, 0)
        )

    return pd.Series(

        resultados,
        index=fechas_fut

    )

def calcular_pronostico_ventas(demanda_serie, precio_unitario, n_periodos=12):
    """
    Calcula pronóstico de ventas = pronóstico demanda * precio.
    """
    pron_dem = calcular_pronostico_descomposicion(demanda_serie, n_periodos)
    return pron_dem * precio_unitario


def calcular_mape(real, pronostico):
    """Calcula MAPE entre dos series alineadas."""
    comun = real.index.intersection(pronostico.index)
    if len(comun) == 0:
        return None
    r = real[comun]
    p = pronostico[comun]
    mask = r != 0
    if mask.sum() == 0:
        return None
    return float((abs(r[mask] - p[mask]) / r[mask]).mean() * 100)


def detectar_periodo_uno(df_dem, nombre_producto):
    """
    Detecta el mes periodo 1 (primer mes con demanda > 0 desde el inicio).
    """
    col_dem = f'Demanda_{nombre_producto}'
    if col_dem not in df_dem.columns:
        return None
    
    for idx, row in df_dem.iterrows():
        valor = float(row[col_dem])
        if valor > 0:
            return row['Mes']
    return None


def verificar_ceros_demanda(df_dem, nombre_producto, fecha_actual):
    """
    Verifica si hay demandas = 0 después del periodo 1.
    Retorna lista de fechas con demanda cero después del periodo 1.
    """
    col_dem = f'Demanda_{nombre_producto}'
    if col_dem not in df_dem.columns:
        return []
    
    periodo_uno = detectar_periodo_uno(df_dem, nombre_producto)
    if not periodo_uno:
        return []
    
    # Filtrar datos después del periodo 1 y hasta fecha actual
    df_filtrado = df_dem[(df_dem['Mes'] > periodo_uno) & (df_dem['Mes'] <= pd.Timestamp(fecha_actual))].copy()
    
    ceros = []
    for idx, row in df_filtrado.iterrows():
        valor = float(row[col_dem])
        if valor == 0:
            ceros.append(row['Mes'])
    
    return ceros


def verificar_ceros_demanda_todos(df_dem, fecha_actual):
    """
    Verifica ceros de demanda para todos los productos.
    Retorna dict con productos y sus fechas con cero.
    """
    nombres = obtener_nombres_productos(df_dem)
    resultado = {}
    for prod in nombres:
        ceros = verificar_ceros_demanda(df_dem, prod, fecha_actual)
        if ceros:
            resultado[prod] = ceros
    return resultado


def necesita_recalculo(modo, fecha_actual):
    """
    Determina si es necesario recalcular basado en cambios de modo o valores.
    Retorna (necesita, razon)
    """
    estado_actual = cargar_estado_calculo()
    
    if not estado_actual:
        return True, "Primer cálculo"
    
    # Verificar cambio de modo
    if estado_actual.get('modo') != modo:
        return True, f"Cambio de modo: {estado_actual.get('modo')} -> {modo}"
    
    # Verificar cambio de fecha actual
    if estado_actual.get('fecha_actual') != str(fecha_actual):
        return True, f"Cambio de fecha: {estado_actual.get('fecha_actual')} -> {fecha_actual}"
    
    # Verificar cambio en valores de demanda
    df_dem = cargar_demanda()
    hash_actual = calcular_hash_valores_demanda(df_dem, fecha_actual)
    if estado_actual.get('hash_valores') != hash_actual:
        return True, "Cambios en valores de demanda detectados"
    
    return False, "Sin cambios"


def ejecutar_pronostico_completo(n_periodos=12, modo='produccion', fecha_actual=None):
    """
    Ejecuta pronóstico de demanda y ventas para todos los productos.
    Guarda resultados en pronosticos.csv.
    Retorna DataFrame con columnas: Mes, Pronostico_Demanda_<prod>, Pronostico_Ventas_<prod>
    
    Args:
        n_periodos: número de periodos a pronosticar (default 12)
        modo: 'produccion' o 'prueba' (default 'produccion')
        fecha_actual: fecha actual para modo prueba (None para producción)
    """
    df_dem = cargar_demanda()
    df_prod = cargar_productos()
    nombres_prod = obtener_nombres_productos(df_dem)

    # Determinar fecha actual según modo
    if modo == 'prueba' and fecha_actual:
        mes_actual = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        hoy = pd.Timestamp.now().normalize()
        mes_actual = hoy.replace(day=1)

    # Usar datos hasta el mes anterior al actual para cálculo del pronóstico
    # pero el pronóstico incluirá el mes actual
    df_hist = df_dem[df_dem['Mes'] < mes_actual].copy()

    precios = {}
    for _, row in df_prod.iterrows():
        nombre_completo = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
        precios[nombre_completo] = float(row['Precio Unitario ($)'])

    resultados = {}
    for prod in nombres_prod:
        col_dem = f'Demanda_{prod}'
        if col_dem not in df_hist.columns:
            continue
        serie = df_hist.set_index('Mes')[col_dem].astype(float)
        # Calcular pronóstico comenzando desde el mes actual
        pron_dem = calcular_pronostico_descomposicion(serie, n_periodos)
        # Ajustar índice para comenzar desde el mes actual
        pron_dem.index = pd.date_range(mes_actual, periods=n_periodos, freq='MS')
        precio = precios.get(prod, 3.5)
        pron_ven = pron_dem * precio
        resultados[f'Pronostico_Demanda_{prod}'] = pron_dem
        resultados[f'Pronostico_Ventas_{prod}'] = pron_ven

    if not resultados:
        return pd.DataFrame()

    df_pron = pd.DataFrame(resultados)
    df_pron.index.name = 'Mes'
    df_pron = df_pron.reset_index()
    guardar_pronosticos(df_pron)
    return df_pron


# ─────────────────────────────────────────────
# PLAN AGREGADO DE PRODUCCIÓN (PAP)
# ─────────────────────────────────────────────

def dias_habiles_mes(fecha):
    """Días hábiles (lunes-sábado) en un mes dado."""
    _, total = calendar.monthrange(fecha.year, fecha.month)
    dias = 0
    for d in range(1, total + 1):
        wd = date(fecha.year, fecha.month, d).weekday()
        if wd < 6:  # lunes a sábado
            dias += 1
    return dias


def calcular_pap_producto(nombre_prod, df_dem, df_pron, operarios_data, inv_inicial, n_meses=3, modo='produccion', fecha_actual=None):
    
    """
    Calcula PAP para un producto dado.
    Retorna DataFrame con columnas: Mes, Demanda, Dias, Unidades_por_operario,
    Operarios_requeridos, Operarios_actuales, Operarios_contratados,
    Operarios_despedidos, Operarios_utilizados, Unidades_producidas,
    Unidades_disponibles, Inventario_final, Costo_contratar, Costo_despedir,
    Costo_mano_obra, Costo_almacenamiento, Costo_total
    
    Args:
        modo: 'produccion' o 'prueba' (default 'produccion')
        fecha_actual: fecha actual para modo prueba (None para producción)
    """
    
    col_dem = f'Demanda_{nombre_prod}'

    if modo == 'prueba' and fecha_actual:
        mes_inicio = pd.Timestamp(fecha_actual).replace(day=1)
    else:
        hoy = pd.Timestamp.now().normalize()
        mes_inicio = hoy.replace(day=1)

    fechas = pd.date_range(mes_inicio, periods=n_meses, freq='MS')

    prod_por_op = 3  # unidades por operario por día (8h jornada)
    op_actuales_ini = int(operarios_data['operarios'])
    costo_contratar = float(operarios_data['costo_contratar'])
    costo_despedir = float(operarios_data['costo_despedir'])
    costo_almacen = float(operarios_data['costo_almacenamiento'])
    costo_hora_normal = float(operarios_data['costo_hora_normal'])
    jornada = float(operarios_data['jornada_normal'])

    # ── Calcular demanda promedio y unidades/operario promedio del horizonte ──
    # para determinar Operarios Requeridos de forma constante en todo el horizonte
    demandas_horizonte = []
    unid_por_op_horizonte = []
    for fecha in fechas:
        # Días naturales del mes
        dias_nat = calendar.monthrange(fecha.year, fecha.month)[1]
        unid_op = dias_nat * prod_por_op
        unid_por_op_horizonte.append(unid_op)

        col_pron = f'Pronostico_Demanda_{nombre_prod}'
        dem_pron = None
        dem_real = None
        if col_pron in df_pron.columns:
            fila_pron = df_pron[df_pron['Mes'] == fecha]
            if not fila_pron.empty:
                dem_pron = float(fila_pron[col_pron].values[0])
        if col_dem in df_dem.columns:
            fila_real = df_dem[df_dem['Mes'] == fecha]
            if not fila_real.empty:
                dem_real = float(fila_real[col_dem].values[0])

        if dem_real is not None and dem_pron is not None:
            demanda = max(dem_real, dem_pron)
        elif dem_real is not None:
            demanda = dem_real
        elif dem_pron is not None:
            demanda = dem_pron
        else:
            demanda = 0
        demandas_horizonte.append(math.ceil(demanda))

    dem_promedio = sum(demandas_horizonte) / len(demandas_horizonte) if demandas_horizonte else 0
    unid_op_promedio = sum(unid_por_op_horizonte) / len(unid_por_op_horizonte) if unid_por_op_horizonte else 1

    # Operarios requeridos fijos para todo el horizonte (basado en promedios)
    op_requeridos_fijo = math.ceil(dem_promedio / unid_op_promedio) if unid_op_promedio > 0 else 1
    op_requeridos_fijo = max(op_requeridos_fijo, 1)

    filas = []
    inv = inv_inicial
    op_prev = op_actuales_ini

    for idx, fecha in enumerate(fechas):
        # Días naturales del mes
        dias_nat = calendar.monthrange(fecha.year, fecha.month)[1]
        unid_por_op = dias_nat * prod_por_op

        demanda = demandas_horizonte[idx]

        # Operarios: usar el valor fijo calculado por promedios del horizonte
        op_requeridos = op_requeridos_fijo
        op_contratados = max(op_requeridos - op_prev, 0)
        op_despedidos = max(op_prev - op_requeridos, 0)
        op_actuales = op_prev + op_contratados - op_despedidos
        op_utilizados = op_actuales

        unidades_producidas = op_utilizados * unid_por_op
        unidades_disponibles = inv + unidades_producidas
        inv_final = max(unidades_disponibles - demanda, 0)

        c_contratar = op_contratados * costo_contratar
        c_despedir = op_despedidos * costo_despedir
        c_mano_obra = op_utilizados * dias_nat * jornada * costo_hora_normal
        c_almacen = inv_final * costo_almacen
        c_total = c_contratar + c_despedir + c_mano_obra + c_almacen

        filas.append({
            'Mes': fecha,
            'Demanda': demanda,
            'Dias': dias_nat,
            'Unidades_por_operario': unid_por_op,
            'Operarios_requeridos': op_requeridos,
            'Operarios_actuales': op_actuales,
            'Operarios_contratados': op_contratados,
            'Operarios_despedidos': op_despedidos,
            'Operarios_utilizados': op_utilizados,
            'Unidades_producidas': unidades_producidas,
            'Unidades_disponibles': unidades_disponibles,
            'Inventario_final': inv_final,
            'Costo_contratar': round(c_contratar, 2),
            'Costo_despedir': round(c_despedir, 2),
            'Costo_mano_obra': round(c_mano_obra, 2),
            'Costo_almacenamiento': round(c_almacen, 2),
            'Costo_total': round(c_total, 2),
        })

        inv = inv_final
        op_prev = op_actuales

    return pd.DataFrame(filas)


def calcular_pap_todos(n_meses=3, modo='produccion', fecha_actual=None):
    """
    Calcula PAP para todos los productos.
    Retorna dict: {nombre_producto: DataFrame_PAP}
    
    Args:
        modo: 'produccion' o 'prueba' (default 'produccion')
        fecha_actual: fecha actual para modo prueba (None para producción)
    """
    df_dem = cargar_demanda()
    df_pron = cargar_pronosticos()
    df_prod = cargar_productos()
    operarios_data = cargar_operarios()
    nombres_prod = obtener_nombres_productos(df_dem)

    resultados = {}
    for prod in nombres_prod:
        # Inventario inicial del producto
        inv_ini = 25  # default
        precio_produccion = 3.5  # default
        for _, row in df_prod.iterrows():
            nombre_completo = f"{row['Nombre']} {int(row['Tamaño (g)'])} g"
            if nombre_completo == prod:
                inv_ini = int(row.get('Inventario', 25))
                precio_produccion = float(row.get('Precio Unitario ($)', 3.5))
                break
        df_pap = calcular_pap_producto(prod, df_dem, df_pron, operarios_data, inv_ini, n_meses, modo, fecha_actual)
        # Agregar precio de producción
        df_pap['Precio_Produccion'] = precio_produccion
        resultados[prod] = df_pap

    # Guardar PAP consolidado
    filas_pap = []
    for prod, df_pap in resultados.items():
        df_pap['Producto'] = prod
        filas_pap.append(df_pap)
    if filas_pap:
        df_pap_total = pd.concat(filas_pap, ignore_index=True)
        guardar_pap(df_pap_total)

    return resultados


def resumen_pap(pap_dict):
    """
    Genera resumen del PAP con todos los indicadores requeridos.
    Incluye: Unidades por operario, Operarios requeridos, Operarios contratados,
    Operarios despedidos, Unidades producidas, Unidades disponibles,
    Inventario final, Costo de contratar, Costo de despedir, Costo mano de obra,
    Costo por mantener inventario, Costo total, Costo por X meses.
    """
    resumen = []
    for prod, df in pap_dict.items():
        precio_prod = df['Precio_Produccion'].iloc[0] if 'Precio_Produccion' in df.columns else 3.5
        
        # Calcular unidades por operario promedio
        total_unidades = int(df['Unidades_producidas'].sum())
        total_operarios = int(df['Operarios_utilizados'].sum())
        unidades_por_operario = total_unidades / total_operarios if total_operarios > 0 else 0
        
        resumen.append({
            'Producto': prod,
            'Precio_Produccion': precio_prod,
            'Unidades_Por_Operario': round(unidades_por_operario, 2),
            'Operarios_Requeridos_Max': int(df['Operarios_requeridos'].max()),
            'Operarios_Contratados_Total': int(df['Operarios_contratados'].sum()),
            'Operarios_Despeditos_Total': int(df['Operarios_despedidos'].sum()),
            'Unidades_Producidas': total_unidades,
            'Unidades_Disponibles': int(df['Unidades_disponibles'].sum()),
            'Inventario_Final': int(df['Inventario_final'].iloc[-1]),
            'Costo_Contratar': round(df['Costo_contratar'].sum(), 2),
            'Costo_Despedit': round(df['Costo_despedir'].sum(), 2),
            'Costo_Mano_Obra': round(df['Costo_mano_obra'].sum(), 2),
            'Costo_Mantener_Inventario': round(df['Costo_almacenamiento'].sum(), 2),
            'Costo_Total': round(df['Costo_total'].sum(), 2),
        })
    return pd.DataFrame(resumen)
