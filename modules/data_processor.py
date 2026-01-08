# -*- coding: utf-8 -*-
"""
data_processor.py - Procesador de Datos para Sistema de Pesaje Industrial
"""

from collections import deque
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import time
import statistics


@dataclass
class SensorData:
    node_id: int
    nombre_logico: str
    valor_crudo: float = 0.0
    valor_filtrado: float = 0.0
    valor_neto: float = 0.0
    tara: float = 0.0
    connected: bool = False
    last_seen: float = 0.0


@dataclass
class SensorDisconnectEvent:
    """Evento de desconexión de sensor para notificar a la GUI."""
    node_id: int
    nombre_logico: str
    timestamp: float
    was_connected: bool = True  # True si estaba conectado antes


class DataProcessor:
    """
    Procesador de datos para sistema de pesaje industrial.
    
    Implementa:
    - Filtro hibrido: Mediana (elimina picos) + EMA (suavizado)
    - Tara matematica de sesion
    - Mapeo de nodos a posiciones logicas
    - Deteccion de desconexion de sensores con eventos
    """
    
    MEDIAN_WINDOW_SIZE = 5
    EMA_ALPHA = 0.3
    SENSOR_TIMEOUT_S = 5.0  # 5 segundos para sensores de 0.5Hz (1 dato cada 2s)
    
    def __init__(self, nodos_config: Dict[str, Dict[str, Any]], 
                 median_window: int = 5,
                 ema_alpha: float = 0.3):
        self.nodos_config = nodos_config
        self.median_window = median_window
        self.ema_alpha = ema_alpha
        
        # Coeficientes de Calibración Global (Sistema Completo)
        # y = mx + b
        # y = (Suma_Raw * slope) + offset
        self.system_slope: float = 1.0
        self.system_offset: float = 0.0
        
        self._last_total_raw: float = 0.0 # Almacenar ultimo raw sum para calibracion
        
        self._node_to_name: Dict[int, str] = {}
        self._median_buffers: Dict[int, deque] = {}
        self._ema_values: Dict[int, Optional[float]] = {}
        self._tares: Dict[int, float] = {}
        self._last_seen: Dict[int, float] = {}
        self._node_connected_state: Dict[int, bool] = {}
        
        # Cola de eventos de desconexión pendientes
        self._disconnect_events: List[SensorDisconnectEvent] = []
        
        self._initialize_structures()
    
    def _initialize_structures(self) -> None:
        for nombre_logico, cfg in self.nodos_config.items():
            node_id = cfg["id"]
            self._node_to_name[node_id] = nombre_logico
            self._median_buffers[node_id] = deque(maxlen=self.median_window)
            self._ema_values[node_id] = None
            self._tares[node_id] = 0.0
            self._last_seen[node_id] = 0.0
            self._node_connected_state[node_id] = False
    
    def _apply_median_filter(self, node_id: int, value: float) -> float:
        if node_id not in self._median_buffers:
            self._median_buffers[node_id] = deque(maxlen=self.median_window)
        
        buffer = self._median_buffers[node_id]
        buffer.append(value)
        
        if len(buffer) == 0:
            return value
        elif len(buffer) == 1:
            return buffer[0]
        else:
            return statistics.median(buffer)
    
    def _apply_ema_filter(self, node_id: int, value: float) -> float:
        if node_id not in self._ema_values:
            self._ema_values[node_id] = None
        
        if self._ema_values[node_id] is None:
            self._ema_values[node_id] = value
            return value
        
        ema = self.ema_alpha * value + (1 - self.ema_alpha) * self._ema_values[node_id]
        self._ema_values[node_id] = ema
        return ema
    
    def _filter_value(self, node_id: int, raw_value: float) -> float:
        median_value = self._apply_median_filter(node_id, raw_value)
        ema_value = self._apply_ema_filter(node_id, median_value)
        return ema_value
    
    def procesar(self, raw_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        resultado = {
            "sensores": {},
            "total": 0.0,
            "total_raw": 0.0, # Nuevo campo para debugging
            "total_tare": 0.0,
            "logs": [],
            "disconnect_events": [],
            "any_disconnected": False
        }
        
        current_time = time.time()
        datos_por_nodo = self._extract_node_data(raw_data)
        
        # 1. Detectar conexiones / desconexiones
        for node_id, value in datos_por_nodo.items():
            self._last_seen[node_id] = current_time
            if not self._node_connected_state.get(node_id, False):
                self._node_connected_state[node_id] = True
                nombre = self._node_to_name.get(node_id, f"Nodo {node_id}")
                resultado["logs"].append(f"Sensor {nombre} (ID:{node_id}) conectado")
        
        # 2. Estrategia "Suma de Fuerzas": Sumar Raw PRIMERO
        sum_raw_connected = 0.0
        active_sensors_count = 0
        
        for nombre_logico, cfg in self.nodos_config.items():
            node_id = cfg["id"]
            is_connected = self._check_connection(node_id, current_time, resultado)
            
            valor_crudo = 0.0
            if node_id in datos_por_nodo:
                valor_crudo = datos_por_nodo[node_id]
            else:
                # Si no hay dato nuevo, usar ultimo conocido o 0?
                # Usamos 0 si no esta conectado.
                pass
                
            # Aplicar filtros al valor individual para visualizacin estable
            valor_filtrado = self._filter_value(node_id, valor_crudo)
            
            # Acumular para la Suma Total (usamos valor filtrado para estabilidad)
            if is_connected:
                sum_raw_connected += valor_filtrado
                active_sensors_count += 1
            else:
                resultado["any_disconnected"] = True
            
            # Datos individuales (sin calibrar, solo raw bits)
            resultado["sensores"][nombre_logico] = {
                "valor": 0.0, # Ya no calculamos peso individual
                "raw": int(valor_filtrado), # Mostrar bits
                "crudo": int(valor_crudo),
                "id": node_id,
                "connected": is_connected
            }

        self._last_total_raw = sum_raw_connected # Guardar para acceso externo (Calibracion)

        # 3. Aplicar Formula Lineal al Total: y = mx + b
        # Peso = (Suma_Raw * m) + b
        
        # IMPORTANTE: Si falta algun sensor, la suma es invalida para pesaje preciso
        # pero mostramos lo que hay.
        
        peso_bruto = (sum_raw_connected * self.system_slope) + self.system_offset
        
        # Aplicar Tara Global
        # La tara ahora se aplica sobre el peso calculado (no sobre raw)
        # O se puede manejar 'b' como (Offset_Zero - Tara).
        # Implementaremos tara simple: Peso_Neto = Peso_Bruto - Tara_Global
        
        tara_global = self._tares.get("global", 0.0)
        peso_neto = peso_bruto - tara_global
        
        resultado["total"] = round(peso_neto, 3)
        resultado["total_raw"] = sum_raw_connected
        resultado["total_tare"] = round(tara_global, 3)
        
        # Incluir eventos de desconexión pendientes
        disconnect_events = self.get_disconnect_events()
        if disconnect_events:
            resultado["disconnect_events"] = [
                {"node_id": e.node_id, "nombre": e.nombre_logico, "timestamp": e.timestamp}
                for e in disconnect_events
            ]
        
        return resultado
        
    def set_system_calibration(self, slope: float, offset: float):
        """Actualiza los coeficientes de calibración del sistema."""
        self.system_slope = slope
        self.system_offset = offset

    def update_calibration(self, slope: float, offset: float):
        """Actualiza los coeficientes de calibración del sistema."""
        self.system_slope = slope
        self.system_offset = offset

    def set_tara(self) -> float:
        """Establece tara global usando el peso actual."""
        # Necesitamos el ultimo peso bruto calculado. 
        # Como procesar() es stateless respecto al peso bruto anterior,
        # Recalculamos rapido con los ultimos EMAs
        
        sum_raw = 0.0
        for node_id in self._ema_values:
             if self._ema_values[node_id] is not None:
                 sum_raw += self._ema_values[node_id]
        
        peso_bruto_actual = (sum_raw * self.system_slope) + self.system_offset
        self._tares["global"] = peso_bruto_actual
        return peso_bruto_actual

    def reset_tara(self) -> None:
        self._tares["global"] = 0.0
    
    def load_tara_state(self) -> bool:
        """Carga el estado de tara desde app_state.json."""
        import json
        import os
        state_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_state.json")
        
        if os.path.exists(state_path):
            try:
                with open(state_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                
                if 'taras' in state:
                    for node_id_str, tara_value in state['taras'].items():
                        node_id = int(node_id_str)
                        if node_id in self._tares:
                            self._tares[node_id] = float(tara_value)
                    return True
            except Exception as e:
                print(f"[DATA_PROCESSOR] Error cargando estado de tara: {e}")
        return False
    
    def _save_tara_state(self) -> bool:
        """Guarda el estado de tara en app_state.json."""
        import json
        import os
        state_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_state.json")
        
        try:
            # Cargar estado existente si hay
            state = {}
            if os.path.exists(state_path):
                try:
                    with open(state_path, 'r', encoding='utf-8') as f:
                        state = json.load(f)
                except:
                    pass
            
            # Actualizar taras (convertir keys a string para JSON)
            state['taras'] = {str(k): v for k, v in self._tares.items()}
            state['last_updated'] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[DATA_PROCESSOR] Error guardando estado de tara: {e}")
            return False
    
    def get_tara(self, node_id: int) -> float:
        return self._tares.get(node_id, 0.0)
    
    def get_all_taras(self) -> Dict[int, float]:
        return dict(self._tares)
    
    def reset_filters(self) -> None:
        for node_id in self._median_buffers:
            self._median_buffers[node_id].clear()
        for node_id in self._ema_values:
            self._ema_values[node_id] = None
    
    def get_filter_state(self, node_id: int) -> Dict[str, Any]:
        return {
            "median_buffer": list(self._median_buffers.get(node_id, [])),
            "median_buffer_size": len(self._median_buffers.get(node_id, [])),
            "ema_value": self._ema_values.get(node_id),
            "tare": self._tares.get(node_id, 0.0),
            "last_seen": self._last_seen.get(node_id, 0.0),
            "is_connected": self._node_connected_state.get(node_id, False)
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        connected_count = sum(1 for v in self._node_connected_state.values() if v)
        return {
            "nodes_configured": len(self.nodos_config),
            "nodes_connected": connected_count,
            "median_window_size": self.median_window,
            "ema_alpha": self.ema_alpha,
            "total_tare": sum(self._tares.values()),
            "sensor_timeout_s": self.SENSOR_TIMEOUT_S
        }
    
    def get_last_total_raw(self) -> float:
        """Retorna la ultima suma total de valores raw (filtrados)."""
        return self._last_total_raw


def create_processor(nodos_config: Dict[str, Dict[str, Any]], 
                     median_window: int = 5,
                     ema_alpha: float = 0.3) -> DataProcessor:
    return DataProcessor(
        nodos_config=nodos_config,
        median_window=median_window,
        ema_alpha=ema_alpha
    )
