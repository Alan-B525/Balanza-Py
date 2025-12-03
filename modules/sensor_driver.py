"""
sensor_driver.py - Driver Unificado para Hardware MSCL MicroStrain

Módulo consolidado y robusto para conexión con nodos SG-Link-200 usando
la biblioteca MSCL. 

Características principales:
- Frame Aggregator: Sincronización de lecturas de 4 celdas por timestamp
- SyncSamplingNetwork: Alineamiento de relojes (±50µs) entre nodos
- Configuración Forzada: Aplica configuración determinista a cada nodo
- Beacon Monitor: Vigilancia y recuperación automática del beacon
- Auto-discovery: Detección automática de puertos COM
- Reconexión robusta: Manejo avanzado de errores y recuperación
- Thread-safe: Operaciones seguras en ambiente multi-thread

NOTA: Este driver entrega valores CRUDOS (calibrados por hardware).
      La tara de sesión se maneja en DataProcessor, NO aquí.

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
    SAMPLING = "sampling"  # Muestreo sincronizado activo
    RECONNECTING = "reconnecting"
    ERROR = "error"


class ConnectionType(Enum):
    """Tipo de conexión física."""
    SERIAL = "serial"
    TCP_IP = "tcp_ip"


@dataclass
class NodeStatus:
    """
    Estado detallado de un nodo individual.
    
    NOTA: No incluye tare_offset - la tara se maneja en DataProcessor.
    """
    node_id: int
    channel: str = "ch1"
    is_online: bool = False
    is_configured: bool = False
    last_seen: float = 0.0
    last_value: float = 0.0
    last_rssi: int = 0
    packet_count: int = 0
    error_count: int = 0
    
    # Estadísticas de calidad
    avg_rssi: float = 0.0
    rssi_history: deque = field(default_factory=lambda: deque(maxlen=50))


@dataclass
class AggregatedFrame:
    """Frame de datos agregado con lecturas sincronizadas de todos los nodos."""
    timestamp_ns: int  # Timestamp en nanosegundos
    readings: Dict[int, float] = field(default_factory=dict)  # node_id -> valor CRUDO
    rssi_map: Dict[int, int] = field(default_factory=dict)   # node_id -> rssi
    complete: bool = False
    creation_time: float = field(default_factory=time.time)
    
    def is_complete(self, expected_nodes: Set[int]) -> bool:
        """Verifica si tiene lecturas de todos los nodos esperados."""
        return set(self.readings.keys()) == expected_nodes


# =============================================================================
# EXCEPCIONES PERSONALIZADAS
# =============================================================================

class SyncNetworkError(Exception):
    """Error crítico en la configuración de SyncSamplingNetwork."""
    pass


class NodeConfigurationError(Exception):
    """Error al configurar un nodo."""
    pass


# =============================================================================
# CLASE PRINCIPAL: MSCLDriver
# =============================================================================

class MSCLDriver(ISistemaPesaje):
    """
    Driver unificado para hardware MSCL MicroStrain.
    
    Implementa la interfaz ISistemaPesaje con características avanzadas:
    - Frame Aggregator para sincronización de 4 celdas
    - SyncSamplingNetwork para alineamiento de relojes (±50µs)
    - Configuración forzada de nodos (32Hz, sync mode)
    - Beacon Monitor para vigilancia de conexión
    - Auto-discovery de puertos
    
    IMPORTANTE: Este driver entrega valores CRUDOS. La tara se aplica
    en DataProcessor para evitar duplicación de lógica.
    
    Uso típico:
        driver = MSCLDriver(nodos_config)
        driver.conectar("COM3")  # o "192.168.1.100:5000"
        datos = driver.obtener_datos()  # Retorna solo frames completos con valores CRUDOS
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
    
    # Validación de datos (valores crudos, pueden ser negativos por calibración)
    DATA_VALIDATION_MIN = -50000.0  # Valor mínimo en kg
    DATA_VALIDATION_MAX = 50000.0   # Valor máximo en kg
    
    # Cache
    VALUE_CACHE_SIZE = 10
    FRAME_BUFFER_SIZE = 100         # Máximo frames pendientes
    
    # Timestamp tolerance para agrupar lecturas (10ms = 10_000_000 ns)
    # Con protocolo LXRS la sincronización es ±50µs, 10ms es margen seguro
    # A 32Hz (periodo ~31ms), esto evita agrupar muestras de distintos ciclos
    TIMESTAMP_TOLERANCE_NS = 10_000_000
    
    # Configuración de muestreo forzada
    TARGET_SAMPLE_RATE_HZ = 32
    
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
        
        # Referencias a nodos para configuración
        self._wireless_nodes: Dict[int, 'mscl.WirelessNode'] = {}
        
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
        
        # Cache de últimos valores por nodo (valores CRUDOS)
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
            
        Raises:
            SyncNetworkError: Si no se puede iniciar el muestreo sincronizado
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
            
            # Inicializar red sincronizada - OBLIGATORIO para esta balanza
            if not self._initialize_sync_network():
                self._log("ERROR", "FALLO CRÍTICO: No se pudo inicializar SyncSamplingNetwork")
                self._set_state(ConnectionState.ERROR)
                raise SyncNetworkError(
                    "No se pudo iniciar el muestreo sincronizado. "
                    "Una red desincronizada es inaceptable para esta balanza."
                )
            
            # Iniciar beacon monitor
            self._start_beacon_monitor()
            
            self._stats['start_time'] = time.time()
            # Estado ya está en SAMPLING después de _initialize_sync_network exitoso
            
            self._log("INFO", "✓ Conexión completada exitosamente")
            return True
            
        except SyncNetworkError:
            # Re-lanzar excepciones de sincronización
            raise
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
            self._connection = mscl.Connection.Serial(puerto)
            return self._initialize_base_station()
            
        except mscl.Error_Connection as e:
            self._log("WARNING", f"Puerto {puerto} falló: {e}")
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
        
        ports_to_try = []
        
        try:
            if hasattr(mscl, 'Devices') and hasattr(mscl.Devices, 'listPorts'):
                device_list = mscl.Devices.listPorts()
                for device in device_list:
                    ports_to_try.append(device.portName())
                self._log("INFO", f"Puertos detectados por MSCL: {ports_to_try}")
        except Exception as e:
            self._log("WARNING", f"listPorts no disponible: {e}")
        
        if not ports_to_try:
            ports_to_try.extend([f"COM{i}" for i in range(1, 20)])
        
        for port in ports_to_try:
            try:
                self._log("INFO", f"Probando puerto: {port}")
                self._connection = mscl.Connection.Serial(port)
                temp_base = mscl.BaseStation(self._connection)
                
                if temp_base.ping():
                    self._log("INFO", f"✓ BaseStation encontrada en {port}")
                    self._base_station = temp_base
                    self._connection_string = port
                    return self._post_base_station_init()
                else:
                    self._connection.disconnect()
                    
            except mscl.Error:
                pass
            except Exception:
                pass
        
        self._log("ERROR", "No se encontró BaseStation en ningún puerto")
        return False
    
    def _initialize_base_station(self) -> bool:
        """Inicializa y valida la BaseStation."""
        try:
            self._base_station = mscl.BaseStation(self._connection)
            
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
            self._log("INFO", "Habilitando Beacon...")
            try:
                beacon_time = self._base_station.enableBeacon()
                self._log("INFO", f"Beacon habilitado. Tiempo base: {beacon_time}")
            except mscl.Error as e:
                self._log("WARNING", f"No se pudo habilitar Beacon: {e}")
            
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
    # CONFIGURACIÓN FORZADA DE NODOS
    # =========================================================================
    
    def _apply_node_config(self, node: 'mscl.WirelessNode') -> bool:
        """
        Aplica configuración determinista a un nodo.
        
        Establece:
        - Modo de muestreo: Sync Sampling
        - Sample Rate: 32 Hz
        - Filtros: Confía en configuración de hardware
        
        Args:
            node: Objeto WirelessNode de MSCL
            
        Returns:
            True si la configuración fue exitosa
            
        Raises:
            NodeConfigurationError: Si no se puede configurar el nodo
        """
        node_id = node.nodeAddress()
        self._log("INFO", f"  Configurando nodo {node_id}...")
        
        try:
            # Crear objeto de configuración
            config = mscl.WirelessNodeConfig()
            
            # Establecer modo de muestreo sincronizado
            # samplingMode_sync = muestreo sincronizado con beacon
            config.samplingMode(mscl.WirelessTypes.samplingMode_sync)
            
            # Establecer sample rate a 32 Hz
            # Esto garantiza uniformidad en toda la red
            sample_rate = mscl.SampleRate.Hertz(self.TARGET_SAMPLE_RATE_HZ)
            config.sampleRate(sample_rate)
            
            # TODO: Configurar filtros analógicos/digitales si es necesario
            # Los SG-Link-200 tienen filtros configurables:
            # - config.lowPassFilter(mscl.WirelessTypes.filter_33hz)
            # - config.highPassFilter(mscl.WirelessTypes.highPass_off)
            # Por ahora, confiamos en la configuración de hardware existente
            
            # Aplicar configuración al nodo
            node.applyConfig(config)
            
            self._log("INFO", f"  Nodo {node_id}: Configurado (Sync, {self.TARGET_SAMPLE_RATE_HZ}Hz)")
            return True
            
        except mscl.Error_NodeCommunication as e:
            self._log("ERROR", f"  Nodo {node_id}: Error de comunicación - {e}")
            raise NodeConfigurationError(f"No se pudo comunicar con nodo {node_id}: {e}")
        except mscl.Error_InvalidNodeConfig as e:
            self._log("ERROR", f"  Nodo {node_id}: Configuración inválida - {e}")
            raise NodeConfigurationError(f"Configuración inválida para nodo {node_id}: {e}")
        except mscl.Error as e:
            self._log("WARNING", f"  Nodo {node_id}: Error aplicando config - {e}")
            # Algunos nodos pueden no soportar todas las opciones
            # Intentamos continuar con configuración por defecto
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
        - Configuración uniforme de sampling rate (32Hz)
        
        IMPORTANTE: Si falla, NO continúa en modo legacy.
        Una red desincronizada es inaceptable para esta balanza.
        
        Returns:
            True si el muestreo sincronizado inició correctamente
            
        Raises:
            SyncNetworkError: Si no se puede iniciar el muestreo
        """
        if not self._base_station or not self._expected_node_ids:
            return False
        
        self._log("INFO", "=" * 50)
        self._log("INFO", "Configurando SyncSamplingNetwork...")
        self._log("INFO", f"  Target Sample Rate: {self.TARGET_SAMPLE_RATE_HZ} Hz")
        self._log("INFO", f"  Timestamp Tolerance: {self.TIMESTAMP_TOLERANCE_NS / 1e6:.1f} ms")
        self._log("INFO", "=" * 50)
        
        try:
            # Crear red de muestreo sincronizado
            self._sync_network = mscl.SyncSamplingNetwork(self._base_station)
            
            nodes_added = 0
            nodes_failed = []
            
            for node_id in self._expected_node_ids:
                try:
                    # Crear objeto WirelessNode
                    node = mscl.WirelessNode(node_id, self._base_station)
                    self._wireless_nodes[node_id] = node
                    
                    # Verificar que el nodo responde
                    try:
                        node.ping()
                        self._log("INFO", f"  Nodo {node_id}: ping OK")
                    except mscl.Error:
                        self._log("WARNING", f"  Nodo {node_id}: no responde a ping")
                        # Continuar de todos modos
                    
                    # APLICAR CONFIGURACIÓN FORZADA antes de agregar a la red
                    try:
                        self._apply_node_config(node)
                    except NodeConfigurationError as e:
                        self._log("WARNING", f"  Nodo {node_id}: {e}")
                        # Intentar continuar con configuración existente
                    
                    # Agregar nodo a la red sincronizada
                    self._sync_network.addNode(node)
                    nodes_added += 1
                    
                    # Marcar como configurado
                    if node_id in self._node_status:
                        self._node_status[node_id].is_configured = True
                    
                    self._log("INFO", f"  Nodo {node_id}: agregado a SyncNetwork ✓")
                    
                except mscl.Error as e:
                    self._log("ERROR", f"  Nodo {node_id}: error crítico - {e}")
                    nodes_failed.append(node_id)
            
            if nodes_added == 0:
                raise SyncNetworkError("No se pudo agregar ningún nodo a SyncNetwork")
            
            if nodes_added < len(self._expected_node_ids):
                self._log("WARNING", f"Solo {nodes_added}/{len(self._expected_node_ids)} nodos agregados")
                self._log("WARNING", f"Nodos fallidos: {nodes_failed}")
            
            # Verificar estado de la red
            try:
                if self._sync_network.ok():
                    self._log("INFO", "✓ SyncSamplingNetwork: Configuración OK")
                else:
                    self._log("WARNING", "SyncSamplingNetwork: Hay problemas de configuración")
                    # Intentar obtener detalles de los problemas
                    try:
                        issues = self._sync_network.getConfigurationIssues()
                        for issue in issues:
                            self._log("WARNING", f"  - {issue.description()}")
                    except:
                        pass
            except Exception as e:
                self._log("WARNING", f"No se pudo verificar estado de red: {e}")
            
            # Iniciar muestreo sincronizado - SIN CAPTURA DE EXCEPCIÓN
            # Si falla, la excepción se propaga hacia arriba
            self._log("INFO", "Iniciando muestreo sincronizado...")
            self._sync_network.startSampling()
            
            self._set_state(ConnectionState.SAMPLING)
            self._log("INFO", f"✓ Muestreo sincronizado iniciado con {nodes_added} nodos")
            self._log("INFO", "=" * 50)
            return True
            
        except mscl.Error as e:
            self._log("ERROR", f"Error MSCL en SyncNetwork: {e}")
            raise SyncNetworkError(f"Fallo al iniciar SyncSamplingNetwork: {e}")
        except SyncNetworkError:
            raise
        except Exception as e:
            self._log("ERROR", f"Error inesperado en SyncNetwork: {e}")
            raise SyncNetworkError(f"Error inesperado: {e}")
    
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
                
                try:
                    beacon_status = self._base_station.beaconStatus()
                    
                    if not beacon_status.enabled():
                        self._log("WARNING", "⚠ Beacon desactivado! Reactivando...")
                        self._base_station.enableBeacon()
                        self._stats['beacon_recoveries'] += 1
                        self._log("INFO", "✓ Beacon reactivado")
                        
                except mscl.Error as e:
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
        
        IMPORTANTE: 
        - Solo retorna frames COMPLETOS (con datos de las 4 celdas)
        - Los valores son CRUDOS (calibrados por hardware, sin tara de sesión)
        - La tara se aplica en DataProcessor
        
        Returns:
            Lista de diccionarios con formato:
            [
                {
                    'timestamp': float,
                    'values': {node_id: valor_crudo, ...},
                    'total': float,  # Suma de valores crudos
                    'rssi': {node_id: rssi, ...}
                },
                ...
            ]
        """
        if not self.esta_conectado() or not self._base_station:
            return []
        
        current_time = time.time()
        
        try:
            sweeps = self._base_station.getData(self.DATA_TIMEOUT_MS)
            
            for sweep in sweeps:
                self._process_sweep_to_frame(sweep, current_time)
            
            complete_frames = self._collect_complete_frames(current_time)
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
        
        NOTA: Los valores se almacenan CRUDOS, sin aplicar tara.
        """
        self._stats['total_packets'] += 1
        
        try:
            node_id = sweep.nodeAddress()
            rssi = sweep.nodeRssi()
            timestamp_ns = sweep.timestamp().nanoseconds()
            
            self._update_node_status(node_id, rssi, current_time)
            
            for data_point in sweep.data():
                if hasattr(data_point, 'valid') and not data_point.valid():
                    self._stats['invalid_packets'] += 1
                    if node_id in self._node_status:
                        self._node_status[node_id].error_count += 1
                    continue
                
                try:
                    valor_crudo = data_point.as_float()
                except:
                    try:
                        valor_crudo = data_point.as_double()
                    except:
                        continue
                
                if not self._validate_value(valor_crudo):
                    self._stats['invalid_packets'] += 1
                    continue
                
                # Guardar valor CRUDO en cache
                if node_id in self._value_cache:
                    self._value_cache[node_id].append(valor_crudo)
                
                if node_id in self._node_status:
                    self._node_status[node_id].last_value = valor_crudo
                
                # Agregar valor CRUDO al frame (SIN aplicar tara)
                self._add_to_frame(timestamp_ns, node_id, valor_crudo, rssi)
                
                self._stats['valid_packets'] += 1
                
        except Exception as e:
            self._stats['invalid_packets'] += 1
            self._log("WARNING", f"Error procesando sweep: {e}")
    
    def _add_to_frame(self, timestamp_ns: int, node_id: int, value: float, rssi: int) -> None:
        """
        Agrega una lectura al frame correspondiente.
        Agrupa por timestamp con tolerancia de 10ms.
        """
        with self._data_lock:
            frame_key = self._find_frame_key(timestamp_ns)
            
            if frame_key is None:
                frame_key = timestamp_ns
                self._frame_buffer[frame_key] = AggregatedFrame(timestamp_ns=timestamp_ns)
            
            frame = self._frame_buffer[frame_key]
            frame.readings[node_id] = value
            frame.rssi_map[node_id] = rssi
    
    def _find_frame_key(self, timestamp_ns: int) -> Optional[int]:
        """Busca un frame existente con timestamp dentro de la tolerancia (10ms)."""
        for key in self._frame_buffer:
            if abs(key - timestamp_ns) <= self.TIMESTAMP_TOLERANCE_NS:
                return key
        return None
    
    def _collect_complete_frames(self, current_time: float) -> List[Dict[str, Any]]:
        """Recolecta frames completos y limpia frames expirados."""
        complete_frames = []
        frames_to_remove = []
        
        timeout_threshold = current_time - (self.FRAME_AGGREGATION_TIMEOUT_MS / 1000.0)
        
        with self._data_lock:
            for key, frame in list(self._frame_buffer.items()):
                if frame.is_complete(self._expected_node_ids):
                    frame.complete = True
                    complete_frames.append(self._format_frame(frame))
                    frames_to_remove.append(key)
                    self._stats['frames_complete'] += 1
                elif frame.creation_time < timeout_threshold:
                    frames_to_remove.append(key)
                    self._stats['frames_incomplete'] += 1
            
            for key in frames_to_remove:
                del self._frame_buffer[key]
        
        return complete_frames
    
    def _format_frame(self, frame: AggregatedFrame) -> Dict[str, Any]:
        """Formatea un frame completo para retorno."""
        total = sum(frame.readings.values())
        
        return {
            'timestamp': frame.timestamp_ns / 1e9,
            'timestamp_ns': frame.timestamp_ns,
            'values': dict(frame.readings),
            'rssi': dict(frame.rssi_map),
            'total': total,  # Suma de valores CRUDOS
            'complete': frame.complete
        }
    
    def _update_node_status(self, node_id: int, rssi: int, current_time: float) -> None:
        """Actualiza el status de un nodo."""
        if node_id not in self._node_status:
            self._node_status[node_id] = NodeStatus(node_id=node_id)
            self._value_cache[node_id] = deque(maxlen=self.VALUE_CACHE_SIZE)
            self._log("INFO", f"Nuevo nodo detectado: {node_id}")
        
        status = self._node_status[node_id]
        status.last_seen = current_time
        status.last_rssi = rssi
        status.packet_count += 1
        status.is_online = True
        
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
                self._cleanup_connection()
                
                if self.conectar(self._connection_string):
                    self._log("INFO", "✓ Reconexión exitosa!")
                    return
                    
            except SyncNetworkError as e:
                self._log("ERROR", f"Falló intento {attempt + 1}: {e}")
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
            
            self._wireless_nodes.clear()
            
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
        
        self._stop_beacon_monitor()
        self._cleanup_connection()
        
        with self._data_lock:
            self._frame_buffer.clear()
            self._completed_frames.clear()
        
        self._set_state(ConnectionState.DISCONNECTED)
        self._log("INFO", "✓ Desconectado")
    
    # =========================================================================
    # TARA - DELEGADA A DataProcessor
    # =========================================================================
    
    def tarar(self, node_id: int = None) -> None:
        """
        NOTA: La tara se maneja en DataProcessor, no en el driver.
        Este método existe solo para compatibilidad con la interfaz.
        """
        self._log("WARNING", "tarar() llamado en driver - la tara se maneja en DataProcessor")
    
    def reset_tarar(self) -> None:
        """
        NOTA: La tara se maneja en DataProcessor, no en el driver.
        Este método existe solo para compatibilidad con la interfaz.
        """
        self._log("WARNING", "reset_tarar() llamado en driver - la tara se maneja en DataProcessor")
    
    # =========================================================================
    # DESCUBRIMIENTO DE NODOS
    # =========================================================================
    
    def descubrir_nodos(self, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        """Descubre nodos wireless en la red."""
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
            'error_count': status.error_count
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
            'frame_buffer_size': len(self._frame_buffer),
            'sample_rate_hz': self.TARGET_SAMPLE_RATE_HZ,
            'timestamp_tolerance_ms': self.TIMESTAMP_TOLERANCE_NS / 1e6
        }
    
    def get_last_cached_value(self, node_id: int) -> Optional[float]:
        """Retorna el último valor CRUDO en cache para un nodo."""
        if node_id in self._value_cache and self._value_cache[node_id]:
            return self._value_cache[node_id][-1]
        return None


# =============================================================================
# ALIAS PARA COMPATIBILIDAD
# =============================================================================

RealPesaje = MSCLDriver


# =============================================================================
# FUNCIÓN DE UTILIDAD
# =============================================================================

def create_driver(nodos_config: Optional[Dict] = None) -> MSCLDriver:
    """Función factory para crear el driver."""
    if not MSCL_AVAILABLE:
        raise ImportError(
            "MSCL no está disponible. "
            "Instale la biblioteca MSCL o use el modo MOCK."
        )
    return MSCLDriver(nodos_config)
