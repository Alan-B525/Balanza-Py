"""
sensor_driver.py - Driver Unificado para Hardware MSCL MicroStrain

Módulo consolidado y robusto para conexión con nodos SG-Link-200 usando
la biblioteca MSCL. Reemplaza sensor_real.py, sensor_real_v2.py y sensor_manager.py.

Características principales:
- Frame Aggregator: Sincronización de lecturas de 4 celdas por timestamp
- SyncSamplingNetwork: Alineamiento de relojes (±50µs) entre nodos
- Beacon Monitor: Vigilancia y recuperación automática del beacon
- Auto-discovery: Detección automática de puertos COM
- Reconexión robusta: Manejo avanzado de errores y recuperación
- Thread-safe: Operaciones seguras en ambiente multi-thread

Referencia: MSCL API Documentation - LORD MicroStrain
Autor: Balanza-Py Team
Fecha: Diciembre 2025
"""

import sys
import os
import time
import threading
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import deque, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

# Interface del sistema de pesaje
from .interfaces import ISistemaPesaje

# =============================================================================
# CONFIGURACIÓN DE MSCL
# =============================================================================

# Intentar importar MSCL
try:
    import mscl
    MSCL_AVAILABLE = True
except ImportError:
    mscl = None
    MSCL_AVAILABLE = False
    print("[DRIVER] AVISO: Biblioteca MSCL no encontrada.")


# =============================================================================
# ENUMS Y DATACLASSES
# =============================================================================

class ConnectionState(Enum):
    """Estados posibles de la conexión."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SAMPLING = "sampling"  # Nuevo: muestreo sincronizado activo
    RECONNECTING = "reconnecting"
    ERROR = "error"


class ConnectionType(Enum):
    """Tipo de conexión física."""
    SERIAL = "serial"
    TCP_IP = "tcp_ip"


@dataclass
class NodeStatus:
    """Estado detallado de un nodo individual."""
    node_id: int
    channel: str = "ch1"
    is_online: bool = False
    is_configured: bool = False
    last_seen: float = 0.0
    last_value: float = 0.0
    last_rssi: int = 0
    packet_count: int = 0
    error_count: int = 0
    tare_offset: float = 0.0
    
    # Estadísticas de calidad
    avg_rssi: float = 0.0
    rssi_history: deque = field(default_factory=lambda: deque(maxlen=50))


@dataclass
class AggregatedFrame:
    """Frame de datos agregado con lecturas sincronizadas de todos los nodos."""
    timestamp_ns: int  # Timestamp en nanosegundos
    readings: Dict[int, float] = field(default_factory=dict)  # node_id -> valor
    rssi_map: Dict[int, int] = field(default_factory=dict)   # node_id -> rssi
    complete: bool = False
    creation_time: float = field(default_factory=time.time)
    
    def is_complete(self, expected_nodes: Set[int]) -> bool:
        """Verifica si tiene lecturas de todos los nodos esperados."""
        return set(self.readings.keys()) == expected_nodes


# =============================================================================
# CLASE PRINCIPAL: MSCLDriver
# =============================================================================

class MSCLDriver(ISistemaPesaje):
    """
    Driver unificado para hardware MSCL MicroStrain.
    
    Implementa la interfaz ISistemaPesaje con características avanzadas:
    - Frame Aggregator para sincronización de 4 celdas
    - SyncSamplingNetwork para alineamiento de relojes
    - Beacon Monitor para vigilancia de conexión
    - Auto-discovery de puertos
    
    Uso típico:
        driver = MSCLDriver(nodos_config)
        driver.conectar("COM3")  # o "192.168.1.100:5000"
        datos = driver.obtener_datos()  # Retorna solo frames completos
    """
    
    # =========================================================================
    # CONSTANTES DE CONFIGURACIÓN
    # =========================================================================
    
    # Timeouts
    DATA_TIMEOUT_MS = 100           # Timeout para getData()
    FRAME_AGGREGATION_TIMEOUT_MS = 50  # Timeout para completar un frame
    NODE_TIMEOUT_S = 5.0            # Tiempo para considerar nodo offline
    BEACON_CHECK_INTERVAL_S = 2.0   # Intervalo de verificación del beacon
    
    # Reconexión
    RECONNECT_DELAY_S = 2.0
    MAX_RECONNECT_ATTEMPTS = 5
    
    # Validación de datos
    DATA_VALIDATION_MIN = -10000.0  # Valor mínimo (puede ser negativo por tara)
    DATA_VALIDATION_MAX = 50000.0   # Valor máximo en kg
    
    # Cache
    VALUE_CACHE_SIZE = 10
    FRAME_BUFFER_SIZE = 100         # Máximo frames pendientes
    
    # Timestamp tolerance para agrupar (50ms = 50_000_000 ns)
    TIMESTAMP_TOLERANCE_NS = 50_000_000
    
    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================
    
    def __init__(self, nodos_config: Optional[Dict] = None):
        """
        Inicializa el driver MSCL.
        
        Args:
            nodos_config: Configuración de nodos esperados. Formato:
                {
                    "celda_sup_izq": {"id": 11111, "ch": "ch1"},
                    "celda_sup_der": {"id": 22222, "ch": "ch1"},
                    ...
                }
        """
        if not MSCL_AVAILABLE:
            raise ImportError(
                "La biblioteca MSCL es requerida. "
                "Asegúrese de que MSCL está en el PATH del sistema."
            )
        
        # Configuración de nodos
        self.nodos_config = nodos_config or {}
        self._expected_node_ids: Set[int] = set()
        
        # Objetos MSCL
        self._connection: Optional[mscl.Connection] = None
        self._base_station: Optional[mscl.BaseStation] = None
        self._sync_network: Optional[mscl.SyncSamplingNetwork] = None
        
        # Estado
        self._state = ConnectionState.DISCONNECTED
        self._state_lock = threading.RLock()
        self._data_lock = threading.RLock()
        
        # Información de conexión
        self._connection_type: Optional[ConnectionType] = None
        self._connection_string: str = ""
        
        # Status de nodos
        self._node_status: Dict[int, NodeStatus] = {}
        
        # Frame Aggregator - Buffer de frames por timestamp
        self._frame_buffer: Dict[int, AggregatedFrame] = {}
        self._completed_frames: deque = deque(maxlen=self.FRAME_BUFFER_SIZE)
        
        # Cache de últimos valores por nodo
        self._value_cache: Dict[int, deque] = {}
        
        # Beacon Monitor
        self._beacon_monitor_thread: Optional[threading.Thread] = None
        self._beacon_monitor_running = False
        self._last_beacon_check = 0.0
        
        # Estadísticas
        self._stats = {
            'total_packets': 0,
            'valid_packets': 0,
            'invalid_packets': 0,
            'frames_complete': 0,
            'frames_incomplete': 0,
            'reconnect_count': 0,
            'beacon_recoveries': 0,
            'last_error': None,
            'start_time': None
        }
        
        # Inicializar estructuras
        self._initialize_node_structures()
    
    def _initialize_node_structures(self) -> None:
        """Inicializa estructuras de datos para los nodos configurados."""
        for key, cfg in self.nodos_config.items():
            node_id = cfg['id']
            channel = cfg.get('ch', 'ch1')
            
            self._expected_node_ids.add(node_id)
            self._node_status[node_id] = NodeStatus(node_id=node_id, channel=channel)
            self._value_cache[node_id] = deque(maxlen=self.VALUE_CACHE_SIZE)
        
        self._log("INFO", f"Configuración: {len(self._expected_node_ids)} nodos esperados: {self._expected_node_ids}")
    
    # =========================================================================
    # LOGGING
    # =========================================================================
    
    def _log(self, level: str, message: str) -> None:
        """Log interno con timestamp."""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] [MSCL-DRIVER] {message}")
    
    # =========================================================================
    # GESTIÓN DE ESTADO
    # =========================================================================
    
    def _set_state(self, new_state: ConnectionState) -> None:
        """Actualiza el estado de forma thread-safe."""
        with self._state_lock:
            old_state = self._state
            self._state = new_state
            if old_state != new_state:
                self._log("INFO", f"Estado: {old_state.value} → {new_state.value}")
    
    @property
    def state(self) -> ConnectionState:
        """Retorna el estado actual de la conexión."""
        with self._state_lock:
            return self._state
    
    def esta_conectado(self) -> bool:
        """Retorna True si está conectado y operativo."""
        return self.state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING)
    
    # =========================================================================
    # CONEXIÓN
    # =========================================================================
    
    def conectar(self, puerto: str) -> bool:
        """
        Establece conexión con la BaseStation y configura la red sincronizada.
        
        Args:
            puerto: String de conexión. Formatos soportados:
                - "COM3", "COM4", etc. para Serial
                - "/dev/ttyUSB0" para Linux Serial
                - "192.168.1.100:5000" para TCP/IP
                - "AUTO" para auto-detección de puerto
        
        Returns:
            True si la conexión fue exitosa, False en caso contrario
        """
        self._connection_string = puerto
        self._set_state(ConnectionState.CONNECTING)
        
        try:
            # Determinar tipo de conexión y conectar
            if puerto.upper() == "AUTO":
                success = self._connect_auto_discover()
            elif self._is_tcp_address(puerto):
                success = self._connect_tcp(puerto)
            else:
                success = self._connect_serial(puerto)
            
            if not success:
                self._set_state(ConnectionState.ERROR)
                return False
            
            # Inicializar red sincronizada
            if not self._initialize_sync_network():
                self._log("WARNING", "SyncSamplingNetwork no configurada. Usando modo legacy.")
            
            # Iniciar beacon monitor
            self._start_beacon_monitor()
            
            self._stats['start_time'] = time.time()
            self._set_state(ConnectionState.CONNECTED)
            
            self._log("INFO", "✓ Conexión completada exitosamente")
            return True
            
        except mscl.Error_Connection as e:
            self._log("ERROR", f"Error de conexión MSCL: {e}")
            self._stats['last_error'] = f"Connection: {e}"
            self._set_state(ConnectionState.ERROR)
            return False
        except mscl.Error as e:
            self._log("ERROR", f"Error MSCL: {e}")
            self._stats['last_error'] = f"MSCL: {e}"
            self._set_state(ConnectionState.ERROR)
            return False
        except Exception as e:
            self._log("ERROR", f"Error inesperado: {e}")
            self._stats['last_error'] = str(e)
            self._set_state(ConnectionState.ERROR)
            return False
    
    def _is_tcp_address(self, address: str) -> bool:
        """Determina si la dirección es TCP/IP."""
        # TCP si contiene : y NO es un puerto COM de Windows
        if ":" in address:
            if "COM" in address.upper():
                return False  # Es COM con baud rate
            return True
        return False
    
    def _connect_serial(self, puerto: str) -> bool:
        """Establece conexión Serial."""
        self._connection_type = ConnectionType.SERIAL
        
        try:
            self._log("INFO", f"Conectando Serial: {puerto}")
            
            # Intentar conexión al puerto especificado
            self._connection = mscl.Connection.Serial(puerto)
            
            return self._initialize_base_station()
            
        except mscl.Error_Connection as e:
            self._log("WARNING", f"Puerto {puerto} falló: {e}")
            
            # Intentar auto-discovery como fallback
            self._log("INFO", "Intentando auto-detección de puertos...")
            return self._connect_auto_discover()
    
    def _connect_tcp(self, address: str) -> bool:
        """Establece conexión TCP/IP."""
        self._connection_type = ConnectionType.TCP_IP
        
        try:
            parts = address.split(":")
            ip = parts[0].strip()
            port = int(parts[1].strip())
            
            self._log("INFO", f"Conectando TCP/IP: {ip}:{port}")
            self._connection = mscl.Connection.TcpIp(ip, port)
            
            return self._initialize_base_station()
            
        except ValueError as e:
            self._log("ERROR", f"Formato de dirección TCP inválido '{address}': {e}")
            return False
        except mscl.Error_Connection as e:
            self._log("ERROR", f"Error conexión TCP: {e}")
            return False
    
    def _connect_auto_discover(self) -> bool:
        """
        Auto-detecta la BaseStation buscando en puertos disponibles.
        Usa mscl.Devices.listPorts() si está disponible.
        """
        self._connection_type = ConnectionType.SERIAL
        self._log("INFO", "Iniciando auto-detección de puertos...")
        
        # Obtener lista de puertos
        ports_to_try = []
        
        try:
            # Intentar usar MSCL listPorts
            if hasattr(mscl, 'Devices') and hasattr(mscl.Devices, 'listPorts'):
                device_list = mscl.Devices.listPorts()
                for device in device_list:
                    ports_to_try.append(device.portName())
                self._log("INFO", f"Puertos detectados por MSCL: {ports_to_try}")
        except Exception as e:
            self._log("WARNING", f"listPorts no disponible: {e}")
        
        # Agregar puertos comunes si no se encontraron
        if not ports_to_try:
            # Windows
            ports_to_try.extend([f"COM{i}" for i in range(1, 20)])
        
        # Intentar cada puerto
        for port in ports_to_try:
            try:
                self._log("INFO", f"Probando puerto: {port}")
                self._connection = mscl.Connection.Serial(port)
                
                # Crear BaseStation temporal para ping
                temp_base = mscl.BaseStation(self._connection)
                
                if temp_base.ping():
                    self._log("INFO", f"✓ BaseStation encontrada en {port}")
                    self._base_station = temp_base
                    self._connection_string = port
                    return self._post_base_station_init()
                else:
                    self._connection.disconnect()
                    
            except mscl.Error as e:
                # Puerto no válido, continuar
                pass
            except Exception as e:
                pass
        
        self._log("ERROR", "No se encontró BaseStation en ningún puerto")
        return False
    
    def _initialize_base_station(self) -> bool:
        """Inicializa y valida la BaseStation."""
        try:
            self._base_station = mscl.BaseStation(self._connection)
            
            # Ping para verificar comunicación
            self._log("INFO", "Verificando comunicación (ping)...")
            ping_ok = False
            try:
                ping_ok = self._base_station.ping()
            except:
                pass
            
            if not ping_ok:
                self._log("WARNING", "Ping falló - algunos modelos no responden, continuando...")
            
            return self._post_base_station_init()
            
        except mscl.Error as e:
            self._log("ERROR", f"Fallo al crear BaseStation: {e}")
            return False
    
    def _post_base_station_init(self) -> bool:
        """Configuración post-inicialización de BaseStation."""
        try:
            # Habilitar Beacon para sincronización de nodos
            self._log("INFO", "Habilitando Beacon...")
            try:
                beacon_time = self._base_station.enableBeacon()
                self._log("INFO", f"Beacon habilitado. Tiempo base: {beacon_time}")
            except mscl.Error as e:
                self._log("WARNING", f"No se pudo habilitar Beacon: {e}")
            
            # Limpiar buffer de datos antiguos
            try:
                old_data = self._base_station.getData(100)
                if old_data:
                    self._log("INFO", f"Limpiados {len(old_data)} sweeps antiguos del buffer")
            except:
                pass
            
            self._log("INFO", "✓ BaseStation inicializada")
            return True
            
        except mscl.Error as e:
            self._log("ERROR", f"Error en post-init: {e}")
            return False
    
    # =========================================================================
    # SYNC SAMPLING NETWORK
    # =========================================================================
    
    def _initialize_sync_network(self) -> bool:
        """
        Inicializa la red de muestreo sincronizado (SyncSamplingNetwork).
        
        Esto garantiza:
        - Alineamiento de relojes entre nodos (±50µs)
        - Sincronización de timestamps
        - Configuración uniforme de sampling rate
        """
        if not self._base_station or not self._expected_node_ids:
            return False
        
        self._log("INFO", "Configurando SyncSamplingNetwork...")
        
        try:
            # Crear red de muestreo sincronizado
            self._sync_network = mscl.SyncSamplingNetwork(self._base_station)
            
            nodes_added = 0
            nodes_failed = []
            
            for node_id in self._expected_node_ids:
                try:
                    # Crear objeto WirelessNode
                    node = mscl.WirelessNode(node_id, self._base_station)
                    
                    # Verificar que el nodo responde
                    try:
                        node.ping()
                        self._log("INFO", f"  Nodo {node_id}: ping OK")
                    except mscl.Error:
                        self._log("WARNING", f"  Nodo {node_id}: no responde a ping")
                    
                    # Agregar nodo a la red sincronizada
                    self._sync_network.addNode(node)
                    nodes_added += 1
                    
                    # Marcar como configurado
                    if node_id in self._node_status:
                        self._node_status[node_id].is_configured = True
                    
                    self._log("INFO", f"  Nodo {node_id}: agregado a SyncNetwork")
                    
                except mscl.Error as e:
                    self._log("WARNING", f"  Nodo {node_id}: error - {e}")
                    nodes_failed.append(node_id)
            
            if nodes_added == 0:
                self._log("ERROR", "No se pudo agregar ningún nodo a SyncNetwork")
                return False
            
            # Verificar estado de la red
            try:
                if self._sync_network.ok():
                    self._log("INFO", "✓ SyncSamplingNetwork: OK")
                else:
                    self._log("WARNING", "SyncSamplingNetwork: Configuración incompleta")
                    # Obtener problemas de configuración
                    # issues = self._sync_network.getConfigurationIssues()
                    # for issue in issues:
                    #     self._log("WARNING", f"  - {issue.description()}")
            except:
                pass
            
            # Iniciar muestreo sincronizado
            try:
                self._log("INFO", "Iniciando muestreo sincronizado...")
                self._sync_network.startSampling()
                self._set_state(ConnectionState.SAMPLING)
                self._log("INFO", f"✓ Muestreo iniciado con {nodes_added} nodos")
                return True
            except mscl.Error as e:
                self._log("WARNING", f"startSampling falló: {e}")
                self._log("INFO", "Continuando en modo legacy (sin SyncNetwork)")
                return False
            
        except mscl.Error as e:
            self._log("WARNING", f"SyncSamplingNetwork no disponible: {e}")
            return False
        except Exception as e:
            self._log("WARNING", f"Error configurando SyncNetwork: {e}")
            return False
    
    # =========================================================================
    # BEACON MONITOR
    # =========================================================================
    
    def _start_beacon_monitor(self) -> None:
        """Inicia el hilo de monitoreo del Beacon."""
        if self._beacon_monitor_running:
            return
        
        self._beacon_monitor_running = True
        self._beacon_monitor_thread = threading.Thread(
            target=self._beacon_monitor_loop,
            daemon=True,
            name="BeaconMonitor"
        )
        self._beacon_monitor_thread.start()
        self._log("INFO", "Beacon Monitor iniciado")
    
    def _stop_beacon_monitor(self) -> None:
        """Detiene el hilo de monitoreo del Beacon."""
        self._beacon_monitor_running = False
        if self._beacon_monitor_thread:
            self._beacon_monitor_thread.join(timeout=2.0)
            self._beacon_monitor_thread = None
    
    def _beacon_monitor_loop(self) -> None:
        """Loop de monitoreo del Beacon."""
        while self._beacon_monitor_running and self.esta_conectado():
            try:
                time.sleep(self.BEACON_CHECK_INTERVAL_S)
                
                if not self._base_station:
                    continue
                
                # Verificar estado del beacon
                try:
                    beacon_status = self._base_station.beaconStatus()
                    
                    # Si el beacon no está activo, reactivarlo
                    if not beacon_status.enabled():
                        self._log("WARNING", "⚠ Beacon desactivado! Reactivando...")
                        self._base_station.enableBeacon()
                        self._stats['beacon_recoveries'] += 1
                        self._log("INFO", "✓ Beacon reactivado")
                        
                except mscl.Error as e:
                    # Si falla la verificación, intentar reactivar
                    self._log("WARNING", f"Error verificando beacon: {e}")
                    try:
                        self._base_station.enableBeacon()
                        self._stats['beacon_recoveries'] += 1
                    except:
                        pass
                        
            except Exception as e:
                self._log("ERROR", f"Error en BeaconMonitor: {e}")
    
    # =========================================================================
    # FRAME AGGREGATOR - OBTENCIÓN DE DATOS SINCRONIZADOS
    # =========================================================================
    
    def obtener_datos(self) -> List[Dict[str, Any]]:
        """
        Obtiene datos sincronizados de todos los nodos.
        
        IMPORTANTE: Solo retorna frames COMPLETOS (con datos de las 4 celdas)
        para evitar errores de suma en la balanza.
        
        Returns:
            Lista de diccionarios con formato:
            [
                {
                    'timestamp': float,
                    'values': {node_id: valor, ...},
                    'total': float,  # Suma de todas las celdas
                    'rssi': {node_id: rssi, ...}
                },
                ...
            ]
        """
        if not self.esta_conectado() or not self._base_station:
            return []
        
        current_time = time.time()
        
        try:
            # Obtener sweeps disponibles del buffer
            sweeps = self._base_station.getData(self.DATA_TIMEOUT_MS)
            
            # Procesar cada sweep y agregarlo al buffer de frames
            for sweep in sweeps:
                self._process_sweep_to_frame(sweep, current_time)
            
            # Limpiar frames expirados y obtener completos
            complete_frames = self._collect_complete_frames(current_time)
            
            # Verificar timeouts de nodos
            self._check_node_timeouts(current_time)
            
            return complete_frames
            
        except mscl.Error_Connection as e:
            self._log("ERROR", f"Error de conexión: {e}")
            self._handle_connection_error()
            return []
        except mscl.Error as e:
            self._log("WARNING", f"Error MSCL leyendo datos: {e}")
            return []
        except Exception as e:
            self._log("ERROR", f"Error inesperado en obtener_datos: {e}")
            return []
    
    def _process_sweep_to_frame(self, sweep: 'mscl.DataSweep', current_time: float) -> None:
        """
        Procesa un sweep y lo agrega al frame correspondiente según su timestamp.
        """
        self._stats['total_packets'] += 1
        
        try:
            node_id = sweep.nodeAddress()
            rssi = sweep.nodeRssi()
            timestamp_ns = sweep.timestamp().nanoseconds()
            
            # Actualizar status del nodo
            self._update_node_status(node_id, rssi, current_time)
            
            # Procesar datos del sweep
            for data_point in sweep.data():
                # Validar punto de datos
                if hasattr(data_point, 'valid') and not data_point.valid():
                    self._stats['invalid_packets'] += 1
                    if node_id in self._node_status:
                        self._node_status[node_id].error_count += 1
                    continue
                
                # Obtener valor
                try:
                    valor_bruto = data_point.as_float()
                except:
                    try:
                        valor_bruto = data_point.as_double()
                    except:
                        continue
                
                # Validar valor
                if not self._validate_value(valor_bruto):
                    self._stats['invalid_packets'] += 1
                    continue
                
                # Guardar en cache
                if node_id in self._value_cache:
                    self._value_cache[node_id].append(valor_bruto)
                
                # Actualizar último valor del nodo
                if node_id in self._node_status:
                    self._node_status[node_id].last_value = valor_bruto
                
                # Aplicar tara
                tare = self._node_status[node_id].tare_offset if node_id in self._node_status else 0.0
                valor_neto = valor_bruto - tare
                
                # Agregar al frame correspondiente
                self._add_to_frame(timestamp_ns, node_id, valor_neto, rssi)
                
                self._stats['valid_packets'] += 1
                
        except Exception as e:
            self._stats['invalid_packets'] += 1
            self._log("WARNING", f"Error procesando sweep: {e}")
    
    def _add_to_frame(self, timestamp_ns: int, node_id: int, value: float, rssi: int) -> None:
        """
        Agrega una lectura al frame correspondiente.
        Agrupa por timestamp con tolerancia definida.
        """
        with self._data_lock:
            # Buscar frame existente con timestamp cercano
            frame_key = self._find_frame_key(timestamp_ns)
            
            if frame_key is None:
                # Crear nuevo frame
                frame_key = timestamp_ns
                self._frame_buffer[frame_key] = AggregatedFrame(timestamp_ns=timestamp_ns)
            
            # Agregar lectura al frame
            frame = self._frame_buffer[frame_key]
            frame.readings[node_id] = value
            frame.rssi_map[node_id] = rssi
    
    def _find_frame_key(self, timestamp_ns: int) -> Optional[int]:
        """
        Busca un frame existente con timestamp dentro de la tolerancia.
        """
        for key in self._frame_buffer:
            if abs(key - timestamp_ns) <= self.TIMESTAMP_TOLERANCE_NS:
                return key
        return None
    
    def _collect_complete_frames(self, current_time: float) -> List[Dict[str, Any]]:
        """
        Recolecta frames completos y limpia frames expirados.
        """
        complete_frames = []
        frames_to_remove = []
        
        timeout_threshold = current_time - (self.FRAME_AGGREGATION_TIMEOUT_MS / 1000.0)
        
        with self._data_lock:
            for key, frame in list(self._frame_buffer.items()):
                # Verificar si el frame está completo
                if frame.is_complete(self._expected_node_ids):
                    frame.complete = True
                    complete_frames.append(self._format_frame(frame))
                    frames_to_remove.append(key)
                    self._stats['frames_complete'] += 1
                    
                # Verificar si el frame expiró
                elif frame.creation_time < timeout_threshold:
                    # Frame incompleto pero expirado
                    # Opción: descartar o enviar parcial
                    # Por robustez, descartamos frames incompletos
                    frames_to_remove.append(key)
                    self._stats['frames_incomplete'] += 1
            
            # Limpiar frames procesados/expirados
            for key in frames_to_remove:
                del self._frame_buffer[key]
        
        return complete_frames
    
    def _format_frame(self, frame: AggregatedFrame) -> Dict[str, Any]:
        """
        Formatea un frame completo para retorno.
        """
        total = sum(frame.readings.values())
        
        return {
            'timestamp': frame.timestamp_ns / 1e9,  # Convertir a segundos
            'timestamp_ns': frame.timestamp_ns,
            'values': dict(frame.readings),
            'rssi': dict(frame.rssi_map),
            'total': total,
            'complete': frame.complete
        }
    
    def _update_node_status(self, node_id: int, rssi: int, current_time: float) -> None:
        """Actualiza el status de un nodo."""
        if node_id not in self._node_status:
            # Nodo no configurado pero detectado
            self._node_status[node_id] = NodeStatus(node_id=node_id)
            self._value_cache[node_id] = deque(maxlen=self.VALUE_CACHE_SIZE)
            self._log("INFO", f"Nuevo nodo detectado: {node_id}")
        
        status = self._node_status[node_id]
        status.last_seen = current_time
        status.last_rssi = rssi
        status.packet_count += 1
        status.is_online = True
        
        # Actualizar historial de RSSI
        status.rssi_history.append(rssi)
        if status.rssi_history:
            status.avg_rssi = sum(status.rssi_history) / len(status.rssi_history)
    
    def _validate_value(self, value: float) -> bool:
        """Valida si un valor está dentro de los límites aceptables."""
        if value is None:
            return False
        if not isinstance(value, (int, float)):
            return False
        if value < self.DATA_VALIDATION_MIN or value > self.DATA_VALIDATION_MAX:
            return False
        return True
    
    def _check_node_timeouts(self, current_time: float) -> None:
        """Verifica y marca nodos en timeout."""
        for node_id, status in self._node_status.items():
            if status.is_online:
                if current_time - status.last_seen > self.NODE_TIMEOUT_S:
                    status.is_online = False
                    self._log("WARNING", f"Nodo {node_id} en timeout (sin datos hace {self.NODE_TIMEOUT_S}s)")
    
    # =========================================================================
    # MANEJO DE ERRORES Y RECONEXIÓN
    # =========================================================================
    
    def _handle_connection_error(self) -> None:
        """Maneja errores de conexión e intenta reconectar."""
        self._set_state(ConnectionState.RECONNECTING)
        self._stats['reconnect_count'] += 1
        
        for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
            self._log("INFO", f"Intento de reconexión {attempt + 1}/{self.MAX_RECONNECT_ATTEMPTS}")
            time.sleep(self.RECONNECT_DELAY_S)
            
            try:
                # Desconectar limpiamente
                self._cleanup_connection()
                
                # Intentar reconectar
                if self.conectar(self._connection_string):
                    self._log("INFO", "✓ Reconexión exitosa!")
                    return
                    
            except Exception as e:
                self._log("ERROR", f"Falló intento {attempt + 1}: {e}")
        
        self._log("ERROR", "Todas las tentativas de reconexión fallaron")
        self._set_state(ConnectionState.ERROR)
    
    def _cleanup_connection(self) -> None:
        """Limpia la conexión actual."""
        try:
            if self._sync_network:
                try:
                    self._sync_network.stopSampling()
                except:
                    pass
                self._sync_network = None
            
            if self._base_station:
                try:
                    self._base_station.disableBeacon()
                except:
                    pass
                self._base_station = None
            
            if self._connection:
                try:
                    self._connection.disconnect()
                except:
                    pass
                self._connection = None
                
        except Exception as e:
            self._log("WARNING", f"Error en cleanup: {e}")
    
    # =========================================================================
    # DESCONEXIÓN
    # =========================================================================
    
    def desconectar(self) -> None:
        """Cierra la conexión de forma segura."""
        self._log("INFO", "Iniciando desconexión...")
        
        # Detener beacon monitor
        self._stop_beacon_monitor()
        
        # Limpiar conexión
        self._cleanup_connection()
        
        # Limpiar buffers
        with self._data_lock:
            self._frame_buffer.clear()
            self._completed_frames.clear()
        
        self._set_state(ConnectionState.DISCONNECTED)
        self._log("INFO", "✓ Desconectado")
    
    # =========================================================================
    # TARA
    # =========================================================================
    
    def tarar(self, node_id: int = None) -> None:
        """
        Aplica tara (cero) a los nodos.
        
        Args:
            node_id: ID específico del nodo, o None para todos
        """
        if node_id is not None:
            self._apply_tare_to_node(node_id)
        else:
            for nid in self._node_status:
                self._apply_tare_to_node(nid)
    
    def _apply_tare_to_node(self, node_id: int) -> None:
        """Aplica tara a un nodo específico."""
        if node_id not in self._value_cache:
            return
        
        cache = self._value_cache[node_id]
        if not cache:
            self._log("WARNING", f"Nodo {node_id}: sin datos para tara")
            return
        
        # Calcular promedio de últimos valores
        avg = sum(cache) / len(cache)
        
        if node_id in self._node_status:
            self._node_status[node_id].tare_offset = avg
        
        self._log("INFO", f"Tara aplicada al nodo {node_id}: {avg:.4f}")
    
    def reset_tarar(self) -> None:
        """Resetea todas las taras a cero."""
        for status in self._node_status.values():
            status.tare_offset = 0.0
        self._log("INFO", "Todas las taras reseteadas")
    
    # =========================================================================
    # DESCUBRIMIENTO DE NODOS
    # =========================================================================
    
    def descubrir_nodos(self, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        """
        Descubre nodos wireless en la red.
        
        Args:
            timeout_ms: Timeout para descubrimiento en milisegundos
            
        Returns:
            Lista de nodos encontrados con sus informaciones
        """
        if not self.esta_conectado() or not self._base_station:
            self._log("WARNING", "Sin conexión activa para descubrir nodos")
            return []
        
        self._log("INFO", f"Iniciando descubrimiento de nodos (timeout: {timeout_ms}ms)...")
        nodos_encontrados = []
        node_ids_seen: Set[int] = set()
        
        try:
            start_time = time.time()
            
            while (time.time() - start_time) * 1000 < timeout_ms:
                sweeps = self._base_station.getData(200)
                
                for sweep in sweeps:
                    node_id = sweep.nodeAddress()
                    
                    if node_id not in node_ids_seen:
                        node_ids_seen.add(node_id)
                        
                        info = {
                            'id': node_id,
                            'rssi': sweep.nodeRssi(),
                            'status': 'active',
                            'configured': node_id in self._expected_node_ids
                        }
                        
                        try:
                            info['sample_rate'] = sweep.sampleRate().prettyStr()
                        except:
                            info['sample_rate'] = 'unknown'
                        
                        nodos_encontrados.append(info)
                        self._log("INFO", f"  Nodo encontrado: ID={node_id}, RSSI={info['rssi']}")
                
                time.sleep(0.1)
                
        except mscl.Error as e:
            self._log("ERROR", f"Error durante descubrimiento: {e}")
        
        self._log("INFO", f"Descubrimiento completo: {len(nodos_encontrados)} nodo(s)")
        return nodos_encontrados
    
    # =========================================================================
    # ESTADÍSTICAS Y STATUS
    # =========================================================================
    
    def get_node_status(self, node_id: int) -> Optional[Dict[str, Any]]:
        """Retorna status detallado de un nodo específico."""
        if node_id not in self._node_status:
            return None
        
        status = self._node_status[node_id]
        return {
            'node_id': status.node_id,
            'channel': status.channel,
            'is_online': status.is_online,
            'is_configured': status.is_configured,
            'last_seen': status.last_seen,
            'last_value': status.last_value,
            'last_rssi': status.last_rssi,
            'avg_rssi': status.avg_rssi,
            'packet_count': status.packet_count,
            'error_count': status.error_count,
            'tare_offset': status.tare_offset
        }
    
    def get_all_node_status(self) -> Dict[int, Dict[str, Any]]:
        """Retorna status de todos los nodos."""
        return {
            node_id: self.get_node_status(node_id)
            for node_id in self._node_status
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Retorna estadísticas generales del sistema."""
        uptime = 0.0
        if self._stats['start_time']:
            uptime = time.time() - self._stats['start_time']
        
        return {
            **self._stats,
            'uptime_seconds': uptime,
            'connection_state': self.state.value,
            'connection_type': self._connection_type.value if self._connection_type else None,
            'nodes_online': sum(1 for s in self._node_status.values() if s.is_online),
            'nodes_configured': len(self._expected_node_ids),
            'nodes_total': len(self._node_status),
            'frame_buffer_size': len(self._frame_buffer)
        }
    
    def get_last_cached_value(self, node_id: int) -> Optional[float]:
        """
        Retorna el último valor en cache para un nodo.
        Útil cuando hay pérdida temporal de datos.
        """
        if node_id in self._value_cache and self._value_cache[node_id]:
            return self._value_cache[node_id][-1]
        return None


# =============================================================================
# ALIAS PARA COMPATIBILIDAD
# =============================================================================

# Alias para compatibilidad con código existente
RealPesaje = MSCLDriver


# =============================================================================
# FUNCIÓN DE UTILIDAD
# =============================================================================

def create_driver(nodos_config: Optional[Dict] = None) -> MSCLDriver:
    """
    Función factory para crear el driver.
    
    Args:
        nodos_config: Configuración de nodos
        
    Returns:
        Instancia de MSCLDriver
        
    Raises:
        ImportError: Si MSCL no está disponible
    """
    if not MSCL_AVAILABLE:
        raise ImportError(
            "MSCL no está disponible. "
            "Instale la biblioteca MSCL o use el modo MOCK."
        )
    return MSCLDriver(nodos_config)
