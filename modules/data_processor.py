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

    def _log_to_file(self, message):
        try:
            from . import logger
            logger.info(f"[DATA_PROCESSOR] {message}")
        except Exception:
            try:
                # Fallback silente
                import datetime, os
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'balanza.log')
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(f"[{timestamp}] [DATA_PROCESSOR] {message}\n")
            except Exception:
                pass
    
    MEDIAN_WINDOW_SIZE = 5
    EMA_ALPHA = 0.3
    SENSOR_TIMEOUT_S = 5.0  # 5 segundos para sensores de 0.5Hz (1 dato cada 2s)
    USE_FILTERS = False  # Cambia a True si quieres activar filtros
    
    def __init__(self, nodos_config: Dict[str, Dict[str, Any]], 
                 median_window: int = 5,
                 ema_alpha: float = 0.3,
                 input_unit: str = "kg"):
        self.nodos_config = nodos_config
        self.median_window = median_window
        self.ema_alpha = ema_alpha
        self.input_unit = input_unit  # "kg" o "t"
        
        # Coeficientes de Calibración Global (Sistema Completo)
        # y = mx + b
        # y = (Suma_Raw * slope) + offset
        self.system_slope: float = 1.0
        self.system_offset: float = 0.0
        
        self._last_total_raw: float = 0.0 # Almacenar ultimo raw sum para calibracion
        self._last_total_weight: float = 0.0 # Almacenar ultimo peso neto (visible) para tara
        
        self._node_to_name: Dict[str, str] = {}
        self._median_buffers: Dict[str, deque] = {}
        self._ema_values: Dict[str, Optional[float]] = {}
        self._tares: Dict[str, float] = {}
        self._last_seen: Dict[str, float] = {}
        self._node_connected_state: Dict[str, bool] = {}
        self._last_total_seen: float = 0.0
        
        # Cola de eventos de desconexión pendientes
        self._disconnect_events: List[SensorDisconnectEvent] = []
        
        self._initialize_structures()
    
    def _initialize_structures(self) -> None:
        for nombre_logico, cfg in self.nodos_config.items():
            node_id = cfg["id"]
            channel = cfg.get("ch", "ch1")
            composite = f"{node_id}:{channel}"
            self._node_to_name[composite] = nombre_logico
            self._median_buffers[composite] = deque(maxlen=self.median_window)
            self._ema_values[composite] = None
            self._tares[composite] = 0.0
            self._last_seen[composite] = 0.0
            self._node_connected_state[composite] = False
            self._log_to_file(f"Inicializado nodo {nombre_logico} (ID={node_id})")
    
    def _apply_median_filter(self, node_key, value: float) -> float:
        if not self.USE_FILTERS:
            return value
        if node_key not in self._median_buffers:
            self._median_buffers[node_key] = deque(maxlen=self.median_window)
        buffer = self._median_buffers[node_key]
        buffer.append(value)
        if len(buffer) == 0:
            return value
        elif len(buffer) == 1:
            return buffer[0]
        else:
            return statistics.median(buffer)
    
    def _apply_ema_filter(self, node_key, value: float) -> float:
        if not self.USE_FILTERS:
            return value
        if node_key not in self._ema_values:
            self._ema_values[node_key] = None
        if self._ema_values[node_key] is None:
            self._ema_values[node_key] = value
            return value
        ema = self.ema_alpha * value + (1 - self.ema_alpha) * self._ema_values[node_key]
        self._ema_values[node_key] = ema
        return ema
    
    def _filter_value(self, node_key, raw_value: float) -> float:
        if not self.USE_FILTERS:
            return raw_value
        median_value = self._apply_median_filter(node_key, raw_value)
        ema_value = self._apply_ema_filter(node_key, median_value)
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

        # 1. Detectar conexiones / desconexiones (datos indexados por clave compuesta)
        for node_key, value in datos_por_nodo.items():
            # node_key es algo como '4248:ch1'
            self._last_seen[node_key] = current_time
            if not self._node_connected_state.get(node_key, False):
                self._node_connected_state[node_key] = True
                nombre = self._node_to_name.get(node_key, f"Nodo {node_key}")
                resultado["logs"].append(f"Sensor {nombre} (Key:{node_key}) conectado")
        
        # 2. Estrategia "Suma de Fuerzas": Sumar Raw PRIMERO
        sum_raw_connected = 0.0
        active_sensors_count = 0
        # Guarda valores filtrados por nodo (clave compuesta) para distribución posterior
        _valor_filtrado_por_nodo: Dict[str, float] = {}

        for nombre_logico, cfg in self.nodos_config.items():
            node_id = cfg["id"]
            channel = cfg.get("ch", "ch1")
            composite = f"{node_id}:{channel}"
            is_connected = self._check_connection(composite, current_time, resultado)
            valor_crudo = 0.0
            if composite in datos_por_nodo:
                valor_crudo = datos_por_nodo[composite]
                # Algunos sensores/reportes MSCL vienen con signo negativo
                # (depende de la configuración de la celda). Para evitar
                # que una suma total negativa bloquee la visualización,
                # normalizamos usando el valor absoluto aquí.
                try:
                    valor_crudo = abs(float(valor_crudo))
                except Exception:
                    valor_crudo = float(valor_crudo)
                # Conversión de unidad si el dato viene en toneladas
                if self.input_unit == "t":
                    valor_crudo = valor_crudo * 1000.0
            # NO aplicar filtros si USE_FILTERS es False
            # Usamos la clave compuesta para buffers/EMA/memoria
            valor_filtrado = self._filter_value(composite, valor_crudo)
            _valor_filtrado_por_nodo[composite] = valor_filtrado
            if is_connected:
                sum_raw_connected += valor_filtrado
                active_sensors_count += 1
            else:
                resultado["any_disconnected"] = True
            resultado["sensores"][nombre_logico] = {
                "valor": 0.0,  # se calculará después para garantizar consistencia con el total
                "raw": round(valor_filtrado, 3),
                "crudo": round(valor_crudo, 3),
                "id": node_id,
                "key": composite,
                "connected": is_connected,
                "last_seen": self._last_seen.get(composite, 0.0)
            }

        # Guardar la última suma raw válida; NO sobrescribir con 0 para
        # evitar que muestras intermedias borren el último valor crudo real.
        if sum_raw_connected > 0:
            self._last_total_raw = sum_raw_connected

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
        # Actualizar timestamp del total solo si hay datos conectados (evita zeros intermedios)
        if sum_raw_connected > 0:
            self._last_total_seen = current_time
            # Guardar el último peso neto visible para operaciones como tara
            self._last_total_weight = peso_neto
        resultado["total_last_seen"] = self._last_total_seen
        
        # Incluir eventos de desconexión pendientes
        disconnect_events = self.get_disconnect_events()
        if disconnect_events:
            resultado["disconnect_events"] = [
                {"node_id": e.node_id, "nombre": e.nombre_logico, "timestamp": e.timestamp}
                for e in disconnect_events
            ]

        # 4. Asignar valor individual por sensor proporcional al total calculado
        try:
            if sum_raw_connected > 0:
                for nombre_logico, cfg in self.nodos_config.items():
                    node_id = cfg["id"]
                    channel = cfg.get("ch", "ch1")
                    composite = f"{node_id}:{channel}"
                    sensor_entry = resultado["sensores"].get(nombre_logico)
                    if not sensor_entry:
                        continue
                    if sensor_entry.get("connected"):
                        vf = _valor_filtrado_por_nodo.get(composite, 0.0)
                        # Distribuir el peso neto proporcionalmente al aporte raw
                        sensor_val = (vf / sum_raw_connected) * peso_neto
                        sensor_entry["valor"] = round(sensor_val, 3)
                    else:
                        sensor_entry["valor"] = 0.0
            else:
                # No hay datos conectados; dejar en 0
                pass
        except Exception as e:
            self._log_to_file(f"Error asignando valores individuales: {e}")
        
        return resultado

    def _extract_node_data(self, raw_data: List[Dict[str, Any]]) -> Dict[str, float]:
        result: Dict[str, float] = {}

        if not raw_data:
            return result

        # Tomamos SOLO el último frame válido
        last_frame = raw_data[-1]

        if not isinstance(last_frame, dict):
            return result

        values = last_frame.get("values", {})
        if not isinstance(values, dict):
            return result

        for key, val in values.items():
            try:
                result[str(key)] = float(val)
            except Exception:
                continue

        return result


    def _check_connection(self, node_key: str, current_time: float, resultado: Dict[str, Any]) -> bool:
        """Verifica si un nodo está conectado según último timestamp observado.

        Si se detecta timeout, genera un evento de desconexión y actualiza el estado.
        Devuelve True si conectado, False si desconectado.
        """
        last = self._last_seen.get(node_key, 0.0)
        was_connected = self._node_connected_state.get(node_key, False)
        if (current_time - last) > self.SENSOR_TIMEOUT_S:
            if was_connected:
                # marcar desconectado y encolar evento
                self._node_connected_state[node_key] = False
                nombre = self._node_to_name.get(node_key, f"Nodo {node_key}")
                # Extraer node_id numérico para el evento si es posible
                try:
                    node_num = int(str(node_key).split(":")[0])
                except Exception:
                    node_num = 0
                ev = SensorDisconnectEvent(node_id=node_num, nombre_logico=nombre, timestamp=current_time, was_connected=True)
                self._disconnect_events.append(ev)
                resultado.setdefault("logs", []).append(f"Sensor {nombre} (Key:{node_key}) desconectado")
            return False
        else:
            return True

    def get_disconnect_events(self) -> List[SensorDisconnectEvent]:
        """Retorna y limpia la cola de eventos de desconexión pendientes."""
        events = list(self._disconnect_events)
        self._disconnect_events.clear()
        return events
        
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
        # La tara debe calcularse siempre a partir de los ÚLTIMOS DATOS CRUDOS
        # para evitar aplicar tara sobre un valor que ya está tarado.
        # Usamos _last_total_raw (suma filtrada/raw por nodo) cuando esté disponible.
        sum_raw = getattr(self, '_last_total_raw', 0.0) or 0.0

        if sum_raw > 0.0:
            peso_bruto_actual = (sum_raw * self.system_slope) + self.system_offset
            self._tares["global"] = peso_bruto_actual
            return peso_bruto_actual

        # Fallback: si no hay _last_total_raw, intentar reconstruir desde EMAs
        sum_raw_fallback = 0.0
        for v in self._ema_values.values():
            if v is not None:
                sum_raw_fallback += v

        peso_bruto_actual = (sum_raw_fallback * self.system_slope) + self.system_offset
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
    
    def get_tara(self, node_key) -> float:
        """Devuelve la tara para una clave compuesta ('id:ch') o un id numérico.
        Si se pasa un int, intenta sumar/retornar la primera coincidencia.
        """
        if isinstance(node_key, int):
            # Buscar la primera clave que empiece con el id
            matches = [k for k in self._tares.keys() if str(k).startswith(f"{node_key}:")]
            if matches:
                return self._tares.get(matches[0], 0.0)
            return 0.0
        return self._tares.get(node_key, 0.0)
    
    def get_all_taras(self) -> Dict[str, float]:
        return dict(self._tares)
    
    def reset_filters(self) -> None:
        for node_id in self._median_buffers:
            self._median_buffers[node_id].clear()
        for node_id in self._ema_values:
            self._ema_values[node_id] = None
    
    def get_filter_state(self, node_key: str) -> Dict[str, Any]:
        return {
            "median_buffer": list(self._median_buffers.get(node_key, [])),
            "median_buffer_size": len(self._median_buffers.get(node_key, [])),
            "ema_value": self._ema_values.get(node_key),
            "tare": self._tares.get(node_key, 0.0),
            "last_seen": self._last_seen.get(node_key, 0.0),
            "is_connected": self._node_connected_state.get(node_key, False)
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
