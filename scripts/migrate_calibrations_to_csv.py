#!/usr/bin/env python3
"""scripts/migrate_calibrations_to_csv.py

Lee todos los archivos JSON en la carpeta `calibrations/` y genera/actualiza
`curvas_celdas.csv`. El formato de salida es:

Carga Real,<serial1>,<serial2>,...
<peso>,<lectura_serial1>,<lectura_serial2>,...

Si un peso no tiene lectura para un serial, la celda queda vacía.
"""
import os
import json
import csv

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB_DIR = os.path.join(HERE, "calibrations")
CSV_PATH = os.path.join(CALIB_DIR, "curvas_celdas.csv")

def read_json_calibs(calib_dir):
    data = {}
    for name in os.listdir(calib_dir):
        if not name.lower().endswith('.json'):
            continue
        serial = os.path.splitext(name)[0]
        path = os.path.join(calib_dir, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                arr = json.load(f)
            mapping = {}
            for item in arr:
                try:
                    w = float(item.get('weight'))
                    r = float(item.get('reading'))
                    mapping[w] = r
                except Exception:
                    continue
            if mapping:
                data[serial] = mapping
        except Exception as e:
            print(f"Error leyendo {path}: {e}")
    return data

def write_csv(path, weights, serials_map):
    serials = sorted(serials_map.keys(), key=lambda x: str(x))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Carga Real"] + serials)
        for w in weights:
            row = [("%.6g" % w)]
            for s in serials:
                val = serials_map.get(s, {}).get(w)
                row.append('' if val is None else str(val))
            writer.writerow(row)

def migrate():
    if not os.path.isdir(CALIB_DIR):
        print(f"Directorio no existe: {CALIB_DIR}")
        return
    serials_map = read_json_calibs(CALIB_DIR)
    if not serials_map:
        print("No se encontraron archivos JSON de calibración.")
        return

    # union de pesos
    weights = set()
    for m in serials_map.values():
        weights.update(m.keys())
    weights = sorted(weights)

    # Normalize maps: ensure keys exist with None when missing
    for s in serials_map:
        for w in weights:
            serials_map[s].setdefault(w, None)

    write_csv(CSV_PATH, weights, serials_map)
    print(f"Migración completada: {CSV_PATH}")

if __name__ == '__main__':
    migrate()
