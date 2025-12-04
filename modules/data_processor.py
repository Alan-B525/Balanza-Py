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
    SENSOR_TIMEOUT_S = 3.0
    
    def __init__(self, nodos_config: Dict[str, Dict[str, Any]], 
                 median_window: int = 5,
                 ema_alpha: float = 0.3):
        self.nodos_config = nodos_config
        self.median_window = median_window
        self.ema_alpha = ema_alpha
        
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
            "total_tare": 0.0,
            "logs": [],
            "disconnect_events": [],  # Eventos de desconexión para la GUI
            "any_disconnected": False  # Flag rápido para verificar desconexiones
        }
        
        current_time = time.time()
        datos_por_nodo = self._extract_node_data(raw_data)
        
        for node_id, value in datos_por_nodo.items():
            self._last_seen[node_id] = current_time
            
            if not self._node_connected_state.get(node_id, False):
                self._node_connected_state[node_id] = True
                nombre = self._node_to_name.get(node_id, f"Nodo {node_id}")
                resultado["logs"].append(f"Sensor {nombre} (ID:{node_id}) conectado")
        
        total_peso = 0.0
        total_tare = 0.0
        
        for nombre_logico, cfg in self.nodos_config.items():
            node_id = cfg["id"]
            is_connected = self._check_connection(node_id, current_time, resultado)
            
            valor_crudo = 0.0
            valor_filtrado = 0.0
            
            if node_id in datos_por_nodo:
                valor_crudo = datos_por_nodo[node_id]
                valor_filtrado = self._filter_value(node_id, valor_crudo)
            elif self._ema_values.get(node_id) is not None:
                valor_filtrado = self._ema_values[node_id]
            
            tara_actual = self._tares.get(node_id, 0.0)
            valor_neto = valor_filtrado - tara_actual
            
            if is_connected:
                total_peso += valor_neto
                total_tare += tara_actual
            else:
                resultado["any_disconnected"] = True
            
            resultado["sensores"][nombre_logico] = {
                "valor": round(valor_neto, 3),
                "raw": round(valor_filtrado, 3),
                "crudo": round(valor_crudo, 3),
                "id": node_id,
                "tara": round(tara_actual, 3),
                "connected": is_connected
            }
        
        resultado["total"] = round(total_peso, 3)
        resultado["total_tare"] = round(total_tare, 3)
        
        # Incluir eventos de desconexión pendientes
        disconnect_events = self.get_disconnect_events()
        if disconnect_events:
            resultado["disconnect_events"] = [
                {"node_id": e.node_id, "nombre": e.nombre_logico, "timestamp": e.timestamp}
                for e in disconnect_events
            ]
        
        return resultado
    
    def _extract_node_data(self, raw_data: List[Dict[str, Any]]) -> Dict[int, float]:
        datos_por_nodo: Dict[int, float] = {}
        
        for item in raw_data:
            if "values" in item:
                for node_id, value in item["values"].items():
                    datos_por_nodo[node_id] = value
            elif "node_id" in item and "value" in item:
                datos_por_nodo[item["node_id"]] = item["value"]
        
        return datos_por_nodo
    
    def _check_connection(self, node_id: int, current_time: float, 
                          resultado: Dict) -> bool:
        last_seen = self._last_seen.get(node_id, 0.0)
        is_connected = (current_time - last_seen) <= self.SENSOR_TIMEOUT_S
        
        if not is_connected and self._node_connected_state.get(node_id, False):
            self._node_connected_state[node_id] = False
            nombre = self._node_to_name.get(node_id, f"Nodo {node_id}")
            resultado["logs"].append(f"ALERTA: {nombre} (ID:{node_id}) perdio conexion")
            
            # Generar evento de desconexión
            event = SensorDisconnectEvent(
                node_id=node_id,
                nombre_logico=nombre,
                timestamp=current_time,
                was_connected=True
            )
            self._disconnect_events.append(event)
        
        return is_connected
    
    def get_disconnect_events(self) -> List[SensorDisconnectEvent]:
        """Retorna y limpia los eventos de desconexión pendientes."""
        events = self._disconnect_events.copy()
        self._disconnect_events.clear()
        return events
    
    def get_disconnected_sensors(self) -> List[Dict[str, Any]]:
        """Retorna lista de sensores actualmente desconectados."""
        disconnected = []
        current_time = time.time()
        for nombre_logico, cfg in self.nodos_config.items():
            node_id = cfg["id"]
            if not self._node_connected_state.get(node_id, False):
                disconnected.append({
                    "node_id": node_id,
                    "nombre": nombre_logico,
                    "last_seen": self._last_seen.get(node_id, 0.0),
                    "offline_seconds": current_time - self._last_seen.get(node_id, 0.0)
                })
        return disconnected
    
    def mark_sensor_reconnected(self, node_id: int) -> None:
        """Marca un sensor como reconectado (para uso externo)."""
        self._node_connected_state[node_id] = True
        self._last_seen[node_id] = time.time()
    
    def set_tara(self) -> Dict[int, float]:
        taras_aplicadas = {}
        for node_id, ema_value in self._ema_values.items():
            if ema_value is not None:
                self._tares[node_id] = ema_value
                taras_aplicadas[node_id] = ema_value
        return taras_aplicadas
    
    def reset_tara(self) -> None:
        for node_id in self._tares:
            self._tares[node_id] = 0.0
    
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


def create_processor(nodos_config: Dict[str, Dict[str, Any]], 
                     median_window: int = 5,
                     ema_alpha: float = 0.3) -> DataProcessor:
    return DataProcessor(
        nodos_config=nodos_config,
        median_window=median_window,
        ema_alpha=ema_alpha
    )
