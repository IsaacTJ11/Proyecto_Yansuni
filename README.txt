═══════════════════════════════════════════════════════════════════
  ASOPRIABET – Aromas del Yasuní
  Sistema de Planificación y Control de la Producción
═══════════════════════════════════════════════════════════════════

ESTRUCTURA DEL PROYECTO:
  iniciar.py          → Script de inicio (ejecutar este)
  app.py              → Servidor Flask (rutas y gráficos)
  calculos.py         → Cálculos: pronóstico y PAP
  data/
    demanda.csv       → Datos históricos de demanda y ventas
    productos.csv     → Catálogo de productos e insumos
    operarios.csv     → Datos de operarios y costos
    inventario_insumos.csv → Inventario de materia prima
    pronosticos.csv   → Pronósticos calculados (se genera automáticamente)
    pap.csv           → PAP calculado (se genera automáticamente)
    init_data.py      → Script de inicialización desde Excel
  static/img/         → Logo y recursos visuales
  templates/          → HTML del dashboard

CÓMO USAR:
  1. Instalar Python 3.8+
  2. Instalar dependencias:
        pip install flask pandas numpy matplotlib scipy
  3. Ejecutar:
        python iniciar.py
  4. Se abrirá automáticamente en: http://localhost:5050

FUNCIONALIDADES:
  ✅ Dashboard principal con KPIs y gráficos
  ✅ Pronóstico de demanda (descomposición estacional, 3/6/12 meses)
  ✅ Pronóstico de ventas
  ✅ Plan Agregado de Producción (PAP) por producto
  ✅ Filtro por producto en todas las vistas
  ✅ Modificar demanda del mes actual (popup)
  ✅ Agregar nuevos productos (popup)
  ✅ Modificar operarios y costos (popup)
  ✅ Tablas y gráficos exportables visualmente
  ⏳ PMP, MRP, Stock de Seguridad, Inventarios (próximamente)

NOTAS:
  - Los datos se almacenan en CSV (carpeta data/)
  - El pronóstico se recalcula manualmente con el botón "Recalcular"
  - El PAP incluye datos reales del último mes si superan al pronóstico
  - Los operarios trabajan en paralelo por producto
═══════════════════════════════════════════════════════════════════
