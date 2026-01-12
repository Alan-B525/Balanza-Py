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

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    from scipy.interpolate import interp1d, UnivariateSpline, CubicSpline
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

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
    
    def __init__(self, data_processor, celda_id=None, serial=None):
        self.dp = data_processor
        self.points: List[CalibrationPoint] = []
        self._cancel = False
        self.celda_id = celda_id
        self.serial = serial
        self._calib_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "calibrations")
        if not os.path.exists(self._calib_dir):
            os.makedirs(self._calib_dir)
        # Cargar puntos si hay celda y serial
        if celda_id and serial:
            self.load_points()
    def _get_calib_path(self):
        if self.celda_id and self.serial:
            return os.path.join(self._calib_dir, f"celda_{self.celda_id}_serie_{self.serial}.json")
        return None

    def save_points(self):
        path = self._get_calib_path()
        if not path:
            return
        data = [{"weight": p.weight, "reading": p.reading, "timestamp": p.timestamp} for p in self.points]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_points(self):
        path = self._get_calib_path()
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.points = [CalibrationPoint(**d) for d in data]
        except Exception:
            self.points = []

    def clear_points(self):
        self.points = []

    def add_point(self, weight: float, reading: float):
        self.points.append(CalibrationPoint(weight, reading, time.time()))

    def remove_point(self, index: int):
        if 0 <= index < len(self.points):
            self.points.pop(index)

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
        
        # Ordenar arrays por X para interpolaciones correctas
        sorted_indices = np.argsort(x_data)
        x_data = x_data[sorted_indices]
        y_data = y_data[sorted_indices]
        
        result = {"method": method, "valid": False}
        
        try:
            if "Lineal" in method:
                if len(x_data) >= 2:
                    z = np.polyfit(x_data, y_data, 1) # [slope, offset]
                    result.update({
                        "valid": True,
                        "slope": float(z[0]),
                        "offset": float(z[1]),
                        "eq": f"y = {z[0]:.4f}x + {z[1]:.2f}"
                    })
            
            elif "Polinomio" in method:
                degree = 2 if "Grado 2" in method else 3
                if len(x_data) >= (degree + 1):
                    z = np.polyfit(x_data, y_data, degree)
                    result.update({
                        "valid": True,
                        "coefficients": z.tolist(), # [c_n, ..., c_0]
                        "degree": degree
                    })
            
            # Nota: Splines e Interpolación no generan coeficientes simples para guardar igual,
            # pero el Manager podría validar que son calculables.
            
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

        # Guardar puntos al aplicar calibración
        self.save_points()

        method = model.get("method", "")

        if method == "segments":
            # Interpolación por segmentos - guardar puntos
            points = model.get("points", [])
            if points and hasattr(self.dp, 'set_calibration_segments'):
                self.dp.set_calibration_segments(points)
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

