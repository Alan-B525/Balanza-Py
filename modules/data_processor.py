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
    - Filtro hibrido: Mediana (elimina picos) + EMA (suavizado) ¡¡¡DESACTIVADO!!!
    - Tara matematica de sesion
    - Mapeo de nodos a posiciones logicas
    - Deteccion de desconexion de sensores con eventos
    """

    def _log_to_file(self, message):
        try:
            from . import logger
            logger.info(f"[PROCESSADOR] {message}")
        except Exception:
            try:
                # Fallback silente
                import datetime, os
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'log.log')
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
                 input_unit: str = "t"):
        self.nodos_config = nodos_config
        self.median_window = median_window
        self.ema_alpha = ema_alpha
        self.input_unit = "kg"  # Force kg as per user request
        
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
        self._last_raw_readings: Dict[str, float] = {}
        # Último valor procesado (estable) por composite (sample & hold)
        self._last_stable_values: Dict[str, float] = {}
        self._last_seen: Dict[str, float] = {}
        self._node_connected_state: Dict[str, bool] = {}
        # Claves de canal de carga (para logs/eventos)
        self._load_keys: set = set()
        self._last_total_seen: float = 0.0
        # Mapas para calibración por sensor
        self.sensor_calibrations: Dict[str, Dict[str, Any]] = {}  # key -> {'method':..., 'points':[(raw,weight),...]}
        self._composite_to_serial: Dict[str, Optional[str]] = {}
        
        # Cola de eventos de desconexión pendientes
        self._disconnect_events: List[SensorDisconnectEvent] = []
        
        self._initialize_structures()
    
    def _initialize_structures(self) -> None:
        # Limpiar estructuras previas antes de (re)inicializar
        self._node_to_name.clear()
        self._median_buffers.clear()
        self._ema_values.clear()
        self._tares.clear()
        self._last_stable_values.clear()
        self._last_seen.clear()
        self._node_connected_state.clear()
        self._composite_to_serial.clear()
        self._load_keys.clear()

        for nombre_logico, cfg in self.nodos_config.items():
            node_id = cfg["id"]
            if not isinstance(cfg, dict):
                cfg = {}

            ch_load = cfg.get('ch_load', cfg.get('ch', 'ch1'))
            ch_angles = cfg.get('ch_angles')
            if not isinstance(ch_angles, list):
                ch_single = cfg.get('ch_angle', 'ch2')
                ch_angles = [ch_single]
            ch_angles = [str(ch).strip() for ch in ch_angles if str(ch).strip()]

            load_enabled = bool(cfg.get('load_enabled', True))

            if load_enabled:
                comp_load = f"{node_id}:{ch_load}"
                self._node_to_name[comp_load] = nombre_logico
                self._median_buffers[comp_load] = deque(maxlen=self.median_window)
                self._ema_values[comp_load] = None
                self._tares[comp_load] = 0.0
                self._last_stable_values[comp_load] = 0.0
                self._last_seen[comp_load] = 0.0
                self._node_connected_state[comp_load] = False
                self._load_keys.add(comp_load)

                serial = cfg.get('serial') if isinstance(cfg, dict) else None
                self._composite_to_serial[comp_load] = serial

            for idx, ch_angle in enumerate(ch_angles, start=1):
                comp_angle = f"{node_id}:{ch_angle}"
                self._node_to_name[comp_angle] = f"{nombre_logico}_Angle{idx}"
                self._median_buffers[comp_angle] = deque(maxlen=self.median_window)
                self._ema_values[comp_angle] = None
                self._tares[comp_angle] = 0.0
                self._last_stable_values[comp_angle] = 0.0
                self._last_seen[comp_angle] = 0.0
                self._node_connected_state[comp_angle] = False

    def update_config(self, new_nodes_config: Dict[str, Any]):
        """Actualiza la configuración en caliente y reinicializa estructuras."""
        self.nodos_config = new_nodes_config
        self._initialize_structures()
            # evento de inicialización: no loguear para evitar ruido en el log
    
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
            "total_raw": 0.0,
            "total_tare": 0.0,
            "angle_val": 0.0,   # Nuevo campo para el ángulo
            "angles": [],
            "logs": [],
            "disconnect_events": [],
            "any_disconnected": False
        }
        
        current_time = time.time()
        datos_por_nodo = self._extract_node_data(raw_data)

        # 1. Detectar conexiones / desconexiones
        # Iterar sobre las claves que esperamos (load y angle) para actualizar timestamps
        for node_key in self._node_to_name.keys():
             if node_key in datos_por_nodo:
                self._last_seen[node_key] = current_time
                if not self._node_connected_state.get(node_key, False):
                    self._node_connected_state[node_key] = True
                    nombre = self._node_to_name.get(node_key, f"Nodo {node_key}")
                    # Loguear conexión solo para el canal principal (LOAD) para evitar spam doble
                    if node_key in self._load_keys:
                        resultado["logs"].append(f"Sensor {nombre} conectado")
        
        # 2. Estrategia "Suma de Fuerzas" (Solo Carga ch1)
        sum_raw_connected = 0.0
        sum_contrib_connected = 0.0
        any_calibrated = False
        
        _valor_filtrado_por_key: Dict[str, float] = {}
        _contrib_por_key: Dict[str, float] = {}

        # Variables para el ángulo
        total_angle_val = 0.0
        angle_count = 0
        angles_ordered: List[float] = []

        for nombre_logico, cfg in self.nodos_config.items():
            if not isinstance(cfg, dict):
                cfg = {}
            node_id = cfg.get("id", 0)
            ch_load = cfg.get('ch_load', cfg.get('ch', 'ch1'))
            ch_angles = cfg.get('ch_angles')
            if not isinstance(ch_angles, list):
                ch_single = cfg.get('ch_angle', 'ch2')
                ch_angles = [ch_single]
            ch_angles = [str(ch).strip() for ch in ch_angles if str(ch).strip()]
            load_enabled = bool(cfg.get('load_enabled', True))

            node_angles: List[float] = []

            # --- PROCESAR CANAL DE CARGA ---
            if load_enabled:
                comp_load = f"{node_id}:{ch_load}"
                is_connected_load = self._check_connection(comp_load, current_time, resultado, emit_event=True)

                val_load = 0.0
                if comp_load in datos_por_nodo:
                    original = datos_por_nodo[comp_load]
                    try:
                        val_load = float(original)
                    except:
                        val_load = 0.0
                    self._last_raw_readings[comp_load] = val_load

                    mult = 1.0
                    try:
                        if 'sign' in cfg:
                            mult = float(cfg.get('sign', 1.0))
                        elif cfg.get('invert', False):
                            mult = -1.0
                    except:
                        mult = 1.0
                    val_load = val_load * mult
                else:
                    val_load = self._last_raw_readings.get(comp_load, 0.0)

                val_load_filt = self._filter_value(comp_load, val_load)
                if comp_load in datos_por_nodo:
                    self._last_stable_values[comp_load] = val_load_filt

                calibrated_load = None
                try:
                    calibrated_load = self._map_raw_to_weight(comp_load, val_load_filt)
                except:
                    pass

                if calibrated_load is not None:
                    contrib_load = float(calibrated_load)
                    any_calibrated = True
                else:
                    contrib_load = val_load_filt

                _valor_filtrado_por_key[comp_load] = val_load_filt
                _contrib_por_key[comp_load] = contrib_load

                if is_connected_load:
                    sum_raw_connected += val_load_filt
                    sum_contrib_connected += contrib_load
                else:
                    resultado["any_disconnected"] = True

            # --- PROCESAR CANALES DE ANGULO ---
            for ch_angle in ch_angles:
                comp_angle = f"{node_id}:{ch_angle}"
                self._check_connection(comp_angle, current_time, resultado, emit_event=False)

                val_angle = 0.0
                if comp_angle in datos_por_nodo:
                    try:
                        val_angle = float(datos_por_nodo[comp_angle])
                    except:
                        val_angle = 0.0
                    self._last_raw_readings[comp_angle] = val_angle
                else:
                    val_angle = self._last_raw_readings.get(comp_angle, 0.0)

                node_angles.append(val_angle)
                angles_ordered.append(val_angle)

                if comp_angle in datos_por_nodo or self._node_connected_state.get(comp_angle, False):
                    total_angle_val += val_angle
                    angle_count += 1

            # --- POPULAR RESULTADO INDIVIDUAL ---
            if load_enabled:
                comp_load = f"{node_id}:{ch_load}"
                tare_val = self._tares.get(comp_load, 0.0)
                sensor_net = _contrib_por_key.get(comp_load, 0.0) - tare_val
                val_load_filt = _valor_filtrado_por_key.get(comp_load, 0.0)
                val_load_raw = self._last_raw_readings.get(comp_load, 0.0)
                is_connected_load = self._node_connected_state.get(comp_load, False)

                resultado["sensores"][nombre_logico] = {
                    "valor": round(sensor_net, 3),
                    "raw": round(val_load_filt, 3),
                    "crudo": round(val_load_raw, 3),
                    "angles": [round(a, 2) for a in node_angles],
                    "id": node_id,
                    "key": comp_load,
                    "connected": is_connected_load,
                    "last_seen": self._last_seen.get(comp_load, 0.0)
                }

        # Guardar ultima suma raw valida
        if sum_raw_connected != 0:
            self._last_total_raw = sum_raw_connected

        # 3. Calcular Total (PESO)
        # Si hay calibración por sensor, usar suma directa. Si no, sistema mx+b
        if any_calibrated:
            peso_bruto = float(sum_contrib_connected)
        else:
            peso_bruto = (sum_raw_connected * self.system_slope) + self.system_offset
        
        # Calcular tara total (suma de taras de los canales de carga activos o configurados)
        tara_total = 0.0
        for k, v in self._tares.items():
            # Check against configured load channels for any node
            is_load_channel = False
            for cfg in self.nodos_config.values():
                ch_load = cfg.get('ch_load', cfg.get('ch', 'ch1'))
                if f":{ch_load}" in str(k):
                    is_load_channel = True
                    break
            
            if is_load_channel: # Solo sumar taras de canales de carga
                try: tara_total += float(v)
                except: pass
        
        peso_neto = peso_bruto - tara_total

        # Evitar saltos a 0
        if sum_raw_connected == 0 and not resultado["any_disconnected"]:
             # Si no hay nada conectado, 0. Si hay desconectados, flag.
             # Pero si simplemente no llegó dato en este ciclo (pero conectado), mantener.
             # La lógica original usaba sum_raw_connected == 0 como heurística de "nadie midió"
             # Mejor usar active_sensors_count check o similar, pero por compatibilidad:
             resultado["total"] = round(self._last_total_weight, 3)
        else:
             resultado["total"] = round(peso_neto, 3)
             if sum_raw_connected != 0:
                 self._last_total_weight = peso_neto
                 self._last_total_seen = current_time

        resultado["total_raw"] = sum_raw_connected
        resultado["total_tare"] = round(tara_total, 3)
        resultado["total_last_seen"] = self._last_total_seen
        
        # Ángulo Final (compatibilidad): promedio simple de todos los canales
        if angle_count > 0:
            resultado["angle_val"] = round(total_angle_val / angle_count, 2)
        else:
            resultado["angle_val"] = 0.0

        resultado["angles"] = [round(a, 2) for a in angles_ordered]
        
        # Eventos
        disconnect_events = self.get_disconnect_events()
        if disconnect_events:
            resultado["disconnect_events"] = [
                {"node_id": e.node_id, "nombre": e.nombre_logico, "timestamp": e.timestamp}
                for e in disconnect_events
            ]
        
        return resultado

    def _extract_node_data(self, raw_data: List[Dict[str, Any]]) -> Dict[str, float]:
        result: Dict[str, float] = {}

        if not raw_data:
            return result

        # Procesar TODOS los frames recibidos en el lote y combinar valores.
        # Si hay varios frames con la misma clave, el último valor prevalece.
        for frame in raw_data:
            if not isinstance(frame, dict):
                continue
            values = frame.get("values", {})
            if not isinstance(values, dict):
                continue
            for key, val in values.items():
                try:
                    result[str(key)] = float(val)
                except Exception:
                    try:
                        result[str(key)] = float(str(val))
                    except Exception:
                        continue

        return result


    def _check_connection(self, node_key: str, current_time: float, resultado: Dict[str, Any], emit_event: bool = True) -> bool:
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
                if emit_event:
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
        """Establece la tara global para que el total visible pase a 0.

        Usamos `self._last_total_weight` (el total mostrado por `procesar()`),
        sumado a la tara actual, para reconstruir el peso bruto actual y
        asignarlo como nueva tara. Esto asegura que la tara tomada coincida
        con lo que el usuario ve en pantalla, incluso si hay calibraciones
        por sensor.
        """
        try:
            # Tarar por celda: para cada composite conocido, calculamos su contribución
            # actual (preferir calibración por sensor si existe) y guardamos esa
            # cantidad como tara para que cada celda pase a 0 individualmente.
            for composite in list(self._last_stable_values.keys()):
                try:
                    last_val = float(self._last_stable_values.get(composite, 0.0))
                except Exception:
                    last_val = 0.0

                # Intentar usar calibración por sensor si existe
                contrib = None
                try:
                    contrib = self._map_raw_to_weight(composite, last_val)
                except Exception:
                    contrib = None

                if contrib is None:
                    # Sin calibración por sensor, aplicar slope del sistema sobre el raw
                    try:
                        contrib = float(last_val) * float(self.system_slope)
                    except Exception:
                        contrib = 0.0

                # Guardar la tara de la celda (sobrescribe la existente para que la
                # operación represente un 'poner a cero' de las celdas actuales)
                try:
                    self._tares[composite] = float(contrib)
                except Exception:
                    self._tares[composite] = 0.0

            # Quitar tara global previa para evitar solapamientos
            if 'global' in self._tares:
                try:
                    del self._tares['global']
                except Exception:
                    pass

            try:
                self._save_tara_state()
            except Exception:
                pass

            # Retornar la suma de taras aplicadas
            return sum([float(v) for v in self._tares.values() if isinstance(v, (int, float))])
        except Exception:
            return 0.0

    def reset_tara(self) -> None:
        # Resetear todas las taras por celda y la tara global si existiera
        try:
            self._tares.clear()
            # Guardar estado
            try:
                self._save_tara_state()
            except Exception:
                pass
        except Exception:
            pass
    
    def load_tara_state(self) -> bool:
        """Carga la tara global desde `settings.json` (clave `tara_global`).

        Solo carga la `tara_global` para evitar crear archivos extra.
        """
        try:
            import json
            import os
            from config import SETTINGS_FILE
            path = SETTINGS_FILE
            if not path or not os.path.exists(path):
                return False
            with open(path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            # Cargar mapa completo de taras si existe ('tares' expected as dict)
            if 'tares' in settings and isinstance(settings.get('tares'), dict):
                try:
                    loaded = {}
                    for k, v in settings.get('tares', {}).items():
                        try:
                            loaded[k] = float(v)
                        except Exception:
                            loaded[k] = 0.0
                    self._tares = loaded
                    return True
                except Exception:
                    return False
            # Mantenemos compatibilidad con la clave antigua 'tara_global'
            if 'tara_global' in settings:
                try:
                    self._tares = {'global': float(settings.get('tara_global', 0.0))}
                    return True
                except Exception:
                    return False
        except Exception as e:
            try:
                self._log_to_file(f"Error cargando tara desde settings: {e}")
            except Exception:
                pass
        return False
    
    def _save_tara_state(self) -> bool:
        """Guarda sólo la `tara_global` dentro de `settings.json`.

        Mantiene el resto del `settings.json` intacto si existe.
        """
        try:
            import json
            import os
            from config import SETTINGS_FILE
            path = SETTINGS_FILE
            settings = {}
            if path and os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                except Exception:
                    settings = {}

            # Guardar mapa completo de taras bajo la clave 'tares'
            try:
                settings['tares'] = {k: float(v) for k, v in self._tares.items()}
            except Exception:
                # En caso de fallo, intentar guardar solo la tara global por compatibilidad
                settings['tara_global'] = float(self._tares.get('global', 0.0))
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            try:
                self._log_to_file(f"Error guardando tara en settings: {e}")
            except Exception:
                pass
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

    def get_last_raw_for(self, node_key) -> float:
        """Retorna la última lectura CRUDA registrada para una clave compuesta ('id:ch'),
        un id numérico, o un nombre interno de sensor (ej. 'celda_1').
        """
        # Si es int, buscar la primera clave compuesta que empiece por id:
        try:
            if isinstance(node_key, int):
                matches = [k for k in self._last_raw_readings.keys() if k.startswith(f"{node_key}:")]
                if matches:
                    return self._last_raw_readings.get(matches[0], 0.0)
                return 0.0
        except Exception:
            pass

        # Si es string y contiene ':', usar directo
        try:
            if isinstance(node_key, str):
                if ':' in node_key:
                    return self._last_raw_readings.get(node_key, 0.0)
                # Si corresponde a un nombre interno en nodos_config
                if node_key in self.nodos_config:
                    cfg = self.nodos_config[node_key]
                    composite = f"{cfg.get('id')}:{cfg.get('ch','ch1')}"
                    return self._last_raw_readings.get(composite, 0.0)
                # Buscar cualquier clave que empiece por node_key + ':'
                matches = [k for k in self._last_raw_readings.keys() if k.startswith(f"{node_key}:")]
                if matches:
                    return self._last_raw_readings.get(matches[0], 0.0)
        except Exception:
            pass

        return 0.0
    
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
            "total_tare": sum([float(v) for v in self._tares.values()]) if self._tares else 0.0,
            "sensor_timeout_s": self.SENSOR_TIMEOUT_S
        }
    
    def get_last_total_raw(self) -> float:
        """Retorna la ultima suma total de valores raw (filtrados)."""
        return self._last_total_raw

    # --------------------------------------------------
    # Calibración por sensor (segments / interpolación)
    # --------------------------------------------------
    def set_calibration_segments(self, points: List[tuple], serial: Optional[str] = None, composite: Optional[str] = None):
        """Registra una curva de calibración por segmentos.

        `points` se espera como lista de tuplas (peso, lectura) tal como
        las genera el wizard; se convierte internamente a (reading, weight).
        Se puede asociar por `serial` o por `composite` (id:ch). Si no se
        encuentra objetivo, se guarda bajo la clave del `serial` si se
        pasó o se ignora.
        """
        try:
            # Convertir (weight, reading) -> (reading, weight)
            conv = []
            for item in points:
                try:
                    w = float(item[0])
                    r = float(item[1])
                    conv.append((r, w))
                except Exception:
                    continue
            if not conv:
                return
            conv.sort(key=lambda x: x[0])

            targets = []
            if composite:
                targets.append(composite)
            elif serial:
                # Asociar a todas las claves composites que tengan ese serial
                for comp, s in self._composite_to_serial.items():
                    if s == serial:
                        targets.append(comp)
            # Si no hay targets, almacenar bajo el serial si fue provisto
            if not targets and serial:
                targets.append(serial)

            for t in targets:
                self.sensor_calibrations[t] = {'method': 'segments', 'points': conv}
                self._log_to_file(f"Calibración por segmentos aplicada a {t} con {len(conv)} puntos")
        except Exception as e:
            self._log_to_file(f"Error registrando calibración por segmentos: {e}")

    def _map_raw_to_weight(self, composite: str, raw_value: float) -> Optional[float]:
        """
        Mapea una lectura cruda a peso físico utilizando calibración por segmentos.

        OPTIMIZACIONES:
        1. Calcula pendientes (m) y offsets (b) solo la primera vez.
        2. Extrapolación: Proyecta la curva hacia el infinito para valores fuera de rango
           (usa la primera pendiente para valores bajos y la última para altos).
        """
        try:
            calib = None
            if composite in self.sensor_calibrations:
                calib = self.sensor_calibrations[composite]
            else:
                serial = self._composite_to_serial.get(composite)
                if serial and serial in self.sensor_calibrations:
                    calib = self.sensor_calibrations[serial]

            if not calib or calib.get('method') != 'segments':
                return None

            if '_lookup_table' not in calib:
                pts = calib.get('points', [])
                if not pts:
                    return None
                pts = sorted(pts, key=lambda x: x[0])
                if len(pts) == 1:
                    calib['_lookup_table'] = {'type': 'single', 'val': float(pts[0][1])}
                else:
                    segments = []
                    for i in range(len(pts) - 1):
                        x0, y0 = pts[i]
                        x1, y1 = pts[i + 1]
                        if x1 == x0:
                            m = 0.0
                        else:
                            m = (y1 - y0) / (x1 - x0)
                        b = y0 - (m * x0)
                        segments.append({'limit': x1, 'm': m, 'b': b})
                    calib['_lookup_table'] = {'type': 'multi', 'segments': segments}

            table = calib['_lookup_table']
            r = float(raw_value)
            if table['type'] == 'single':
                return table['val']
            segments = table['segments']
            selected_seg = segments[-1]
            for seg in segments:
                if r <= seg['limit']:
                    selected_seg = seg
                    break
            return (selected_seg['m'] * r) + selected_seg['b']
        except Exception:
            return None


def create_processor(nodos_config: Dict[str, Dict[str, Any]], 
                     median_window: int = 5,
                     ema_alpha: float = 0.3) -> DataProcessor:
    return DataProcessor(
        nodos_config=nodos_config,
        median_window=median_window,
        ema_alpha=ema_alpha
    )
