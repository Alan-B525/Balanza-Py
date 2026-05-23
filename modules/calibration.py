# -*- coding: utf-8 -*-
"""
calibration.py - Módulo de Calibración Avanzado

Implementa:
- Gestión de puntos de calibración (Peso vs Lectura)
- Múltiples modelos de ajuste: Lineal, Polinómico, Interpolación, Spline.
- Integración con DataProcessor para captura de valores.
"""

import time
import statistics
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
import csv

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    from scipy.interpolate import interp1d, UnivariateSpline, CubicSpline  # type: ignore
    SCIPY_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    SCIPY_AVAILABLE = False
    interp1d = None
    UnivariateSpline = None
    CubicSpline = None

@dataclass
class CalibrationPoint:
    weight: float
    reading: float
    timestamp: float = 0.0

@dataclass
class CalibrationSession:
    points: List[CalibrationPoint] = field(default_factory=list)
    method: str = "Lineal"
    unit: str = "Raw"
    coefficients: Dict[str, Any] = field(default_factory=dict)
    
class CalibrationManager:
    """
    Gestor de calibración avanzado.
    Permite capturar puntos, gestionar sesión y calcular curvas.
    """
    
    UNIFIED_CSV_NAME = "curva_celda.csv"

    def __init__(self, data_processor, celda_id=None, serial=None):
        self.dp = data_processor
        self.points: List[CalibrationPoint] = []
        self._cancel = False
        self.celda_id = celda_id
        self.serial = serial
        from config import CALIBRATIONS_DIR
        self._calib_dir = CALIBRATIONS_DIR
        if not os.path.exists(self._calib_dir):
            os.makedirs(self._calib_dir)
        # Cargar puntos si hay serial (aunque celda_id sea None)
        if serial and str(serial).strip():
            self.load_points()
        else:
            self._log_to_file("Advertencia: serial no definido o vacío, no se cargará archivo de calibración.")
    def _get_csv_path(self):
        return os.path.join(self._calib_dir, self.UNIFIED_CSV_NAME)

    def save_points(self):
        # Save into unified CSV. If CSV exists, merge columns; else create new CSV.
        # Determine key to use for CSV column: prefer serial, else try dp.nodos_config, else use normalized celda_id
        serial_key = None
        if self.serial and str(self.serial).strip():
            serial_key = str(self.serial).strip()
        else:
            # try resolve from dp.nodos_config if available
            try:
                if self.celda_id is not None and hasattr(self.dp, 'nodos_config'):
                    internal = self.celda_id
                    if isinstance(internal, (int, float)):
                        internal = f"celda_{int(internal)}"
                    elif isinstance(internal, str) and not internal.startswith("celda_"):
                        internal = f"celda_{internal}"
                    cfg = self.dp.nodos_config.get(internal, {})
                    serial_candidate = cfg.get('serial') if isinstance(cfg, dict) else None
                    if serial_candidate:
                        serial_key = str(serial_candidate)
            except Exception:
                pass

        if not serial_key:
            # fallback to using celda_id as column header so we can save even when disconnected
            if self.celda_id is not None:
                internal = self.celda_id
                if isinstance(internal, (int, float)):
                    serial_key = f"celda_{int(internal)}"
                else:
                    serial_key = str(internal)
            else:
                serial_key = "unknown"
            self._log_to_file(f"Advertencia: serial no disponible, usando clave alternativa '{serial_key}' para guardar calibración")

        csv_path = self._get_csv_path()
        # Build mapping weight->reading for current points
        current_map = {float(p.weight): float(p.reading) for p in self.points}

        # Read existing CSV (if any)
        if os.path.exists(csv_path):
            weights, serials_map = self._read_csv(csv_path)
        else:
            weights, serials_map = [], {}

        # Merge weights: union of existing and current
        new_weights = sorted(set(weights) | set(current_map.keys()))

        # Ensure serials_map has entries for the target key
        if serial_key not in serials_map:
            serials_map[serial_key] = {}

        # Update the readings for this serial
        for w in new_weights:
            if w in current_map:
                serials_map[serial_key][w] = current_map[w]
            else:
                # Explicitly clear value for this serial when point missing (delete case)
                serials_map[serial_key][w] = None

        # Prune weights that have no readings across any serials
        final_weights = []
        for w in new_weights:
            any_val = False
            for s in serials_map:
                if serials_map[s].get(w) is not None:
                    any_val = True
                    break
            if any_val:
                final_weights.append(w)
        new_weights = final_weights

        # Write back CSV
        self._write_csv(csv_path, new_weights, serials_map)
        self._log_to_file(f"Guardada calibración en CSV: {csv_path} para clave={serial_key}")

    def load_points(self):
        csv_path = self._get_csv_path()
        loaded: List[CalibrationPoint] = []

        # Try CSV first
        try:
            if os.path.exists(csv_path):
                weights, serials_map = self._read_csv(csv_path)
                # Try several keys: explicit serial, normalized celda id
                candidates = []
                if self.serial and str(self.serial).strip():
                    candidates.append(str(self.serial).strip())
                if self.celda_id is not None:
                    internal = self.celda_id
                    if isinstance(internal, (int, float)):
                        candidates.append(f"celda_{int(internal)}")
                    else:
                        candidates.append(str(internal))

                found = False
                for key in candidates:
                    if key in serials_map:
                        serial_map = serials_map.get(key, {})
                        tmp_loaded: List[CalibrationPoint] = []
                        for w in weights:
                            r = serial_map.get(w)
                            if r is None:
                                continue
                            tmp_loaded.append(CalibrationPoint(float(w), float(r), time.time()))
                        # Only accept this key if we actually found points for it
                        if tmp_loaded:
                            self.points = tmp_loaded
                            self._log_to_file(f"Cargados {len(self.points)} puntos de calibración desde CSV: {csv_path} (clave={key})")
                            found = True
                            break
                csv_loaded = found
            else:
                csv_loaded = False
        except Exception as e:
            self._log_to_file(f"Error leyendo CSV de calibración: {e}")
            csv_loaded = False

        # If CSV not loaded, nothing to load (we no longer use per-serial JSON files)
        if not csv_loaded:
            self._log_to_file(f"No se encontró CSV de calibración ({csv_path}) o serial no definido; no se cargaron puntos.")
            self.points = []

        # Si cargamos puntos, guardar en CSV (migración) y luego auto-aplicar
        try:
            if self.points:
                try:
                    # Persistir puntos cargados (migración JSON->CSV o asegurar existencia en CSV)
                    self.save_points()
                except Exception as e:
                    self._log_to_file(f"Fallo guardando puntos después de cargar: {e}")

            if self.points and hasattr(self.dp, 'set_calibration_segments'):
                pts = self.get_points()  # lista de (weight, reading)
                composite = None
                try:
                    if self.celda_id is not None:
                        internal = self.celda_id
                        if isinstance(internal, (int, float)):
                            internal = f"celda_{int(internal)}"
                        elif isinstance(internal, str) and not internal.startswith("celda_"):
                            internal = f"celda_{internal}"
                        if hasattr(self.dp, 'nodos_config') and internal in self.dp.nodos_config:
                            cfg = self.dp.nodos_config.get(internal, {})
                            nid = cfg.get('id')
                            ch = cfg.get('ch', 'ch1')
                            if nid:
                                composite = f"{nid}:{ch}"
                except Exception:
                    composite = None

                try:
                    self.dp.set_calibration_segments(pts, serial=self.serial, composite=composite)
                    self._log_to_file(f"Auto-aplicada calibración a serial={self.serial} composite={composite}")
                except Exception as e:
                    self._log_to_file(f"Fallo auto-aplicando calibración: {e}")
        except Exception:
            pass
    def _log_to_file(self, message):
        try:
            from . import logger
            logger.info(f"[CALIBRATION] {message}")
        except Exception:
            try:
                import datetime, os
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'log.log')
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(f"[{timestamp}] {message}\n")
            except Exception:
                pass

    # -----------------------
    # CSV helpers
    # -----------------------
    def _read_csv(self, path: str) -> Tuple[List[float], Dict[str, Dict[float, float]]]:
        """Lee CSV unificado de calibración y retorna (weights_list, {serial: {weight: reading}}).
        Las celdas vacías se convierten en None.
        """
        weights: List[float] = []
        serials_map: Dict[str, Dict[float, float]] = {}
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return weights, serials_map
        header = rows[0]
        # header[0] expected to be 'Carga Real'
        serials = [h.strip() for h in header[1:]]
        for s in serials:
            serials_map[s] = {}
        for row in rows[1:]:
            if not row:
                continue
            try:
                w = float(row[0])
            except Exception:
                continue
            weights.append(w)
            for idx, s in enumerate(serials, start=1):
                val = None
                if idx < len(row):
                    cell = row[idx].strip()
                    if cell != "":
                        try:
                            val = float(cell)
                        except Exception:
                            val = None
                serials_map[s][w] = val
        return weights, serials_map

    def _write_csv(self, path: str, weights: List[float], serials_map: Dict[str, Dict[float, Any]]):
        # serials order stable
        serials = sorted(serials_map.keys(), key=lambda x: str(x))
        temp_path = path + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8", newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Carga Real"] + serials)
                for w in weights:
                    row = [("%.6g" % w)]
                    for s in serials:
                        val = serials_map.get(s, {}).get(w)
                        if val is None:
                            row.append("")
                        else:
                            row.append(str(val))
                    writer.writerow(row)
            # Reemplazo atómico para evitar corrupción en caso de interrupción de escritura
            if os.path.exists(temp_path):
                os.replace(temp_path, path)
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise e

    def clear_points(self):
        self.points = []

    def add_point(self, weight: float, reading: float):
        self.points.append(CalibrationPoint(weight, reading, time.time()))
        try:
            self.save_points()
        except Exception:
            pass

    def remove_point(self, index: int):
        if 0 <= index < len(self.points):
            self.points.pop(index)
            try:
                self.save_points()
            except Exception:
                pass

    def get_points(self) -> List[Tuple[float, float]]:
        return [(p.weight, p.reading) for p in self.points]

    def cancel(self):
        self._cancel = True

    def calculate_model(self, method: str) -> Dict[str, Any]:
        """Calcula el modelo basado en los puntos actuales."""
        if not self.points or not NUMPY_AVAILABLE:
            return {}
            
        x_data = np.array([p.reading for p in self.points]) # X = Lectura
        y_data = np.array([p.weight for p in self.points])  # Y = Peso real
        
        if len(x_data) >= 2 and np.max(x_data) == np.min(x_data):
            return {"method": method, "valid": False, "error": "Todos los puntos de lectura son idénticos, no se puede calcular calibración."}

        # Ordenar arrays por X para interpolaciones correctas
        sorted_indices = np.argsort(x_data)
        x_data = x_data[sorted_indices]
        y_data = y_data[sorted_indices]
        
        result = {"method": method, "valid": False}
        
        try:
            if "Lineal" in method:
                if len(x_data) >= 2:
                    z = np.polyfit(x_data, y_data, 1) # [slope, offset]
                    slope, offset = float(z[0]), float(z[1])
                    
                    # Calcular R²
                    y_pred = slope * x_data + offset
                    y_mean = np.mean(y_data)
                    ss_tot = np.sum((y_data - y_mean) ** 2)
                    ss_res = np.sum((y_data - y_pred) ** 2)
                    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else 1.0
                    
                    result.update({
                        "valid": True,
                        "slope": slope,
                        "offset": offset,
                        "eq": f"y = {slope:.4f}x + {offset:.2f}",
                        "r_squared": float(r_squared)
                    })
            
            elif "Polinomio" in method:
                degree = 2 if "Grado 2" in method else 3
                if len(x_data) >= (degree + 1):
                    z = np.polyfit(x_data, y_data, degree)
                    
                    # Calcular R²
                    p = np.poly1d(z)
                    y_pred = p(x_data)
                    y_mean = np.mean(y_data)
                    ss_tot = np.sum((y_data - y_mean) ** 2)
                    ss_res = np.sum((y_data - y_pred) ** 2)
                    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else 1.0
                    
                    result.update({
                        "valid": True,
                        "coefficients": z.tolist(), # [c_n, ..., c_0]
                        "degree": degree,
                        "r_squared": float(r_squared)
                    })
            
        except Exception as e:
            result["error"] = str(e)
            
        return result

    def obtener_promedio_estable(self, duration: float = 2.0, interval: int = 100) -> Optional[float]:
        """
        Obtiene el promedio de la 'Suma Total Raw' durante 'duration' segundos.
        """
        self._cancel = False
        samples = []
        end_time = time.time() + duration
        sleep_sec = interval / 1000.0
        
        while time.time() < end_time:
            if self._cancel:
                return None
            val = self.dp.get_last_total_raw()
            samples.append(val)
            time.sleep(sleep_sec)
            
        if not samples:
            return 0.0
        return statistics.mean(samples)

    def apply_calibration(self, model: Dict[str, Any]):
        """Aplica la calibración al Data Processor y guarda los puntos."""
        if not model.get("valid"):
            return

        # Si el modelo contiene 'points', actualizamos self.points y guardamos.
        points = model.get("points", [])
        if points:
            try:
                # Esperamos lista de tuplas (weight, reading)
                self.points = [CalibrationPoint(float(w), float(r), time.time()) for (w, r) in points]
            except Exception:
                # Intentar invertir si vienen como (reading, weight)
                try:
                    self.points = [CalibrationPoint(float(r), float(w), time.time()) for (w, r) in points]
                except Exception:
                    pass
            try:
                self.save_points()
            except Exception as e:
                self._log_to_file(f"Error guardando puntos al aplicar calibración: {e}")

        method = "segments"

        if method == "segments":
            # Interpolación por segmentos - guardar puntos
            points = model.get("points", [])
            if points and hasattr(self.dp, 'set_calibration_segments'):
                # Intentar asociar la calibración por serial o por celda (composite id:ch)
                composite = None
                try:
                    if self.celda_id is not None:
                        # Normalizar nombre interno
                        internal = self.celda_id
                        if isinstance(internal, (int, float)):
                            internal = f"celda_{int(internal)}"
                        elif isinstance(internal, str) and not internal.startswith("celda_"):
                            internal = f"celda_{internal}"
                        # Buscar en dp.nodos_config
                        if hasattr(self.dp, 'nodos_config') and internal in self.dp.nodos_config:
                            cfg = self.dp.nodos_config.get(internal, {})
                            nid = cfg.get('id')
                            ch = cfg.get('ch', 'ch1')
                            if nid:
                                composite = f"{nid}:{ch}"
                except Exception:
                    composite = None

                try:
                    self.dp.set_calibration_segments(points, serial=self.serial, composite=composite)
                    self._log_to_file(f"Aplicada calibración segments a serial={self.serial} composite={composite}")
                except Exception:
                    # Ultimo recurso: pasar solo points
                    try:
                        self.dp.set_calibration_segments(points)
                        self._log_to_file(f"Aplicada calibración segments (fallback) sin target explícito")
                    except Exception as e:
                        self._log_to_file(f"Error aplicando calibración: {e}")
            elif points:
                # Fallback: guardar en atributo
                self.dp.calibration_segments = points
                self.dp.calibration_method = "segments"

        elif "Lineal" in method:
            slope = model.get("slope", 1.0)
            offset = model.get("offset", 0.0)
            if hasattr(self.dp, 'update_calibration'):
                self.dp.update_calibration(slope, offset)
            else:
                self.dp.system_slope = slope
                self.dp.system_offset = offset

