"""
sensor_driver.py - Driver Industrial "Acorazado" (V8)
Basado en pruebas de campo exitosas.

ESTRATEGIA (Recuperación y Robustez):
1. Silencio Radial: Apagar Beacon y esperar 6s para que los nodos "zombies" despierten.
2. Persistencia Agresiva: Bombardear con 'SetToIdle' antes de hacer Ping.
3. Tolerancia a Fallos: Si la librería MSCL falla al configurar (bug v67), se salta el paso.
4. Salida Limpia: Intenta dormir a los nodos al desconectar para ahorrar batería.
"""

import sys
import os
import time
import threading
import traceback
from typing import List, Dict, Any, Optional, Set
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

# --- CONFIGURACIÓN DE RUTA MSCL ---
_current_dir = os.path.dirname(os.path.abspath(__file__))
_mscl_path = os.path.join(os.path.dirname(_current_dir), 'MSCL', 'x64', 'Release')
if _mscl_path not in sys.path and os.path.exists(_mscl_path):
    sys.path.insert(0, _mscl_path)

try:
    import mscl
    MSCL_AVAILABLE = True
except ImportError:
    mscl = None
    MSCL_AVAILABLE = False

try:
    import config as app_config
except Exception:
    app_config = None

RUNTIME_TUNING = getattr(app_config, 'RUNTIME_TUNING', {}) if app_config is not None else {}
# Sobreescribir con valores de settings.json si existen (tienen prioridad sobre config.py)
try:
    from config import load_settings as _load_settings
    _settings = _load_settings()
    _rt_from_file = _settings.get('runtime_tuning', {})
    if _rt_from_file:
        RUNTIME_TUNING = {**RUNTIME_TUNING, **_rt_from_file}
except Exception:
    pass

from .interfaces import ISistemaPesaje, ConnectionState

@dataclass
class AggregatedFrame:
    timestamp_ns: int
    readings: Dict[str, float] = field(default_factory=dict)
    rssi_map: Dict[int, int] = field(default_factory=dict)
    complete: bool = False
    creation_time: float = field(default_factory=time.time)
    
    def is_complete(self, expected_keys: Set[str]) -> bool:
        return expected_keys.issubset(set(self.readings.keys()))

# =============================================================================
# CLASE PRINCIPAL DEL DRIVER
# =============================================================================

class MSCLDriver(ISistemaPesaje):

    # Configuración de Hardware
    BAUD_RATE = int(getattr(app_config, 'BAUDRATE', 3000000))
    DATA_TIMEOUT_MS = int(RUNTIME_TUNING.get('gateway_getdata_timeout_ms', 30))
    FRAME_TIMEOUT_S = float(RUNTIME_TUNING.get('gateway_frame_timeout_s', 0.05))
    TIMESTAMP_TOLERANCE_NS = int(RUNTIME_TUNING.get('gateway_timestamp_tolerance_ns', 20_000_000))
    
    # Configuración
    RECOVERY_TIMEOUT_S = 30  # Tiempo máx intentando despertar un nodo

    def __init__(self, nodos_config: Optional[Dict] = None, use_sensor_config: bool = True, avoid_eeprom: bool = True):
        if not MSCL_AVAILABLE: raise ImportError("Librería MSCL no encontrada.")
        
        self.nodos_config = nodos_config or {}
        
        # Base de datos de configuración (Qué esperamos leer)
        self._config_node_ids: Set[int] = set()
        self._config_data_keys: Set[str] = set()
        
        # Estado dinámico
        self._active_node_ids: Set[int] = set() # Nodos confirmados en la red
        self._connection = None
        self._base_station = None
        self._network = None  # Objeto SyncSamplingNetwork
        
        self._state = ConnectionState.DISCONNECTED
        self._lock = threading.RLock()
        
        # Buffer de agregación de tramas (para sincronizar datos de varios nodos)
        self._frame_buffer: Dict[int, AggregatedFrame] = {}
        self._value_cache: Dict[str, deque] = {} # Para estadísticas o debug
        # Callback opcional para informar progreso a la UI
        self._progress_cb = None
        self._port_autodetected_cb = None

        self._parse_config()
        # Último recuento de nodos recuperados tras intentar conectar
        self._last_recovered_count = 0

    def set_port_autodetected_callback(self, cb):
        """Registra un callback para informar la autodetección de un puerto COM."""
        try:
            if cb is None:
                self._port_autodetected_cb = None
            elif callable(cb):
                self._port_autodetended_cb = cb  # Mantener compatibilidad si hay typos
                self._port_autodetected_cb = cb
        except Exception:
            self._port_autodetected_cb = None

    def set_progress_callback(self, cb):
        """Registra un callback callable(msg: str) para progreso de conexión."""
        try:
            if cb is None:
                self._progress_cb = None
            elif callable(cb):
                self._progress_cb = cb
        except Exception:
            self._progress_cb = None

    def _emit_progress(self, msg: str) -> None:
        """Enviar mensaje de progreso tanto al logger como al callback si existe."""
        try:
            self._log(msg)
        except Exception:
            pass
        try:
            if self._progress_cb:
                try:
                    self._progress_cb(msg)
                except Exception:
                    pass
        except Exception:
            pass

    def _parse_config(self):
        """Traduce el diccionario de configuración a estructuras internas."""
        for name, cfg in self.nodos_config.items():
            if not isinstance(cfg, dict):
                cfg = {}
            nid = cfg.get('id', 0)
            if nid <= 0: continue
            self._config_node_ids.add(nid)

            ch_load = cfg.get('ch_load', cfg.get('ch', 'ch1'))
            ch_angles = cfg.get('ch_angles')
            if not isinstance(ch_angles, list):
                ch_single = cfg.get('ch_angle', 'ch2')
                ch_angles = [ch_single]
            ch_angles = [str(ch).strip() for ch in ch_angles if str(ch).strip()]
            load_enabled = bool(cfg.get('load_enabled', True))

            channels = []
            if load_enabled:
                channels.append(ch_load)
            channels.extend(ch_angles)
            for ch in dict.fromkeys(channels):
                key = f"{nid}:{ch}"
                self._config_data_keys.add(key)
                self._value_cache[key] = deque(maxlen=10)

    def _log(self, msg):
        """Wrapper de log para integrarse con el sistema o imprimir."""
        try:
            from . import logger
            logger.info(f"[MSCL] {msg}")
        except Exception:
            print(f"[MSCL] {msg}")

    # =========================================================================
    # LÓGICA DE CONEXIÓN
    # =========================================================================

    def conectar(self, puerto: str) -> bool:
        # 1. Comprobar/marcar estado de conexión rápido con lock
        with self._lock:
            if self._state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING, ConnectionState.CONNECTING):
                return self._state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING)
            self._state = ConnectionState.CONNECTING
            self._emit_progress(f"Iniciando Conexão em {puerto} @ {self.BAUD_RATE}...")

        # Validación temprana de puerto y autodetección
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        available_ports = [p.device for p in ports]
        available_ports_upper = {str(p).strip().upper() for p in available_ports}

        target_port = puerto
        autodetect_triggered = False

        normalized_requested = str(puerto or '').strip().upper()
        if not normalized_requested or normalized_requested not in available_ports_upper:
            self._emit_progress(f"Porta {puerto} indisponível. Iniciando autodetección...")
            autodetect_triggered = True
        else:
            # Probar puerto configurado con un ping rápido
            self._emit_progress(f"Testando porta configurada {puerto}...")
            try:
                temp_conn = mscl.Connection.Serial(puerto, self.BAUD_RATE)
                temp_bs = mscl.BaseStation(temp_conn)
                if temp_bs.ping():
                    self._emit_progress(f"BaseStation encontrada em {puerto}!")
                    temp_conn.disconnect()
                else:
                    self._emit_progress(f"BaseStation no responde en {puerto}. Buscando alternativas...")
                    temp_conn.disconnect()
                    autodetect_triggered = True
            except Exception as e:
                self._emit_progress(f"Erro ao testar {puerto}: {e}. Buscando alternativas...")
                autodetect_triggered = True

        if autodetect_triggered:
            # Buscar BaseStation escaneando todos los puertos
            sorted_ports = []
            for p in ports:
                desc = str(p.description or '').lower()
                device = p.device
                if device.upper() == normalized_requested:
                    continue  # Ya lo probamos
                
                # Priorizar los puertos que tengan descripciones asociadas a Silicon Labs CP210x o UART
                if 'silicon' in desc or 'cp210' in desc or 'uart' in desc or 'bridge' in desc:
                    sorted_ports.insert(0, device)
                else:
                    sorted_ports.append(device)
            
            detected_port = None
            for p in sorted_ports:
                self._emit_progress(f"Escaneando porta {p}...")
                try:
                    temp_conn = mscl.Connection.Serial(p, self.BAUD_RATE)
                    temp_bs = mscl.BaseStation(temp_conn)
                    if temp_bs.ping():
                        self._emit_progress(f"BaseStation detectada con éxito en {p}!")
                        detected_port = p
                        temp_conn.disconnect()
                        break
                    temp_conn.disconnect()
                except Exception:
                    pass
            
            if detected_port:
                target_port = detected_port
                self._emit_progress(f"Autoconexão: Mudando porta serial para {target_port}")
                # Notificar callback de autodetección
                if getattr(self, '_port_autodetected_cb', None):
                    try:
                        self._port_autodetected_cb(target_port)
                    except Exception:
                        pass
            else:
                self._emit_progress("Autodetección finalizada: nenhuma BaseStation foi encontrada.")
                # Si falló la autodetección y el puerto original no estaba disponible, abortamos
                if normalized_requested not in available_ports_upper:
                    self.desconectar()
                    return False
                self._emit_progress(f"Tentando continuar con la porta original {puerto} como último recurso...")

        try:
            # 2. Conexión Física (con el lock para asegurar creación segura de objetos)
            with self._lock:
                if self._state == ConnectionState.DISCONNECTED:
                    return False
                self._connection = mscl.Connection.Serial(target_port, self.BAUD_RATE)
                self._base_station = mscl.BaseStation(self._connection)

            # 3. SILENCIO RADIAL (CRÍTICO)
            self._emit_progress("Passo 1: Silenciando rede (6s)...")
            try:
                with self._lock:
                    if self._base_station:
                        self._base_station.disableBeacon()
            except Exception:
                pass
            
            # Dormir SIN mantener el lock para evitar bloquear esta_conectado() o desconectar()!
            time.sleep(6)

            # Verificar si fue cancelado durante el sleep
            with self._lock:
                if self._state == ConnectionState.DISCONNECTED or not self._base_station:
                    self._emit_progress("Conexão cancelada durante o silêncio radial.")
                    return False
                self._network = mscl.SyncSamplingNetwork(self._base_station)

            # 3.5 ACTIVAR BEACON PARA DESPERTAR NODOS EN SLEEP
            self._emit_progress("Passo 2: Ativando Beacon para despertar nós (sleep)...")
            try:
                with self._lock:
                    if self._base_station:
                        self._base_station.enableBeacon()
            except Exception as e:
                self._log(f"Aviso: Não foi posible ativar beacon: {e}")
            
            time.sleep(1) # Pequeña espera para estabilizar red

            # 4. GESTIÓN Y RECUPERACIÓN DE NODOS
            nodos_recuperados = 0
            if not self._config_node_ids:
                self._emit_progress("AVISO: Nenhum nó configurado em settings.json.")

            for nid in self._config_node_ids:
                # Comprobar cancelación
                with self._lock:
                    if self._state == ConnectionState.DISCONNECTED or not self._base_station:
                        self._emit_progress("Conexão cancelada durante a recuperação de nós.")
                        return False
                
                self._emit_progress(f"Tentando recuperar nó {nid}...")
                if self._recuperar_y_preparar_nodo(nid):
                    self._emit_progress(f"Nó {nid} recuperado.")
                    nodos_recuperados += 1
                else:
                    self._emit_progress(f"Nó {nid} NÃO recuperado.")
            
            with self._lock:
                if self._state == ConnectionState.DISCONNECTED or not self._base_station:
                    self._emit_progress("Conexão cancelada antes do início de amostragem.")
                    return False

            if nodos_recuperados == 0 and self._config_node_ids:
                self._log("ERRO: Não foi posible conectar a ningún nó configurado.")
                self.desconectar()
                return False

            # Si la recuperación fue parcial, intentar reset del beacon/base station y reintentar nodos faltantes
            total_expected = len(self._config_node_ids) if self._config_node_ids else 0
            if total_expected and nodos_recuperados < total_expected:
                with self._lock:
                    missing = set(self._config_node_ids) - set(self._active_node_ids)
                if missing:
                    self._emit_progress(f"Conexão parcial ({nodos_recuperados}/{total_expected}). Tentando reset do beacon e reintentar...")
                    try:
                        with self._lock:
                            if self._base_station:
                                try: self._base_station.disableBeacon()
                                except Exception: pass
                        time.sleep(1.0)
                        with self._lock:
                            if self._base_station and hasattr(self._base_station, 'enableBeacon'):
                                try: self._base_station.enableBeacon()
                                except Exception: pass
                    except Exception:
                        pass

                    # Recrear la conexión física si la base station no responde
                    try:
                        with self._lock:
                            if self._state == ConnectionState.DISCONNECTED:
                                return False
                            if self._connection:
                                try: self._connection.disconnect()
                                except Exception: pass
                            self._connection = mscl.Connection.Serial(puerto, self.BAUD_RATE)
                            self._base_station = mscl.BaseStation(self._connection)
                            self._network = mscl.SyncSamplingNetwork(self._base_station)
                    except Exception:
                        pass

                    # Reintentar nodos faltantes
                    for nid in list(missing):
                        with self._lock:
                            if self._state == ConnectionState.DISCONNECTED or not self._base_station:
                                return False
                        try:
                            self._emit_progress(f"Tentando novamente o nó {nid} após reset do beacon...")
                            if self._recuperar_y_preparar_nodo(nid):
                                self._emit_progress(f"Nó {nid} recuperado após reset.")
                                nodos_recuperados += 1
                        except Exception:
                            continue

            # 5. APLICAR CONFIGURACIÓN A LA RED
            self._emit_progress("Passo 3: Aplicando configuração de rede ao Gateway...")
            try:
                with self._lock:
                    if self._state == ConnectionState.DISCONNECTED or not self._network:
                        return False
                    self._network.applyConfiguration()
            except Exception as e:
                self._log(f"Aviso: falha ao aplicar configuração de rede: {e}")

            # 6. INICIAR MUESTREO
            self._emit_progress(f"Passo 4: Iniciando amostragem ({nodos_recuperados} nós)...")
            try:
                with self._lock:
                    if self._state == ConnectionState.DISCONNECTED or not self._network:
                        return False
                    self._network.startSampling()
                self._emit_progress(">>> REDE OPERACIONAL (Beacon Ativo) <<<")
            except Exception as e:
                self._log(f"Erro crítico ao iniciar rede: {e}")
                self.desconectar()
                return False

            with self._lock:
                if self._state == ConnectionState.DISCONNECTED:
                    return False
                self._state = ConnectionState.SAMPLING
                self._last_recovered_count = nodos_recuperados

            if self._config_node_ids:
                return nodos_recuperados == len(self._config_node_ids)
            return True

        except Exception as e:
            self._emit_progress(f"Falha geral na conexão: {e}")
            self._emit_progress(traceback.format_exc())
            self.desconectar()
            return False

    def get_recovered_count(self) -> int:
        """Devuelve el último recuento de nodos recuperados tras conectar()."""
        try:
            return int(getattr(self, '_last_recovered_count', 0) or 0)
        except Exception:
            return 0

    def _set_node_idle(self, node, node_id: int, timeout_ms: int = 300) -> bool:
        """Envía setToIdle y espera confirmación del SetToIdleStatus."""
        try:
            status = node.setToIdle()
            # Evitar bucles infinitos si la librería no completa el estado.
            # complete(timeout_ms) ya espera internamente; limitamos intentos.
            max_attempts = 10
            attempts = 0
            while not status.complete(timeout_ms):
                attempts += 1
                if attempts >= max_attempts:
                    self._log(f"[{node_id}] setToIdle: timeout após {max_attempts} tentativas")
                    return False
            result = status.result()
            if result == mscl.SetToIdleStatus.setToIdleResult_success:
                self._log(f"[{node_id}] setToIdle: éxito")
                return True
            elif result == mscl.SetToIdleStatus.setToIdleResult_canceled:
                self._log(f"[{node_id}] setToIdle: cancelado")
                return False
            else:
                self._log(f"[{node_id}] setToIdle: falló (resultado={result})")
                return False
        except Exception as e:
            self._log(f"[{node_id}] setToIdle excepción: {e}")
            return False

    def _recuperar_y_preparar_nodo(self, node_id: int) -> bool:
        """
        Busca, detiene y agrega el nodo a la red.
        Maneja nodos dormidos y bugs de librería.
        """
        self._log(f"[{node_id}] Tentando recuperar controle...")
        
        with self._lock:
            if not self._base_station:
                return False
            node = mscl.WirelessNode(node_id, self._base_station)
        
        start_time = time.time()
        encontrado = False

        # Bucle de persistencia para despertar nodos dormidos
        attempts = 0
        while (time.time() - start_time) < self.RECOVERY_TIMEOUT_S:
            attempts += 1
            
            with self._lock:
                if self._state == ConnectionState.DISCONNECTED or not self._base_station:
                    return False

            try:
                # Mandar Idle aunque no responda ping
                self._set_node_idle(node, node_id)

                # Verificar si está vivo mediante ping
                try:
                    if node.ping().success():
                        self._log(f"[{node_id}] CONTATO! Nó parado.")
                        self._set_node_idle(node, node_id)  # Asegurar estado Idle
                        encontrado = True
                        break
                except Exception:
                    # ping falló
                    pass

                # Fallback: cada 8 intentos verificar descubrimientos pasivos
                if attempts % 8 == 0:
                    try:
                        self._log(f"[{node_id}] Ping falló; verificando descubrimientos pendientes...")
                        with self._lock:
                            if not self._base_station:
                                return False
                            discoveries = self._base_station.getNodeDiscoveries()
                        for disc in discoveries:
                            try:
                                if disc.nodeAddress() == node_id:
                                    self._log(f"[{node_id}] Nodo detectado via getNodeDiscoveries().")
                                    encontrado = True
                                    break
                            except Exception:
                                continue
                        if encontrado:
                            break
                    except Exception as e:
                        self._log(f"[{node_id}] getNodeDiscoveries falló: {e}")

            except Exception:
                pass

            time.sleep(0.2) # Pequeña pausa para no saturar puerto

        if not encontrado:
            self._log(f"[{node_id}] ERRO: Não respondeu após {self.RECOVERY_TIMEOUT_S}s.")
            return False

        # Configuración gestionada por SensorConnect — no re-configurar desde aquí
        self._log(f"[{node_id}] Configuración gestionada por SensorConnect. Saltando re-configuración.")

        # Agregar a la red
        try:
            with self._lock:
                if self._state == ConnectionState.DISCONNECTED or not self._network:
                    return False
                self._network.addNode(node)
                self._active_node_ids.add(node_id)
            self._log(f"[{node_id}] Adicionado à rede de amostragem.")
            return True
        except Exception as e:
            self._log(f"[{node_id}] Error al agregar a red: {e}")
            return False

    # =========================================================================
    # DESCONEXIÓN
    # =========================================================================

    def desconectar(self):
        """Cierra conexión intentando dejar los nodos en IDLE."""
        with self._lock:
            self._log("Iniciando desconexão...")
            
            # 1. Intentar detener nodos individualmente (si es posible)
            if self._base_station and self._active_node_ids:
                self._log(f"Enviando comando STOP para {len(self._active_node_ids)} nós...")
                for nid in list(self._active_node_ids):
                    try:
                        node = mscl.WirelessNode(nid, self._base_station)
                        node.setToIdle()
                    except Exception:
                        pass # Si falla, no importa, ya lo intentamos

            # 2. Apagar Beacon (Fundamental para detener sincronización)
            if self._base_station:
                try:
                    self._base_station.disableBeacon()
                    self._log("Beacon desativado.")
                except Exception:
                    pass
            
            # 3. Cerrar conexión física
            if self._connection:
                try:
                    self._connection.disconnect()
                except Exception:
                    pass

            self._active_node_ids.clear()
            self._frame_buffer.clear()
            self._base_station = None
            self._connection = None
            self._network = None
            
            self._state = ConnectionState.DISCONNECTED
            self._log("Sistema desconectado.")

    # =========================================================================
    # LECTURA DE DATOS
    # =========================================================================

    def obtener_datos(self) -> List[Dict[str, Any]]:
        """
        Método llamado periódicamente por DataProcessor.
        Lee datos del buffer del Gateway y los agrega en tramas sincronizadas.
        """
        with self._lock:
            if not self._base_station or self._state != ConnectionState.SAMPLING:
                return []

            # Leer del buffer interno del Gateway
            try:
                sweeps = self._base_station.getData(self.DATA_TIMEOUT_MS)
            except Exception:
                return []

            now = time.time()

            # Procesar cada paquete individualmente
            for sweep in sweeps:
                self._process_single_sweep(sweep)

            # Recolectar tramas que estén completas o hayan expirado
            return self._collect_ready_frames(now)

    def _process_single_sweep(self, sweep):
        """Procesa un paquete de datos crudo y lo mete en el buffer de tramas."""
        try:
            nid = sweep.nodeAddress()
            
            # Solo procesamos nodos que configuramos
            if nid not in self._config_node_ids:
                return

            ts_ns = sweep.timestamp().nanoseconds()
            rssi = sweep.nodeRssi()

            # Extraer valores de canales (usando as_string/as_float seguro)
            values = {}
            for dp in sweep.data():
                try:
                    # Mapeo de nombre de canal (ej: "Channel 1" -> "ch1")
                    import re
                    ch_str = str(dp.channelName()).lower()
                    ch_key = None
                    
                    # Extraer el número exacto del canal de forma robusta
                    match = re.search(r'\b(\d+)\b', ch_str)
                    num = None
                    if match:
                        num = int(match.group(1))
                    else:
                        match_named = re.search(r'(?:ch|val|channel|analog|column|ch_)\s*(\d+)', ch_str)
                        if match_named:
                            num = int(match_named.group(1))
                    
                    if num == 1: ch_key = "ch1"
                    elif num == 2: ch_key = "ch2"
                    elif num == 3: ch_key = "ch3"
                    elif num == 4: ch_key = "ch4"

                    if ch_key:
                        full_key = f"{nid}:{ch_key}"
                        
                        # Si este dato nos interesa
                        if full_key in self._config_data_keys:
                            val = 0.0
                            try:
                                if dp.storedAs() == mscl.valueType_float:
                                    val = dp.as_float()
                                else:
                                    val = float(dp.as_string())
                            except Exception:
                                # Fallback extremo si as_float falla
                                continue
                            
                            values[full_key] = val
                            
                            # Cache simple para debug
                            if full_key in self._value_cache:
                                self._value_cache[full_key].append(val)
                except Exception:
                    continue

            # Si encontramos datos útiles en este barrido, los guardamos
            if values:
                self._insert_into_buffer(ts_ns, values, nid, rssi)

        except Exception:
            pass 

    def _insert_into_buffer(self, ts_ns, values, nid, rssi):
        """Agrega datos a un frame existente o crea uno nuevo."""
        with self._lock:
            # Buscar si ya existe un frame para este instante (con tolerancia)
            target_ts = None
            for t in self._frame_buffer:
                if abs(t - ts_ns) <= self.TIMESTAMP_TOLERANCE_NS:
                    target_ts = t
                    break
            
            if target_ts is None:
                # Crear nuevo frame
                frame = AggregatedFrame(timestamp_ns=ts_ns)
                self._frame_buffer[ts_ns] = frame
            else:
                frame = self._frame_buffer[target_ts]
            
            # Actualizar datos
            frame.readings.update(values)
            frame.rssi_map[nid] = rssi

    def _collect_ready_frames(self, now) -> List[Dict[str, Any]]:
        """Devuelve frames completos o viejos y limpia el buffer."""
        completed = []
        expired_keys = []

        with self._lock:
            # Determinar qué claves esperamos recibir (solo de nodos activos configurados)
            # Como en forzamos los nodos, esperamos todos los configurados
            expected_keys = self._config_data_keys

            for ts, frame in list(self._frame_buffer.items()):
                # ¿Está completo? (Tiene todos los canales configurados)
                is_complete = expected_keys.issubset(frame.readings.keys())
                
                # ¿Es viejo? (Pasó el tiempo de espera para sincronización)
                is_expired = (now - frame.creation_time) > self.FRAME_TIMEOUT_S

                if is_complete or is_expired:
                    # Empaquetar para el DataProcessor
                    completed.append({
                        'timestamp': frame.timestamp_ns / 1e9, # Segundos
                        'values': frame.readings.copy(),
                        'rssi': frame.rssi_map.copy(),
                        'complete': is_complete
                    })
                    expired_keys.append(ts)
            
            # Limpiar procesados
            for ts in expired_keys:
                del self._frame_buffer[ts]

        # Ordenar por timestamp para mantener secuencia
        completed.sort(key=lambda x: x['timestamp'])
        return completed

    # =========================================================================
    # DESCUBRIMIENTO (UI)
    # =========================================================================

    def descubrir_nodos(self, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        """Función auxiliar para la ventana de configuración."""
        if not self._base_station: 
            return []

        self._log(f"Procurando nós ({timeout_ms}ms)...")
        found = {}
        start = time.time()
        
        # Intentamos usar el NodeDiscovery helper de MSCL
        try:
            discovery = mscl.NodeDiscovery(self._base_station)
            discovery.start()
            time.sleep(timeout_ms / 1000.0)
            discovery.stop()
            
            for n in discovery.foundNodes():
                nid = n.nodeAddress()
                found[nid] = {'id': nid, 'rssi': n.radioStrength(), 'channels': []}
                # Asumimos canales por defecto para descubrimiento rápido
                found[nid]['channels'] = [
                    {'channel': 'ch1', 'type': 'strain', 'value': 0.0},
                    {'channel': 'ch2', 'type': 'strain', 'value': 0.0}
                ]
        except Exception as e:
            self._log(f"Fallo en AutoDiscovery: {e}")

        return list(found.values())

    # =========================================================================
    # INTERFAZ Y COMPATIBILIDAD
    # =========================================================================

    @property
    def state(self) -> ConnectionState: 
        with self._lock:
            return self._state
    
    def esta_conectado(self) -> bool: 
        with self._lock:
            return self._state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING)
    
    def get_statistics(self) -> Dict: 
        with self._lock:
            return {'connection_state': self._state.value}

    def get_node_status(self, nid: int) -> Optional[Dict]: 
        # Verificar si hemos recibido datos de este nodo recientemente en el buffer
        last_seen = 0
        is_online = False
        
        # Buscar en cache de valores la última actualización
        for key, deque_vals in self._value_cache.items():
            if str(nid) in key and len(deque_vals) > 0:
                is_online = True # Si hay datos en cache, asumimos vivo
                break
        
        # O usar el set de activos
        if nid in self._active_node_ids:
            is_online = True

        return {'node_id': nid, 'is_online': is_online, 'last_seen': time.time() if is_online else 0}

    def tarar(self, nid=None): pass
    def reset_tarar(self): pass

    def update_nodes_config(self, config: Dict[str, Any]) -> None:
        """Actualiza la configuración de nodos en caliente."""
        with self._lock:
            self.nodos_config = config
            self._config_node_ids = set()
            self._config_data_keys = set()
            self._parse_config()
            self._log(f"Configuración de nodos actualizada en caliente. Total nodos configurados: {len(self._config_node_ids)}")


# Factory function requerida por main.py
def create_driver(nodos_config: Optional[Dict] = None, avoid_eeprom: bool = True) -> MSCLDriver:
    return MSCLDriver(nodos_config, avoid_eeprom=avoid_eeprom)