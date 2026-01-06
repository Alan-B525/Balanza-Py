# -*- coding: utf-8 -*-
"""
calibration.py - Módulo de Calibración para Celdas de Carga

Este módulo permite:
- Realizar ensayos de calibración con pesos patrón
- Capturar valores crudos (mV/V) y convertidos (kg)
- Generar curvas de calibración (lineal y polinómica)
- Detectar y corregir no-linealidades en el rango superior
- Exportar datos a CSV
- Guardar/cargar configuraciones de calibración

Referencia: SG-Link-200 User Manual - LORD MicroStrain
"""

import csv
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import statistics

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("[CALIBRATION] NumPy no disponible. Regresión polinómica limitada.")


@dataclass
class CalibrationPoint:
    """Punto de calibración individual."""
    peso_aplicado_kg: float          # Peso patrón aplicado
    valor_crudo_mv_v: float = 0.0    # Lectura cruda en mV/V (si disponible)
    valor_sensor_kg: float = 0.0     # Lectura del sensor en kg
    timestamp: str = ""               # Momento de la lectura
    readings_count: int = 1           # Número de lecturas promediadas
    std_dev: float = 0.0              # Desviación estándar de las lecturas
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class CalibrationSession:
    """Sesión completa de calibración para un sensor."""
    sensor_id: int
    sensor_nombre: str
    fecha_inicio: str = ""
    fecha_fin: str = ""
    puntos: List[CalibrationPoint] = field(default_factory=list)
    
    # Coeficientes de calibración calculados
    linear_slope: float = 1.0
    linear_offset: float = 0.0
    linear_r_squared: float = 0.0
    
    # Coeficientes polinómicos (para corregir no-linealidad)
    poly_coefficients: List[float] = field(default_factory=list)
    poly_degree: int = 1
    poly_r_squared: float = 0.0
    
    # Metadatos
    operador: str = ""
    notas: str = ""
    
    def __post_init__(self):
        if not self.fecha_inicio:
            self.fecha_inicio = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class CalibrationManager:
    """
    Gestor de calibración para celdas de carga.
    
    Características:
    - Puntos de calibración predefinidos: 0 a 200,000 kg en pasos de 15,000 kg
    - Captura de múltiples lecturas para promediar y reducir ruido
    - Regresión lineal y polinómica para generar curvas
    - Detección de no-linealidad en extremos
    - Exportación a CSV
    """
    
    # Puntos de calibración estándar (en kg)
    DEFAULT_CAL_POINTS = [0] + list(range(15000, 200001, 15000))  # 0, 15000, 30000, ..., 200000
    
    # Número de lecturas para promediar en cada punto
    READINGS_PER_POINT = 10
    READING_INTERVAL_S = 0.5  # Intervalo entre lecturas
    
    def __init__(self, nodos_config: Dict[str, Dict[str, Any]]):
        """
        Inicializa el gestor de calibración.
        
        Args:
            nodos_config: Configuración de nodos del sistema
        """
        self.nodos_config = nodos_config
        self.sessions: Dict[int, CalibrationSession] = {}
        self.current_session: Optional[CalibrationSession] = None
        
        # Referencia al driver para leer valores (se establece externamente)
        self._driver = None
        self._data_processor = None
        
        # Buffer de lecturas para el punto actual
        self._reading_buffer: List[float] = []
        
        # Directorio para guardar calibraciones
        self._cal_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "calibrations"
        )
        os.makedirs(self._cal_dir, exist_ok=True)
    
    def set_driver(self, driver) -> None:
        """Establece referencia al driver MSCL."""
        self._driver = driver
    
    def set_data_processor(self, processor) -> None:
        """Establece referencia al procesador de datos."""
        self._data_processor = processor
    
    def get_sensor_list(self) -> List[Dict[str, Any]]:
        """Retorna lista de sensores disponibles para calibrar."""
        sensors = []
        for nombre, cfg in self.nodos_config.items():
            sensors.append({
                "id": cfg["id"],
                "nombre": nombre,
                "channel": cfg.get("ch", "ch1")
            })
        return sensors
    
    def get_default_cal_points(self) -> List[float]:
        """Retorna los puntos de calibración predefinidos."""
        return self.DEFAULT_CAL_POINTS.copy()
    
    def start_session(self, sensor_id: int, sensor_nombre: str, 
                      operador: str = "") -> CalibrationSession:
        """
        Inicia una nueva sesión de calibración.
        
        Args:
            sensor_id: ID del nodo a calibrar
            sensor_nombre: Nombre lógico del sensor
            operador: Nombre del operario (opcional)
            
        Returns:
            Nueva sesión de calibración
        """
        session = CalibrationSession(
            sensor_id=sensor_id,
            sensor_nombre=sensor_nombre,
            operador=operador
        )
        self.current_session = session
        self.sessions[sensor_id] = session
        return session
    
    def get_current_reading(self, sensor_id: int) -> Tuple[float, float]:
        """
        Obtiene la lectura actual del sensor.
        
        Args:
            sensor_id: ID del nodo
            
        Returns:
            Tupla (valor_kg, valor_mv_v) - mV/V puede ser 0 si no está disponible
        """
        valor_kg = 0.0
        valor_mv_v = 0.0
        
        if self._data_processor:
            # Obtener valor filtrado del procesador
            filter_state = self._data_processor.get_filter_state(sensor_id)
            if filter_state and filter_state.get("ema_value") is not None:
                valor_kg = filter_state["ema_value"]
        
        # TODO: Implementar lectura de mV/V crudo si el driver lo soporta
        # Esto requiere configurar el nodo para entregar datos raw
        # Por ahora, calculamos un valor aproximado basado en sensibilidad típica
        # Sensibilidad típica de celda de carga: 2 mV/V a carga nominal
        # Si carga nominal = 50,000 kg y sensibilidad = 2 mV/V:
        # mV/V = (valor_kg / 50000) * 2
        SENSIBILIDAD_MV_V = 2.0
        CARGA_NOMINAL_KG = 50000.0
        if valor_kg != 0:
            valor_mv_v = (valor_kg / CARGA_NOMINAL_KG) * SENSIBILIDAD_MV_V
        
        return valor_kg, valor_mv_v
    
    def capture_point(self, sensor_id: int, peso_aplicado_kg: float,
                      num_readings: int = None) -> Optional[CalibrationPoint]:
        """
        Captura un punto de calibración tomando múltiples lecturas.
        
        Args:
            sensor_id: ID del nodo
            peso_aplicado_kg: Peso patrón aplicado
            num_readings: Número de lecturas a promediar (default: READINGS_PER_POINT)
            
        Returns:
            Punto de calibración capturado o None si falla
        """
        if num_readings is None:
            num_readings = self.READINGS_PER_POINT
        
        readings_kg = []
        readings_mv_v = []
        
        for i in range(num_readings):
            kg, mv_v = self.get_current_reading(sensor_id)
            readings_kg.append(kg)
            readings_mv_v.append(mv_v)
            time.sleep(self.READING_INTERVAL_S)
        
        if not readings_kg:
            return None
        
        # Calcular promedios y desviación
        avg_kg = statistics.mean(readings_kg)
        avg_mv_v = statistics.mean(readings_mv_v)
        std_dev = statistics.stdev(readings_kg) if len(readings_kg) > 1 else 0.0
        
        point = CalibrationPoint(
            peso_aplicado_kg=peso_aplicado_kg,
            valor_crudo_mv_v=round(avg_mv_v, 6),
            valor_sensor_kg=round(avg_kg, 3),
            readings_count=num_readings,
            std_dev=round(std_dev, 3)
        )
        
        # Agregar a la sesión actual
        if self.current_session and self.current_session.sensor_id == sensor_id:
            self.current_session.puntos.append(point)
        
        return point
    
    def add_manual_point(self, peso_aplicado_kg: float, valor_sensor_kg: float,
                         valor_mv_v: float = 0.0) -> Optional[CalibrationPoint]:
        """
        Agrega un punto de calibración manualmente.
        
        Args:
            peso_aplicado_kg: Peso patrón aplicado
            valor_sensor_kg: Valor leído del sensor
            valor_mv_v: Valor en mV/V (opcional)
            
        Returns:
            Punto de calibración creado
        """
        if not self.current_session:
            return None
        
        point = CalibrationPoint(
            peso_aplicado_kg=peso_aplicado_kg,
            valor_crudo_mv_v=valor_mv_v,
            valor_sensor_kg=valor_sensor_kg
        )
        self.current_session.puntos.append(point)
        return point
    
    def update_point(self, index: int, peso_aplicado_kg: float = None,
                     valor_sensor_kg: float = None, valor_mv_v: float = None) -> bool:
        """
        Actualiza un punto de calibración existente.
        
        Args:
            index: Índice del punto en la sesión
            peso_aplicado_kg: Nuevo peso aplicado (opcional)
            valor_sensor_kg: Nuevo valor sensor (opcional)
            valor_mv_v: Nuevo valor mV/V (opcional)
            
        Returns:
            True si se actualizó correctamente
        """
        if not self.current_session or index >= len(self.current_session.puntos):
            return False
        
        point = self.current_session.puntos[index]
        if peso_aplicado_kg is not None:
            point.peso_aplicado_kg = peso_aplicado_kg
        if valor_sensor_kg is not None:
            point.valor_sensor_kg = valor_sensor_kg
        if valor_mv_v is not None:
            point.valor_crudo_mv_v = valor_mv_v
        
        return True
    
    def remove_point(self, index: int) -> bool:
        """Elimina un punto de calibración por índice."""
        if not self.current_session or index >= len(self.current_session.puntos):
            return False
        del self.current_session.puntos[index]
        return True
    
    def calculate_linear_regression(self) -> Tuple[float, float, float]:
        """
        Calcula regresión lineal: valor_real = slope * valor_sensor + offset
        
        Returns:
            Tupla (slope, offset, r_squared)
        """
        if not self.current_session or len(self.current_session.puntos) < 2:
            return 1.0, 0.0, 0.0
        
        x = [p.valor_sensor_kg for p in self.current_session.puntos]
        y = [p.peso_aplicado_kg for p in self.current_session.puntos]
        
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi ** 2 for xi in x)
        sum_y2 = sum(yi ** 2 for yi in y)
        
        # Pendiente y offset
        denominator = n * sum_x2 - sum_x ** 2
        if denominator == 0:
            return 1.0, 0.0, 0.0
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        offset = (sum_y - slope * sum_x) / n
        
        # Coeficiente de determinación R²
        y_mean = sum_y / n
        ss_tot = sum((yi - y_mean) ** 2 for yi in y)
        ss_res = sum((yi - (slope * xi + offset)) ** 2 for xi, yi in zip(x, y))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        # Guardar en sesión
        self.current_session.linear_slope = round(slope, 6)
        self.current_session.linear_offset = round(offset, 3)
        self.current_session.linear_r_squared = round(r_squared, 6)
        
        return slope, offset, r_squared
    
    def calculate_polynomial_regression(self, degree: int = 2) -> Tuple[List[float], float]:
        """
        Calcula regresión polinómica para corregir no-linealidades.
        
        Args:
            degree: Grado del polinomio (2 = cuadrático, 3 = cúbico)
            
        Returns:
            Tupla (coeficientes, r_squared)
        """
        if not NUMPY_AVAILABLE:
            print("[CALIBRATION] NumPy requerido para regresión polinómica")
            return [], 0.0
        
        if not self.current_session or len(self.current_session.puntos) < degree + 1:
            return [], 0.0
        
        x = np.array([p.valor_sensor_kg for p in self.current_session.puntos])
        y = np.array([p.peso_aplicado_kg for p in self.current_session.puntos])
        
        # Ajuste polinómico
        coeffs = np.polyfit(x, y, degree)
        
        # Calcular R²
        y_pred = np.polyval(coeffs, x)
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        # Guardar en sesión
        self.current_session.poly_coefficients = [round(c, 9) for c in coeffs.tolist()]
        self.current_session.poly_degree = degree
        self.current_session.poly_r_squared = round(r_squared, 6)
        
        return self.current_session.poly_coefficients, r_squared
    
    def get_calibration_curve_data(self) -> Dict[str, List[float]]:
        """
        Genera datos para graficar las curvas de calibración.
        
        Returns:
            Diccionario con:
            - x_sensor: valores leídos del sensor
            - y_real: pesos reales aplicados
            - y_linear: predicción lineal
            - y_poly: predicción polinómica
            - x_ideal: línea ideal (y=x)
        """
        if not self.current_session or not self.current_session.puntos:
            return {}
        
        x_sensor = [p.valor_sensor_kg for p in self.current_session.puntos]
        y_real = [p.peso_aplicado_kg for p in self.current_session.puntos]
        
        # Línea ideal (si el sensor fuera perfecto)
        x_ideal = list(range(0, int(max(y_real)) + 10000, 5000))
        
        # Predicción lineal
        slope = self.current_session.linear_slope
        offset = self.current_session.linear_offset
        y_linear = [slope * xi + offset for xi in x_sensor]
        
        # Predicción polinómica
        y_poly = []
        if NUMPY_AVAILABLE and self.current_session.poly_coefficients:
            coeffs = np.array(self.current_session.poly_coefficients)
            y_poly = np.polyval(coeffs, np.array(x_sensor)).tolist()
        
        return {
            "x_sensor": x_sensor,
            "y_real": y_real,
            "y_linear": y_linear,
            "y_poly": y_poly,
            "x_ideal": x_ideal,
            "y_ideal": x_ideal  # Línea y=x
        }
    
    def detect_nonlinearity(self) -> Dict[str, Any]:
        """
        Detecta no-linealidades en la curva de calibración.
        
        Returns:
            Diccionario con análisis de linealidad
        """
        if not self.current_session or len(self.current_session.puntos) < 3:
            return {"linear": True, "max_error_percent": 0}
        
        self.calculate_linear_regression()
        slope = self.current_session.linear_slope
        offset = self.current_session.linear_offset
        
        errors = []
        for p in self.current_session.puntos:
            if p.peso_aplicado_kg > 0:
                predicted = slope * p.valor_sensor_kg + offset
                error_percent = abs(predicted - p.peso_aplicado_kg) / p.peso_aplicado_kg * 100
                errors.append({
                    "peso_aplicado": p.peso_aplicado_kg,
                    "error_percent": round(error_percent, 2)
                })
        
        max_error = max(e["error_percent"] for e in errors) if errors else 0
        
        # Detectar si hay aplanamiento en el extremo superior
        upper_third = [e for e in errors if e["peso_aplicado"] > max(p.peso_aplicado_kg for p in self.current_session.puntos) * 0.66]
        upper_avg_error = statistics.mean([e["error_percent"] for e in upper_third]) if upper_third else 0
        
        return {
            "linear": max_error < 0.5,  # Consideramos lineal si error < 0.5%
            "max_error_percent": round(max_error, 2),
            "errors_by_point": errors,
            "upper_third_avg_error": round(upper_avg_error, 2),
            "needs_polynomial": upper_avg_error > 0.3,
            "r_squared": self.current_session.linear_r_squared
        }
    
    def finish_session(self) -> CalibrationSession:
        """
        Finaliza la sesión actual de calibración.
        
        Returns:
            Sesión finalizada con cálculos completados
        """
        if not self.current_session:
            return None
        
        self.current_session.fecha_fin = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Calcular regresiones
        self.calculate_linear_regression()
        if NUMPY_AVAILABLE and len(self.current_session.puntos) >= 4:
            self.calculate_polynomial_regression(degree=2)
        
        return self.current_session
    
    def export_to_csv(self, filepath: str = None) -> str:
        """
        Exporta la sesión actual a CSV.
        
        Args:
            filepath: Ruta del archivo (opcional, genera nombre automático)
            
        Returns:
            Ruta del archivo creado
        """
        if not self.current_session:
            raise ValueError("No hay sesión activa")
        
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"calibracion_{self.current_session.sensor_nombre}_{timestamp}.csv"
            filepath = os.path.join(self._cal_dir, filename)
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Encabezados
            writer.writerow([
                "Peso Aplicado (kg)",
                "Valor Sensor (kg)",
                "Valor mV/V",
                "Desv. Estándar",
                "Timestamp"
            ])
            
            # Datos
            for p in self.current_session.puntos:
                writer.writerow([
                    p.peso_aplicado_kg,
                    p.valor_sensor_kg,
                    p.valor_crudo_mv_v,
                    p.std_dev,
                    p.timestamp
                ])
            
            # Línea en blanco
            writer.writerow([])
            
            # Resultados de calibración
            writer.writerow(["Resultados de Calibración"])
            writer.writerow(["Regresión Lineal"])
            writer.writerow(["Slope", self.current_session.linear_slope])
            writer.writerow(["Offset", self.current_session.linear_offset])
            writer.writerow(["R²", self.current_session.linear_r_squared])
            
            if self.current_session.poly_coefficients:
                writer.writerow([])
                writer.writerow(["Regresión Polinómica"])
                writer.writerow(["Grado", self.current_session.poly_degree])
                writer.writerow(["Coeficientes", *self.current_session.poly_coefficients])
                writer.writerow(["R²", self.current_session.poly_r_squared])
        
        return filepath
    
    def save_session(self, filepath: str = None) -> str:
        """
        Guarda la sesión actual en formato JSON.
        
        Args:
            filepath: Ruta del archivo (opcional)
            
        Returns:
            Ruta del archivo creado
        """
        if not self.current_session:
            raise ValueError("No hay sesión activa")
        
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"calibracion_{self.current_session.sensor_nombre}_{timestamp}.json"
            filepath = os.path.join(self._cal_dir, filename)
        
        # Convertir a diccionario
        data = {
            "sensor_id": self.current_session.sensor_id,
            "sensor_nombre": self.current_session.sensor_nombre,
            "fecha_inicio": self.current_session.fecha_inicio,
            "fecha_fin": self.current_session.fecha_fin,
            "operador": self.current_session.operador,
            "notas": self.current_session.notas,
            "puntos": [asdict(p) for p in self.current_session.puntos],
            "linear_slope": self.current_session.linear_slope,
            "linear_offset": self.current_session.linear_offset,
            "linear_r_squared": self.current_session.linear_r_squared,
            "poly_coefficients": self.current_session.poly_coefficients,
            "poly_degree": self.current_session.poly_degree,
            "poly_r_squared": self.current_session.poly_r_squared
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return filepath
    
    def load_session(self, filepath: str) -> CalibrationSession:
        """
        Carga una sesión de calibración desde archivo JSON.
        
        Args:
            filepath: Ruta del archivo
            
        Returns:
            Sesión cargada
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        session = CalibrationSession(
            sensor_id=data["sensor_id"],
            sensor_nombre=data["sensor_nombre"],
            fecha_inicio=data.get("fecha_inicio", ""),
            fecha_fin=data.get("fecha_fin", ""),
            operador=data.get("operador", ""),
            notas=data.get("notas", "")
        )
        
        # Cargar puntos
        for p_data in data.get("puntos", []):
            point = CalibrationPoint(
                peso_aplicado_kg=p_data["peso_aplicado_kg"],
                valor_crudo_mv_v=p_data.get("valor_crudo_mv_v", 0.0),
                valor_sensor_kg=p_data.get("valor_sensor_kg", 0.0),
                timestamp=p_data.get("timestamp", ""),
                readings_count=p_data.get("readings_count", 1),
                std_dev=p_data.get("std_dev", 0.0)
            )
            session.puntos.append(point)
        
        # Cargar coeficientes
        session.linear_slope = data.get("linear_slope", 1.0)
        session.linear_offset = data.get("linear_offset", 0.0)
        session.linear_r_squared = data.get("linear_r_squared", 0.0)
        session.poly_coefficients = data.get("poly_coefficients", [])
        session.poly_degree = data.get("poly_degree", 1)
        session.poly_r_squared = data.get("poly_r_squared", 0.0)
        
        self.current_session = session
        self.sessions[session.sensor_id] = session
        
        return session
    
    def list_saved_sessions(self) -> List[Dict[str, str]]:
        """
        Lista las sesiones de calibración guardadas.
        
        Returns:
            Lista de diccionarios con info de cada archivo
        """
        sessions = []
        for filename in os.listdir(self._cal_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self._cal_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    sessions.append({
                        "filename": filename,
                        "filepath": filepath,
                        "sensor_nombre": data.get("sensor_nombre", "Desconocido"),
                        "fecha": data.get("fecha_inicio", ""),
                        "puntos": len(data.get("puntos", []))
                    })
                except:
                    pass
        return sessions


def create_calibration_manager(nodos_config: Dict[str, Dict[str, Any]]) -> CalibrationManager:
    """Factory function para crear el gestor de calibración."""
    return CalibrationManager(nodos_config)
