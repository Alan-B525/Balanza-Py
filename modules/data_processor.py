# -*- coding: utf-8 -*-
"""
data_processor.py - Procesador de Datos para Sistema de Pesaje Industrial
"""

from collections import deque
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import time
import statistics
import math


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
    MA_WINDOW_SIZE = 10  # Ventana de media móvil simple (cantidad de muestras)
    
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
        # Buffers de media móvil por canal (carga y ángulos)
        self._ma_buffers: Dict[str, deque] = {}
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
        self._last_raw_readings.clear()
        self._ma_buffers.clear()
        self._last_seen.clear()
        self._node_connected_state.clear()
        self._composite_to_serial.clear()
        self._load_keys.clear()
        
        self._parsed_nodes_config = []

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

            mult = 1.0
            try:
                if 'sign' in cfg:
                    mult = float(cfg.get('sign', 1.0))
                elif cfg.get('invert', False):
                    mult = -1.0
            except Exception:
                mult = 1.0

            convert_rad = bool(cfg.get('convert_rad_to_deg', False))
            serial = cfg.get('serial')
            
            comp_load = f"{node_id}:{ch_load}"
            comp_angles = [f"{node_id}:{ch}" for ch in ch_angles]

            parsed_cfg = {
                'nombre_logico': nombre_logico,
                'node_id': node_id,
                'ch_load': ch_load,
                'comp_load': comp_load,
                'ch_angles': ch_angles,
                'comp_angles': comp_angles,
                'load_enabled': load_enabled,
                'mult': mult,
                'convert_rad': convert_rad,
                'serial': serial,
                'cfg_dict': cfg
            }
            self._parsed_nodes_config.append(parsed_cfg)

            if load_enabled:
                self._node_to_name[comp_load] = nombre_logico
                self._median_buffers[comp_load] = deque(maxlen=self.median_window)
                self._ema_values[comp_load] = None
                self._tares[comp_load] = 0.0
                self._last_stable_values[comp_load] = 0.0
                self._last_seen[comp_load] = 0.0
                self._node_connected_state[comp_load] = False
                self._load_keys.add(comp_load)
                self._composite_to_serial[comp_load] = serial

            for idx, comp_angle in enumerate(comp_angles, start=1):
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

    # =========================================================================
    # MEDIA MÓVIL SIMPLE (SMA) — Ventana de 10 muestras
    # =========================================================================

    def _extract_all_samples(self, raw_data: List[Dict[str, Any]]) -> Dict[str, List[float]]:
        """Extrae TODAS las muestras individuales por key, preservando orden temporal.

        A diferencia de _extract_node_data() que solo retiene el último valor,
        este método conserva cada muestra de cada frame para alimentar la media móvil.
        """
        result: Dict[str, List[float]] = {}
        if not raw_data:
            return result

        for frame in raw_data:
            if not isinstance(frame, dict):
                continue
            values = frame.get("values", {})
            if not isinstance(values, dict):
                continue
            for key, val in values.items():
                try:
                    fval = float(val)
                except Exception:
                    continue
                skey = str(key)
                if skey not in result:
                    result[skey] = []
                result[skey].append(fval)

        return result

    def _feed_moving_average(self, key: str, value: float) -> float:
        """Alimenta el buffer de media móvil con un nuevo valor y retorna el promedio actual.

        El buffer es un deque(maxlen=MA_WINDOW_SIZE). Al llenarse, el valor más
        viejo se descarta automáticamente.
        """
        if key not in self._ma_buffers:
            self._ma_buffers[key] = deque(maxlen=self.MA_WINDOW_SIZE)
        buf = self._ma_buffers[key]
        buf.append(value)
        return sum(buf) / len(buf)

    def _get_moving_average(self, key: str) -> Optional[float]:
        """Retorna el promedio actual sin agregar nuevos valores.

        Usado para sample-and-hold: cuando no llegan datos nuevos,
        se repite el último promedio sin contaminar el buffer.
        """
        buf = self._ma_buffers.get(key)
        if buf and len(buf) > 0:
            return sum(buf) / len(buf)
        return None
    
    def procesar(self, raw_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        resultado = {
            "sensores": {},
            "total": 0.0,
            "total_raw": 0.0,
            "total_tare": 0.0,
            "angle_val": 0.0,
            "angles": [],
            "disconnect_events": [],
            "any_disconnected": False
        }
        
        current_time = time.time()
        datos_por_nodo = self._extract_node_data(raw_data)

        # Extraer TODAS las muestras individuales y alimentar buffers de media móvil
        all_samples = self._extract_all_samples(raw_data)
        ma_current: Dict[str, float] = {}
        for key, samples in all_samples.items():
            avg = 0.0
            for sample in samples:
                avg = self._feed_moving_average(key, sample)
            ma_current[key] = avg  # Último promedio después de alimentar todas las muestras

        for node_key in self._node_to_name.keys():
             if node_key in datos_por_nodo:
                self._last_seen[node_key] = current_time
                if not self._node_connected_state.get(node_key, False):
                    self._node_connected_state[node_key] = True
                    nombre = self._node_to_name.get(node_key, f"Nodo {node_key}")
                    if node_key in self._load_keys:
                        resultado.setdefault("logs", []).append(f"Sensor {nombre} conectado")
        
        sum_raw_connected = 0.0
        sum_contrib_connected = 0.0
        any_calibrated = False
        
        _valor_filtrado_por_key: Dict[str, float] = {}
        _contrib_por_key: Dict[str, float] = {}
        angles_ordered: List[float] = []

        for p_cfg in getattr(self, '_parsed_nodes_config', []):
            nombre_logico = p_cfg['nombre_logico']
            node_id = p_cfg['node_id']
            comp_load = p_cfg['comp_load']
            comp_angles = p_cfg['comp_angles']
            load_enabled = p_cfg['load_enabled']
            mult = p_cfg['mult']
            convert_rad = p_cfg['convert_rad']

            node_angles: List[float] = []

            if load_enabled:
                is_connected_load = self._check_connection(comp_load, current_time, resultado, emit_event=True)
                val_load = 0.0
                if comp_load in datos_por_nodo:
                    try:
                        raw_val = float(datos_por_nodo[comp_load])
                    except Exception:
                        raw_val = 0.0
                    self._last_raw_readings[comp_load] = raw_val
                    # Usar media móvil (ya alimentada con todas las muestras del lote)
                    val_load = ma_current.get(comp_load, raw_val) * mult
                else:
                    # Sample-and-hold: repetir último promedio MA sin alimentar buffer
                    ma_val = self._get_moving_average(comp_load)
                    val_load = (ma_val if ma_val is not None else 0.0) * mult

                val_load_filt = self._filter_value(comp_load, val_load)
                if comp_load in datos_por_nodo:
                    self._last_stable_values[comp_load] = val_load_filt

                calibrated_load = None
                try:
                    calibrated_load = self._map_raw_to_weight(comp_load, val_load_filt)
                except Exception:
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

            for comp_angle in comp_angles:
                self._check_connection(comp_angle, current_time, resultado, emit_event=False)
                val_angle = 0.0
                if comp_angle in datos_por_nodo:
                    try:
                        raw_angle = float(datos_por_nodo[comp_angle])
                        if convert_rad:
                            raw_angle = math.degrees(raw_angle)
                    except Exception:
                        raw_angle = 0.0
                    self._last_raw_readings[comp_angle] = raw_angle
                    # Usar media móvil para ángulos (ya alimentada)
                    # Nota: si convert_rad, los valores en ma_current son crudos (radianes)
                    # pero la MA de radianes convertida a grados = grados de la MA (operación lineal)
                    ma_angle = ma_current.get(comp_angle)
                    if ma_angle is not None:
                        val_angle = math.degrees(ma_angle) if convert_rad else ma_angle
                    else:
                        val_angle = raw_angle
                else:
                    # Sample-and-hold: repetir último promedio MA
                    ma_val = self._get_moving_average(comp_angle)
                    if ma_val is not None:
                        val_angle = math.degrees(ma_val) if convert_rad else ma_val
                    else:
                        val_angle = self._last_raw_readings.get(comp_angle, 0.0)

                node_angles.append(val_angle)
                angles_ordered.append(val_angle)

            if load_enabled:
                tare_val = self._tares.get(comp_load, 0.0)
                sensor_net = _contrib_por_key.get(comp_load, 0.0) - tare_val
                val_load_filt = _valor_filtrado_por_key.get(comp_load, 0.0)
                val_load_raw = self._last_raw_readings.get(comp_load, 0.0)
                is_connected_load = self._node_connected_state.get(comp_load, False)

                resultado["sensores"][nombre_logico] = {
                    "valor": round(sensor_net, 3),
                    "raw": round(val_load_filt, 3),
                    "crudo": round(val_load_raw, 3),
                    "bruto": round(_contrib_por_key.get(comp_load, 0.0), 3),
                    "angles": [round(a, 2) for a in node_angles],
                    "id": node_id,
                    "key": comp_load,
                    "connected": is_connected_load,
                    "last_seen": self._last_seen.get(comp_load, 0.0)
                }

        if sum_raw_connected != 0:
            self._last_total_raw = sum_raw_connected

        if any_calibrated:
            peso_bruto = float(sum_contrib_connected)
        else:
            peso_bruto = (sum_raw_connected * self.system_slope) + self.system_offset
        
        resultado["total_gross"] = round(peso_bruto, 3)

        tara_total = 0.0
        for k, v in self._tares.items():
            if k in self._load_keys:
                try:
                    tara_total += float(v)
                except Exception:
                    pass
        
        peso_neto = peso_bruto - tara_total

        if sum_raw_connected == 0 and not resultado["any_disconnected"]:
             resultado["total"] = round(self._last_total_weight, 3)
        else:
             resultado["total"] = round(peso_neto, 3)
             if sum_raw_connected != 0:
                 self._last_total_weight = peso_neto
                 self._last_total_seen = current_time

        resultado["total_raw"] = sum_raw_connected
        resultado["total_tare"] = round(tara_total, 3)
        resultado["total_last_seen"] = self._last_total_seen
        
        valid_angles = []
        for p_cfg in getattr(self, '_parsed_nodes_config', []):
            for comp_angle in p_cfg['comp_angles']:
                if comp_angle in datos_por_nodo or self._node_connected_state.get(comp_angle, False):
                    valid_angles.append(self._last_raw_readings.get(comp_angle, 0.0))

        if valid_angles:
            try:
                sum_sin = 0.0
                sum_cos = 0.0
                for a in valid_angles:
                    rad = math.radians(a)
                    sum_sin += math.sin(rad)
                    sum_cos += math.cos(rad)
                mean_rad = math.atan2(sum_sin, sum_cos)
                resultado["angle_val"] = round(math.degrees(mean_rad), 2)
            except Exception:
                resultado["angle_val"] = 0.0
        else:
            resultado["angle_val"] = 0.0

        resultado["angles"] = [round(a, 2) for a in angles_ordered]
        
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
                self._log_to_file(f"Erro ao carregar tara das configurações: {e}")
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
                self._log_to_file(f"Erro ao salvar tara nas configurações: {e}")
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
                self._log_to_file(f"Calibração por segmentos aplicada a {t} com {len(conv)} pontos")
        except Exception as e:
            self._log_to_file(f"Erro ao registrar calibração por segmentos: {e}")

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
