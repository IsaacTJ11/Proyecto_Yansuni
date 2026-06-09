"""Initialize CSV data files from the original Excel data."""
import pandas as pd
import csv
import os

EXCEL_PATH = '/mnt/user-data/uploads/Proyecto_Cacao.xlsx'
DATA_DIR = os.path.dirname(__file__)

def init_csv():
    # 1. Demand data
    df_dem = pd.read_excel(EXCEL_PATH, sheet_name='Demanda', header=0)
    df_dem = df_dem.dropna(subset=['Mes'])
    # Keep only rows with actual dates (the 41 real rows)
    df_dem = df_dem[df_dem['Mes'].notna() & (df_dem['Mes'].apply(lambda x: hasattr(x, 'year')))]
    df_dem['Mes'] = pd.to_datetime(df_dem['Mes'])
    df_dem = df_dem[df_dem['Mes'] >= '2023-01-01']
    df_dem = df_dem.fillna(0)
    dem_path = os.path.join(DATA_DIR, 'demanda.csv')
    df_dem.to_csv(dem_path, index=False, date_format='%Y-%m-%d')
    print(f"demanda.csv: {len(df_dem)} rows")

    # 2. Products
    df_prod = pd.read_excel(EXCEL_PATH, sheet_name='Productos e insumos', header=0)
    prod_path = os.path.join(DATA_DIR, 'productos.csv')
    df_prod.to_csv(prod_path, index=False)
    print(f"productos.csv: {len(df_prod)} rows")

    # 3. Workers and costs
    df_op = pd.read_excel(EXCEL_PATH, sheet_name='Operarios y costos', header=None)
    op_data = {
        'operarios': int(df_op.iloc[0,1]),
        'costo_contratar': float(df_op.iloc[1,1]),
        'costo_despedir': float(df_op.iloc[2,1]),
        'costo_almacenamiento': float(df_op.iloc[3,1]),
        'costo_hora_extra': float(df_op.iloc[4,1]),
        'costo_hora_normal': float(df_op.iloc[5,1]),
        'jornada_normal': float(df_op.iloc[6,1]),
    }
    op_path = os.path.join(DATA_DIR, 'operarios.csv')
    pd.DataFrame([op_data]).to_csv(op_path, index=False)
    print(f"operarios.csv: {op_data}")

    # 4. Inventory of inputs
    df_inv = pd.read_excel(EXCEL_PATH, sheet_name='Inventario de insumos', header=0)
    inv_path = os.path.join(DATA_DIR, 'inventario_insumos.csv')
    df_inv.to_csv(inv_path, index=False)
    print(f"inventario_insumos.csv: {len(df_inv)} rows")

    print("All CSVs initialized!")

if __name__ == '__main__':
    init_csv()
