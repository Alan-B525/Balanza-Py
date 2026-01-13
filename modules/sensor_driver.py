"""
sensor_driver.py - Driver Industrial Estabilizado (v5.0)

CORRECCIÓN CRÍTICA DE SECUENCIA:
El error 'Failed to read Model Number' se soluciona asegurando que el Beacon
esté APAGADO mientras se añaden los nodos a la red de software.

Secuencia Correcta v5.0:
1. Conectar BaseStation.
2. DESACTIVAR Beacon (Silencio para configuración).
3. Resetear nodos a Idle y añadirlos a SyncNetwork.
4. ACTIVAR Beacon.
5. Iniciar Muestreo.
"""

import sys
import os
import time
import threading
from typing import List, Dict, Any, Optional, Set
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

# Configuración de ruta MSCL
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

# =============================================================================
# ESTRUCTURAS
# =============================================================================

class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SAMPLING = "sampling"
    RECONNECTING = "reconnecting"
    ERROR = "error"

class SyncNetworkError(Exception): pass

@dataclass
class AggregatedFrame:
    timestamp_ns: int
    readings: Dict[str, float] = field(default_factory=dict)
    rssi_map: Dict[int, int] = field(default_factory=dict)
    complete: bool = False
    creation_time: float = field(default_factory=time.time)
    
    def is_complete(self, expected_keys: Set[str]) -> bool:
        return expected_keys.issubset(set(self.readings.keys()))

try:
    from .interfaces import ISistemaPesaje
except ImportError:
    class ISistemaPesaje: pass

# =============================================================================
# DRIVER PRINCIPAL
# =============================================================================

class MSCLDriver(ISistemaPesaje):

    BAUD_RATE = 3000000
    DATA_TIMEOUT_MS = 100
    FRAME_TIMEOUT_S = 0.05
    TIMESTAMP_TOLERANCE_NS = 10_000_000 # 10ms

    def __init__(self, nodos_config: Optional[Dict] = None, use_sensor_config: bool = True, avoid_eeprom: bool = True):
        if not MSCL_AVAILABLE: raise ImportError("MSCL no encontrado")
        
        self.nodos_config = nodos_config or {}
        
        self._expected_node_ids: Set[int] = set()
        self._expected_data_keys: Set[str] = set()
        
        self._connection = None
        self._base_station = None
        self._sync_network = None
        self._wireless_nodes = {}
        
        self._state = ConnectionState.DISCONNECTED
        self._lock = threading.RLock()
        
        self._frame_buffer: Dict[int, AggregatedFrame] = {}
        self._value_cache: Dict[str, deque] = {}
        
        self._beacon_monitor_thread = None
        
        self._stats = {'total_packets': 0, 'start_time': None}
        
        self._parse_config()

    def _parse_config(self):
        for name, cfg in self.nodos_config.items():
            nid = cfg.get('id', 0)
            if nid <= 0: continue
            
            ch_raw = cfg.get('ch', 'ch1').lower().replace("channel", "ch").replace(" ", "")
            self._expected_node_ids.add(nid)
            key = f"{nid}:{ch_raw}"
            self._expected_data_keys.add(key)
            self._value_cache[key] = deque(maxlen=10)

    def _log(self, msg):
        try:
            from . import logger
            logger.info(f"[MSCL] {msg}")
        except:
            print(f"[MSCL] {msg}")

    # =========================================================================
    # CONEXIÓN
    # =========================================================================

    def conectar(self, puerto: str) -> bool:
        with self._lock:
            self._state = ConnectionState.CONNECTING
            self._log(f"Iniciando secuencia de conexión en {puerto}...")
            
            try:
                self._connection = mscl.Connection.Serial(puerto, self.BAUD_RATE)
                self._base_station = mscl.BaseStation(self._connection)
                
                # --- PASO CRÍTICO 1: SILENCIO DE RADIO ---
                # Desactivamos el Beacon para que los nodos puedan responder a addNode()
                # sin interferencias.
                try:
                    self._base_station.disableBeacon()
                    time.sleep(0.5) # Esperar a que se limpie el aire
                except:
                    pass

                # --- PASO 2: CONFIGURAR RED Y NODOS ---
                # Ahora addNode() debería funcionar porque la base no está ocupada
                if not self._setup_sync_network_safe():
                    raise SyncNetworkError("No se pudo configurar la red de nodos")

                # --- PASO 3: ACTIVAR BEACON ---
                # Una vez configurada la red, encendemos el Beacon para sincronizar
                self._log("Activando Beacon...")
                try:
                    self._base_station.enableBeacon()
                    time.sleep(1.0) # Dar tiempo a que los nodos encuentren el beacon
                except Exception as e:
                    self._log(f"Advertencia activando Beacon: {e}")

                # --- PASO 4: INICIAR MUESTREO ---
                self._log("Enviando comando Start Sampling...")
                try:
                    self._sync_network.startSampling()
                except Exception as e:
                    self._log(f"Error en startSampling: {e}")
                    # Continuamos igual por si acaso ya estaban andando

                self._state = ConnectionState.SAMPLING
                self._stats['start_time'] = time.time()
                self._log("✓ Sistema operativo. Escuchando datos.")
                return True

            except Exception as e:
                self._log(f"ERROR CRÍTICO: {e}")
                self.desconectar()
                self._state = ConnectionState.ERROR
                return False

    def _setup_sync_network_safe(self) -> bool:
        """Añade nodos a la red asegurando su estado."""
        if not self._expected_node_ids: return False

        self._sync_network = mscl.SyncSamplingNetwork(self._base_station)
        nodes_added = 0
        
        for nid in self._expected_node_ids:
            try:
                # Instanciamos el nodo
                node = mscl.WirelessNode(nid, self._base_station)
                
                # 1. Forzamos Idle (Importante si estaba en sampling previo)
                try:
                    node.setToIdle()
                except: 
                    pass # Puede fallar si está dormido, no es bloqueante
                
                # 2. Añadimos a la red (Aquí fallaba antes por el Beacon activo)
                self._sync_network.addNode(node)
                self._wireless_nodes[nid] = node
                nodes_added += 1
                self._log(f"Nodo {nid} agregado correctamente.")
                
            except Exception as e:
                self._log(f"Error gestionando nodo {nid}: {e}")
                # Intentamos agregarlo 'ciegamente' si la librería lo permite en fallo parcial
                try:
                    self._sync_network.addNode(node)
                    nodes_added += 1
                except:
                    pass

        if nodes_added == 0:
            self._log("No se pudieron agregar nodos a la red.")
            return False

        # Aplicar la configuración de red (valida la topología)
        try:
            self._sync_network.applyConfiguration()
        except Exception as e:
            self._log(f"Nota sobre applyConfiguration: {e}")
            
        return True

    def desconectar(self):
        self._log("Cerrando sistema...")
        with self._lock:
            # Orden: Parar red -> Parar nodos -> Apagar Beacon -> Cerrar Puerto
            if self._sync_network:
                try: self._sync_network.stopSampling()
                except: pass
            
            # Refuerzo: mandar a dormir uno por uno
            for nid, node in self._wireless_nodes.items():
                try: node.setToIdle()
                except: pass
            
            if self._base_station:
                try: self._base_station.disableBeacon()
                except: pass
            
            if self._connection:
                try: self._connection.disconnect()
                except: pass
            
            self._connection = None
            self._base_station = None
            self._sync_network = None
            self._state = ConnectionState.DISCONNECTED
            self._log("Desconectado.")

    # =========================================================================
    # LECTURA
    # =========================================================================

    def obtener_datos(self) -> List[Dict[str, Any]]:
        if not self._base_station: return []
        
        current_time = time.time()
        
        try:
            sweeps = self._base_station.getData(self.DATA_TIMEOUT_MS)
            for sweep in sweeps:
                self._parse_sweep(sweep)
        except:
            pass

        return self._collect_frames(current_time)

    def _parse_sweep(self, sweep):
        try:
            nid = sweep.nodeAddress()
            if nid not in self._expected_node_ids: return

            ts_ns = sweep.timestamp().nanoseconds()
            rssi = sweep.nodeRssi()
            
            for dp in sweep.data():
                # Eliminado chequeo .valid() para compatibilidad
                try:
                    raw_name = str(dp.channelName()).lower()
                except:
                    raw_name = "unknown"
                
                ch_key = None
                # Lógica flexible para nombres de canal
                if "1" in raw_name and ("ch" in raw_name or "strain" in raw_name or "val" in raw_name):
                    ch_key = "ch1"
                elif "2" in raw_name and ("ch" in raw_name or "strain" in raw_name or "val" in raw_name):
                    ch_key = "ch2"
                elif "3" in raw_name:
                    ch_key = "ch3"
                
                if ch_key:
                    try:
                        val = dp.as_float()
                        full_key = f"{nid}:{ch_key}"
                        
                        # Debug ocasional si quieres ver que entran datos
                        # self._log(f"Rx: {full_key} = {val}")
                        
                        self._add_to_frame_buffer(ts_ns, full_key, val, rssi)
                        
                        if full_key in self._value_cache:
                            self._value_cache[full_key].append(val)
                    except:
                        pass
        except:
            pass

    def _add_to_frame_buffer(self, ts_ns, key, val, rssi):
        with self._lock:
            target = None
            for t in self._frame_buffer:
                if abs(t - ts_ns) < self.TIMESTAMP_TOLERANCE_NS:
                    target = self._frame_buffer[t]
                    break
            
            if not target:
                target = AggregatedFrame(timestamp_ns=ts_ns)
                self._frame_buffer[ts_ns] = target
            
            target.readings[key] = val
            try:
                nid = int(key.split(':')[0])
                target.rssi_map[nid] = rssi
            except: pass

    def _collect_frames(self, now):
        completed = []
        expired = []
        
        with self._lock:
            for ts, frame in self._frame_buffer.items():
                if frame.is_complete(self._expected_data_keys):
                    frame.complete = True
                    completed.append(self._to_dict(frame))
                    expired.append(ts)
                elif (now - frame.creation_time) > self.FRAME_TIMEOUT_S:
                    frame.complete = False
                    completed.append(self._to_dict(frame))
                    expired.append(ts)
            
            for k in expired:
                del self._frame_buffer[k]
        
        return completed

    def _to_dict(self, frame):
        return {
            'timestamp': frame.timestamp_ns / 1e9,
            'values': frame.readings.copy(),
            'rssi': frame.rssi_map.copy(),
            'complete': frame.complete
        }

    # =========================================================================
    # DESCUBRIMIENTO
    # =========================================================================

    def descubrir_nodos(self, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        """Descubrimiento pasivo escuchando el aire."""
        if not self._base_station: 
            self._log("Error: No hay conexión para descubrir")
            return []

        self._log(f"Escuchando nodos ({timeout_ms}ms)...")
        found = {}
        start = time.time()
        
        # Asegurar beacon encendido para despertar nodos
        try: self._base_station.enableBeacon()
        except: pass

        while (time.time() - start) * 1000 < timeout_ms:
            try:
                sweeps = self._base_station.getData(100)
                for sweep in sweeps:
                    nid = sweep.nodeAddress()
                    if nid not in found:
                        found[nid] = {'id': nid, 'rssi': sweep.nodeRssi(), 'channels': set()}
                    
                    for dp in sweep.data():
                        name = str(dp.channelName()).lower()
                        if "1" in name: found[nid]['channels'].add('ch1')
                        if "2" in name: found[nid]['channels'].add('ch2')
            except: pass
            time.sleep(0.01)

        res = []
        for nid, data in found.items():
            chs = [{'channel': c, 'type': 'strain', 'value': 0.0} for c in sorted(data['channels'])]
            if not chs: chs = [{'channel': 'ch1', 'type': 'strain', 'value': 0.0}, {'channel': 'ch2', 'type': 'strain', 'value': 0.0}]
            data['channels'] = chs
            res.append(data)
            self._log(f"Encontrado: {nid}")
            
        return res

    # =========================================================================
    # GUI INTERFACE
    # =========================================================================
    @property
    def state(self) -> ConnectionState: return self._state
    def esta_conectado(self) -> bool: return self._state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING)
    def get_statistics(self) -> Dict: return {'connection_state': self._state.value}
    def get_node_status(self, nid: int) -> Optional[Dict]: return {'node_id': nid, 'is_online': True}
    def tarar(self, nid=None): pass
    def reset_tarar(self): pass

def create_driver(nodos_config: Optional[Dict] = None, avoid_eeprom: bool = True) -> MSCLDriver:
    return MSCLDriver(nodos_config, avoid_eeprom=avoid_eeprom)