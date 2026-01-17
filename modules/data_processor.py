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
                 input_unit: str = "t"):
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
        self._last_raw_readings: Dict[str, float] = {}
        # Último valor procesado (estable) por composite (sample & hold)
        self._last_stable_values: Dict[str, float] = {}
        self._last_seen: Dict[str, float] = {}
        self._node_connected_state: Dict[str, bool] = {}
        self._last_total_seen: float = 0.0
        # Mapas para calibración por sensor
        self.sensor_calibrations: Dict[str, Dict[str, Any]] = {}  # key -> {'method':..., 'points':[(raw,weight),...]}
        self._composite_to_serial: Dict[str, Optional[str]] = {}
        
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
            self._last_stable_values[composite] = 0.0
            self._last_seen[composite] = 0.0
            self._node_connected_state[composite] = False
            # Guardar serial si existe en la configuración para mapping de calibración
            serial = cfg.get('serial') if isinstance(cfg, dict) else None
            self._composite_to_serial[composite] = serial
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
        sum_contrib_connected = 0.0
        any_calibrated = False
        # Guarda valores filtrados por nodo (clave compuesta) para distribución posterior
        _valor_filtrado_por_nodo: Dict[str, float] = {}

        for nombre_logico, cfg in self.nodos_config.items():
            node_id = cfg["id"]
            channel = cfg.get("ch", "ch1")
            composite = f"{node_id}:{channel}"
            is_connected = self._check_connection(composite, current_time, resultado)
            # Si el paquete actual contiene dato para este composite, lo usamos
            valor_crudo = 0.0
            if composite in datos_por_nodo:
                original_val = datos_por_nodo[composite]
                try:
                    self._last_raw_readings[composite] = float(original_val)
                except Exception:
                    try:
                        self._last_raw_readings[composite] = float(str(original_val))
                    except Exception:
                        self._last_raw_readings[composite] = 0.0
                # Mantener la lectura cruda original para auditoría/calibración
                valor_crudo = original_val
                # Convertir a float y aplicar multiplicador por sensor (signo/config)
                try:
                    raw_f = float(original_val)
                except Exception:
                    try:
                        raw_f = float(str(original_val))
                    except Exception:
                        raw_f = 0.0

                mult = 1.0
                try:
                    nombre_logico = self._node_to_name.get(composite)
                    cfg_local = self.nodos_config.get(nombre_logico, {}) if nombre_logico else {}
                    if 'sign' in cfg_local:
                        mult = float(cfg_local.get('sign', 1.0))
                    elif cfg_local.get('invert', False):
                        mult = -1.0
                except Exception:
                    mult = 1.0

                # El valor crudo es tomado directamente del sensor y se interpreta
                # según `input_unit`. En configuración actual se usa 't' (toneladas),
                # por lo que no realizamos conversión a kg aquí — todo el procesamiento
                # usa la misma unidad de entrada para mantener consistencia.
                valor_crudo = raw_f * mult
            else:
                # Si no llegaron datos en este ciclo, usamos el último valor estable
                # (Sample & Hold) para evitar resetear a 0 y provocar parpadeos.
                valor_crudo = self._last_raw_readings.get(composite, 0.0)

            # Aplicar filtros (si están activados) sobre el valor actual o retenido
            valor_filtrado = self._filter_value(composite, valor_crudo)

            # Actualizar la memoria estable (hold) solo si hubo dato nuevo
            if composite in datos_por_nodo:
                self._last_stable_values[composite] = valor_filtrado
            # Aplicar calibración por sensor (segments) si existe
            calibrated_value = None
            try:
                calibrated_value = self._map_raw_to_weight(composite, valor_filtrado)
            except Exception:
                calibrated_value = None

            # Si hay calibración por sensor, su contribución usa el valor calibrado (peso)
            if calibrated_value is not None:
                contrib = float(calibrated_value)
                any_calibrated = True
            else:
                contrib = valor_filtrado

            _valor_filtrado_por_nodo[composite] = valor_filtrado
            if is_connected:
                sum_raw_connected += valor_filtrado
                # sum_contrib acumula la suma ya calibrada cuando corresponda
                sum_contrib_connected += contrib
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
        # Ahora aceptamos sums negativas (signo) ya que las lecturas pueden ser
        # negativas por configuración o por orientación de la celda.
        if sum_raw_connected != 0:
            self._last_total_raw = sum_raw_connected

        # 3. Aplicar Formula Lineal al Total: y = mx + b
        # Peso = (Suma_Raw * m) + b
        
        # IMPORTANTE: Si falta algun sensor, la suma es invalida para pesaje preciso
        # pero mostramos lo que hay.
        
        # Si existen contribuciones calibradas (por sensor), preferimos usar
        # la suma calibrada directa como peso bruto. Esto permite que curvas
        # por-sensor (interpolación por segmentos) se reflejen directamente.
        # Si existen contribuciones calibradas por sensor, usar esa suma directa
        if any_calibrated:
            peso_bruto = float(sum_contrib_connected)
        else:
            peso_bruto = (sum_raw_connected * self.system_slope) + self.system_offset
        
        # Aplicar Tara Global
        # La tara ahora se aplica sobre el peso calculado (no sobre raw)
        # O se puede manejar 'b' como (Offset_Zero - Tara).
        # Implementaremos tara simple: Peso_Neto = Peso_Bruto - Tara_Global
        
        tara_global = self._tares.get("global", 0.0)
        peso_neto = peso_bruto - tara_global
        
        # Si no hay sensores aportando raw (suma == 0), devolvemos el último
        # peso calculado para evitar saltos a 0 en la UI entre frames.
        if sum_raw_connected == 0:
            resultado["total"] = round(self._last_total_weight, 3)
        else:
            resultado["total"] = round(peso_neto, 3)
        resultado["total_raw"] = sum_raw_connected
        resultado["total_tare"] = round(tara_global, 3)
        # Actualizar timestamp del total solo si hay datos conectados (evita zeros intermedios)
        if sum_raw_connected != 0:
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
            # Distribuir el peso neto proporcionalmente al aporte raw.
            # Soportamos sums negativas: la proporción preservará el signo.
            if sum_raw_connected != 0:
                for nombre_logico, cfg in self.nodos_config.items():
                    node_id = cfg["id"]
                    channel = cfg.get("ch", "ch1")
                    composite = f"{node_id}:{channel}"
                    sensor_entry = resultado["sensores"].get(nombre_logico)
                    if not sensor_entry:
                        continue
                    if sensor_entry.get("connected"):
                        vf = _valor_filtrado_por_nodo.get(composite, 0.0)
                        # Si existe calibracion por sensor, utilizar el valor calibrado directo
                        calib_v = None
                        try:
                            calib_v = self._map_raw_to_weight(composite, vf)
                        except Exception:
                            calib_v = None
                        if calib_v is not None:
                            sensor_entry["valor"] = round(float(calib_v), 3)
                        else:
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
        """Establece la tara global para que el total visible pase a 0.

        Usamos `self._last_total_weight` (el total mostrado por `procesar()`),
        sumado a la tara actual, para reconstruir el peso bruto actual y
        asignarlo como nueva tara. Esto asegura que la tara tomada coincida
        con lo que el usuario ve en pantalla, incluso si hay calibraciones
        por sensor.
        """
        try:
            tara_actual = self._tares.get("global", 0.0)
            # peso_bruto_actual = peso_neto_visible + tara_actual
            peso_bruto_actual = float(self._last_total_weight or 0.0) + float(tara_actual)
            self._tares["global"] = peso_bruto_actual
            # opcional: guardar estado de taras
            try:
                self._save_tara_state()
            except Exception:
                pass
            return peso_bruto_actual
        except Exception:
            return 0.0

    def reset_tara(self) -> None:
        self._tares["global"] = 0.0
    
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
            if 'tara_global' in settings:
                try:
                    self._tares['global'] = float(settings.get('tara_global', 0.0))
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

            # Guardar sólo la tara global
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
            "total_tare": sum(self._tares.values()),
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
            # -----------------------------------------------------------
            # 1. Búsqueda del objeto de calibración (Lógica original)
            # -----------------------------------------------------------
            calib = None
            if composite in self.sensor_calibrations:
                calib = self.sensor_calibrations[composite]
            else:
                # Intenta buscar por Num serial si no encuentra por composite
                serial = self._composite_to_serial.get(composite)
                if serial and serial in self.sensor_calibrations:
                    calib = self.sensor_calibrations[serial]
            
            # Si no hay calibración o el método no es 'segments', salir.
            if not calib or calib.get('method') != 'segments':
                return None

            # -----------------------------------------------------------
            # 2. Generación de Tabla de Búsqueda (Se ejecuta SOLO UNA VEZ)
            # -----------------------------------------------------------
            # Verificamos si ya calculamos la tabla para no repetir el trabajo.
            if '_lookup_table' not in calib:
                pts = calib.get('points', [])
                if not pts:
                    return None
                
                # Se ordenan los puntos por valor crudo (eje X) de menor a mayor
                pts = sorted(pts, key=lambda x: x[0])
                
                # Caso especial: Si solo hay 1 punto, actúa como un offset simple
                if len(pts) == 1:
                    calib['_lookup_table'] = {'type': 'single', 'val': float(pts[0][1])}
                else:
                    segments = []
                    # Pre-calcular pendiente (m) y offset (b) para cada tramo
                    # Fórmula: y = mx + b  ->  b = y - mx
                    for i in range(len(pts) - 1):
                        x0, y0 = pts[i]
                        x1, y1 = pts[i + 1]
                        
                        # Protección contra división por cero (si dos puntos tienen el mismo X)
                        if x1 == x0:
                            m = 0.0
                        else:
                            m = (y1 - y0) / (x1 - x0)
                        
                        b = y0 - (m * x0) # Despeje del offset
                        
                        # Guardar: límite superior del tramo, pendiente y offset
                        segments.append({
                            'limit': x1, # Hasta qué valor raw aplica este segmento
                            'm': m,
                            'b': b
                        })
                    
                    # Guardar la tabla optimizada dentro del mismo objeto de calibración
                    calib['_lookup_table'] = {'type': 'multi', 'segments': segments}

            # -----------------------------------------------------------
            # 3. Cálculo Rápido (Se ejecuta en CADA lectura)
            # -----------------------------------------------------------
            table = calib['_lookup_table']
            r = float(raw_value)

            # Si es calibración de un solo punto
            if table['type'] == 'single':
                return table['val']

            segments = table['segments']
            
            # --- Selección de Segmento y Extrapolación ---
            
            # Por defecto, seleccionamos el último segmento.
            # Esto maneja automáticamente la "Extrapolación Alta":
            # si r > todos los límites, el bucle for termina sin break y usamos el último.
            selected_seg = segments[-1]

            # Buscamos si el valor cae dentro de un segmento anterior (Interpolación o Extrapolación Baja)
            for seg in segments:
                if r <= seg['limit']:
                    selected_seg = seg
                    break
            
            # NOTA SOBRE EXTRAPOLACIÓN BAJA:
            # Si 'r' es menor que el primer punto de calibración, la condición (r <= seg['limit'])
            # se cumple inmediatamente en la primera iteración (index 0).
            # Por tanto, se usa la pendiente y offset del primer tramo para proyectar hacia atrás.

            # Aplicar la ecuación de la recta: y = mx + b
            return (selected_seg['m'] * r) + selected_seg['b']

        except Exception:
            # En caso de error numérico, retornamos None para no romper el flujo
            return None


def create_processor(nodos_config: Dict[str, Dict[str, Any]], 
                     median_window: int = 5,
                     ema_alpha: float = 0.3) -> DataProcessor:
    return DataProcessor(
        nodos_config=nodos_config,
        median_window=median_window,
        ema_alpha=ema_alpha
    )
