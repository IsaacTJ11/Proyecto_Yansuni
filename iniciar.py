"""
iniciar.py - Script de inicio para ASOPRIABET Aromas del Yasuní
Sistema de Planificación y Control de la Producción
================================================================
INSTRUCCIONES:
1. Instalar dependencias:  pip install flask pandas numpy matplotlib scipy
2. Ejecutar este script:   python iniciar.py
3. Abrir en navegador:     http://localhost:5050
================================================================
"""
import os
import sys
import subprocess
import webbrowser
import threading
import time

def check_dependencies():
    deps = ['flask', 'pandas', 'numpy', 'matplotlib', 'scipy']
    missing = []
    for dep in deps:
        try:
            __import__(dep)
        except ImportError:
            missing.append(dep)
    if missing:
        print(f"Instalando dependencias faltantes: {', '.join(missing)}")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing)

def init_data():
    """Inicializa los datos desde el Excel si es necesario."""
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    if not os.path.exists(os.path.join(data_dir, 'demanda.csv')):
        print("Inicializando datos desde Excel...")
        sys.path.insert(0, os.path.dirname(__file__))
        from data.init_data import init_csv
        init_csv()

def open_browser():
    """Abre el navegador después de que el servidor inicie."""
    time.sleep(1.5)
    webbrowser.open('http://localhost:5050')

if __name__ == '__main__':
    print("=" * 60)
    print("  ASOPRIABET – Aromas del Yasuní")
    print("  Sistema de Planificación y Control de la Producción")
    print("=" * 60)

    check_dependencies()

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    init_data()

    # Calcular pronóstico inicial si no existe
    from calculos import ejecutar_pronostico_completo
    if not os.path.exists(os.path.join('data', 'pronosticos.csv')):
        print("Calculando pronóstico inicial (puede tomar unos segundos)...")
        ejecutar_pronostico_completo(12)
        print("¡Pronóstico calculado!")

    print("\n✅ Servidor iniciado en http://localhost:5050")
    print("   Presione Ctrl+C para detener\n")

    threading.Thread(target=open_browser, daemon=True).start()

    from app import app
    app.run(debug=False, host='0.0.0.0', port=5050)
