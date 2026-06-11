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


def calcular_pronostico_estacional(serie, n_periodos=3):

    serie = serie.copy()

    # ==========================================
    # BUSCAR PRIMER DATO REAL
    # ==========================================

    primer_idx = None

    for i, valor in enumerate(serie.values):

        if valor > 0:
            primer_idx = i
            break

    if primer_idx is None:
        raise ValueError(
            "La serie contiene únicamente ceros."
        )

    # ==========================================
    # SERIE PARA CÁLCULOS
    # ==========================================

    serie_calculo = serie.iloc[primer_idx:]

    # ==========================================
    # PROMEDIOS MENSUALES
    # ==========================================

    promedios_mes = {}

    for mes in range(1, 13):

        datos_mes = serie_calculo[
            serie_calculo.index.month == mes
        ]

        if len(datos_mes) > 0:

            promedios_mes[mes] = (
                datos_mes.mean()
            )

    # ==========================================
    # PROMEDIO GLOBAL
    # ==========================================

    promedio_global = np.mean(
        list(promedios_mes.values())
    )

    # ==========================================
    # IE
    # ==========================================

    ie = {}

    for mes in range(1, 13):

        if mes in promedios_mes:

            ie[mes] = (
                promedios_mes[mes]
                / promedio_global
            )

        else:

            ie[mes] = 1.0

    # ==========================================
    # IE AJUSTADO
    # Excel:
    # IE_Ajustado = IE / SUM(IE) * 12
    # ==========================================

    suma_ie = sum(ie.values())

    estacional = {}

    for mes in range(1, 13):

        estacional[mes] = (
            ie[mes]
            / suma_ie
            * 12
        )

    # ==========================================
    # DD
    # ==========================================

    desest = pd.Series(

        [

            round(
                valor
                / estacional[fecha.month],
                0
            )

            for fecha, valor
            in serie_calculo.items()

        ],

        index=serie_calculo.index

    )

    # ==========================================
    # REGRESIÓN
    # t = 1,2,3,...
    # ==========================================

    x_reg = np.arange(
        1,
        len(desest) + 1
    )

    pendiente, intercepto = np.polyfit(

        x_reg,
        desest.values,
        1

    )

    # ==========================================
    # FECHAS FUTURAS
    # ==========================================

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

        # Continúa secuencia Excel

        t_reg = (
            len(desest)
            + i
            + 1
        )

        T = roundup_excel(

            intercepto
            + pendiente * t_reg

        )

        Ft = roundup_excel(

            T
            * estacional[fecha.month]

        )

        resultados.append(

            max(Ft, 0)

        )

    pronostico = pd.Series(

        resultados,

        index=fechas_fut

    )

    # ==========================================
    # TABLA DETALLADA
    # ==========================================

    filas = []

    for t_abs, (fecha, demanda) in enumerate(
        serie.items()
    ):

        # ------------------------------
        # Ceros iniciales
        # ------------------------------

        if t_abs < primer_idx:

            filas.append({

                "Fecha":
                    fecha.strftime("%Y-%m"),

                "Demanda/Ventas":
                    demanda,

                "Indice Estacionalidad":
                    np.nan,

                "Demanda Desestacionalizada":
                    np.nan,

                "Periodo (t)":
                    np.nan,

                "T":
                    np.nan,

                "Ft":
                    np.nan,

                "Tipo":
                    "REAL"

            })

            continue

        # ------------------------------
        # t como Excel
        # ------------------------------

        t_excel = (
            t_abs
            - primer_idx
            + 1
        )

        ie_mes = estacional[
            fecha.month
        ]

        dd = round(

            demanda
            / ie_mes,

            0

        )

        T = roundup_excel(

            intercepto
            + pendiente * t_excel

        )

        Ft = roundup_excel(

            T
            * ie_mes

        )

        filas.append({

            "Fecha":
                fecha.strftime("%Y-%m"),

            "Demanda/Ventas":
                demanda,

            "Indice Estacionalidad":
                round(
                    ie_mes,
                    4
                ),

            "Demanda Desestacionalizada":
                dd,

            "Periodo (t)":
                t_excel,

            "T":
                T,

            "Ft":
                Ft,

            "Tipo":
                "REAL"

        })

    # ==========================================
    # FILAS PRONÓSTICO
    # ==========================================

    for i, fecha in enumerate(
        fechas_fut
    ):

        t_excel = (
            len(desest)
            + i
            + 1
        )

        ie_mes = estacional[
            fecha.month
        ]

        T = roundup_excel(

            intercepto
            + pendiente * t_excel

        )

        Ft = roundup_excel(

            T
            * ie_mes

        )

        filas.append({

            "Fecha":
                fecha.strftime("%Y-%m"),

            "Demanda/Ventas":
                None,

            "Indice Estacionalidad":
                round(
                    ie_mes,
                    4
                ),

            "Demanda Desestacionalizada":
                None,

            "Periodo (t)":
                t_excel,

            "T":
                T,

            "Ft":
                Ft,

            "Tipo":
                "PRONOSTICO"

        })

    tabla = pd.DataFrame(
        filas
    )

    return (
        pronostico,
        estacional,
        tabla,
        promedios_mes,
        promedio_global,
        pendiente,
        intercepto
    )

# ==================================================
# DATOS DE EJEMPLO
# ==================================================

valores = [

    0,0,0,0,0,
    0,0,0,0,0,

    500,700,

    100,100,100,100,
    100,100,100,100,
    50,100,500,700,

    200,200,150,120,
    100,100,250,300,
    300,100,450,700,

    75,150

]

fechas = pd.date_range(
    start="2023-01-01",
    periods=len(valores),
    freq="MS"
)

serie = pd.Series(
    valores,
    index=fechas
)

# ==================================================
# CALCULO
# ==================================================

(
    pronostico,
    ie,
    tabla,
    promedios_mes,
    promedio_global,
    pendiente,
    intercepto
) = calcular_pronostico_estacional(
    serie,
    n_periodos=3
)

# ==================================================
# TABLA COMPLETA
# ==================================================

pd.set_option(
    "display.max_rows",
    None
)

pd.set_option(
    "display.max_columns",
    None
)

pd.set_option(
    "display.width",
    250
)

print("\nTABLA DE CALCULO")
print("-" * 180)

print(
    tabla.to_string(
        index=False
    )
)