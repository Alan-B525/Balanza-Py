"""Exportador de calibraciones a un único CSV.

Escanea el directorio `CALIBRATIONS_DIR` (de `config.py`) en busca de archivos JSON
por serial/composite y los concatena en `calibrations.csv` en el mismo
directorio.

Formato CSV (cabecera): serial,composite,weight,reading,timestamp
- serial: puede estar vacío ("") si el archivo se identificó por composite solamente
- composite: puede estar vacío si la calibración estaba guardada por serial

Uso:
    python scripts/export_calibrations_to_csv.py

El script es idempotente: sobrescribe `calibrations.csv` con la vista actual.
"""

import os
import json
import csv
from config import CALIBRATIONS_DIR


def find_json_files(dirpath):
    for fn in os.listdir(dirpath):
        if not fn.lower().endswith('.json'):
            continue
        yield os.path.join(dirpath, fn)


def infer_target_from_filename(fn):
    """Devuelve (serial, composite) inferidos a partir del nombre de archivo.
    Ejemplos:
      - 12345.json -> serial='12345', composite=None
      - node1_ch1.json -> serial=None, composite='node1:ch1' (si contiene '_')
    """
    base = os.path.basename(fn)
    name = os.path.splitext(base)[0]
    # Heurística simple: si contiene ':' o '_', tratar como composite
    if ':' in name:
        return (None, name)
    if '_' in name:
        parts = name.split('_')
        if len(parts) >= 2:
            # node_ch -> node:ch
            return (None, f"{parts[0]}:{parts[1]}")
    # otherwise assume serial
    return (name, None)


def load_json_points(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return []
    pts = []
    if isinstance(data, list):
        for it in data:
            if not isinstance(it, dict):
                continue
            w = it.get('weight')
            r = it.get('reading')
            ts = it.get('timestamp', '')
            try:
                w = float(w)
                r = float(r)
            except Exception:
                continue
            pts.append({'weight': w, 'reading': r, 'timestamp': ts})
    return pts


def main():
    if not os.path.exists(CALIBRATIONS_DIR):
        print(f"Directorio de calibraciones no existe: {CALIBRATIONS_DIR}")
        return

    out_path = os.path.join(CALIBRATIONS_DIR, 'calibrations.csv')
    rows = []

    for pj in find_json_files(CALIBRATIONS_DIR):
        serial, composite = infer_target_from_filename(pj)
        points = load_json_points(pj)
        for p in points:
            rows.append({
                'serial': serial or '',
                'composite': composite or '',
                'weight': p['weight'],
                'reading': p['reading'],
                'timestamp': p.get('timestamp', '')
            })

    # Escribir CSV
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['serial', 'composite', 'weight', 'reading', 'timestamp'])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Exportadas {len(rows)} filas a {out_path}")


if __name__ == '__main__':
    main()
