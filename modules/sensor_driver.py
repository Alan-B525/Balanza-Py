"""
sensor_driver.py - Driver Industrial "Smart Join" (v6.0)

ESTRATEGIA CORRECTA:
1. No forzar conexión con nodos dormidos (evita error EEPROM).
2. Activar Beacon inmediatamente.
3. "Auto-Enrolamiento": Cuando un nodo despierta y manda un dato, 
   el driver lo detecta y lo registra en memoria automáticamente.
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
    ERROR = "error"

@dataclass
class AggregatedFrame:
    timestamp_ns: int
    readings: Dict[str, float] = field(default_factory=dict)
    rssi_map: Dict[int, int] = field(default_factory=dict)
    complete: bool = False
    creation_time: float = field(default_factory=time.time)
    
    def is_complete(self, expected_keys: Set[str]) -> bool:
        # Nota: en modo descubrimiento, expected_keys puede crecer dinámicamente
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
    DATA_TIMEOUT_MS = 500  # Muy rápido para no bloquear
    FRAME_TIMEOUT_S = 0.05
    TIMESTAMP_TOLERANCE_NS = 10_000_000 # 10ms

    def __init__(self, nodos_config: Optional[Dict] = None, use_sensor_config: bool = True, avoid_eeprom: bool = True):
        if not MSCL_AVAILABLE: raise ImportError("MSCL no encontrado")
        
        self.nodos_config = nodos_config or {}
        
        # Configuración Esperada (Base de datos de qué buscar)
        self._config_node_ids: Set[int] = set()
        self._config_data_keys: Set[str] = set()
        
        # Estado de Red Dinámico
        self._active_node_ids: Set[int] = set() # Nodos que ya despertaron y están enviando
        
        self._connection = None
        self._base_station = None
        
        self._state = ConnectionState.DISCONNECTED
        self._lock = threading.RLock()
        
        self._frame_buffer: Dict[int, AggregatedFrame] = {}
        self._value_cache: Dict[str, deque] = {}
        
        self._stats = {'total_packets': 0, 'start_time': None}
        
        self._parse_config()

    def _parse_config(self):
        """Carga la lista de nodos permitidos."""
        for name, cfg in self.nodos_config.items():
            nid = cfg.get('id', 0)
            if nid <= 0: continue
            
            ch_raw = cfg.get('ch', 'ch1').lower().replace("channel", "ch").replace(" ", "")
            self._config_node_ids.add(nid)
            key = f"{nid}:{ch_raw}"
            self._config_data_keys.add(key)
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

    def conectar(self, puerto: str, lista_nodos: List[int]):
        """
        Conecta a la BaseStation, configura los nodos y arranca la red sincronizada.
        """
        try:
            self.logger.info(f"Iniciando conexión en puerto {puerto}...")
            
            # 1. Conexión Serial
            self.connection = mscl.Connection.Serial(puerto)
            self.base_station = mscl.BaseStation(self.connection)
            
            # 2. Limpieza inicial: Asegurar estado limpio
            self.logger.info("Desactivando Beacon previo para configuración...")
            try:
                self.base_station.disableBeacon()
            except mscl.Error as e:
                self.logger.warning(f"No se pudo desactivar beacon (puede que ya esté apagado): {e}")

            # 3. Crear la Red de Muestreo Sincronizado
            self.network = mscl.SyncSamplingNetwork(self.base_station)
            
            # 4. Procesar y Añadir cada nodo
            nodos_exitosos = 0
            for node_address in lista_nodos:
                if self._preparar_y_agregar_nodo(node_address):
                    nodos_exitosos += 1
            
            if nodos_exitosos == 0:
                self.logger.error("No se pudo inicializar ningún nodo. Abortando conexión.")
                self.desconectar()
                return False

            # 5. Iniciar el Muestreo Sincronizado (El 'Disparo')
            self.logger.info("Iniciando muestreo sincronizado de la red (Start Sampling)...")
            try:
                self.network.startSampling()
                self.logger.info("¡Red iniciada correctamente! Beacon activo.")
            except mscl.Error as e:
                self.logger.error(f"Error crítico al iniciar muestreo de red: {e}")
                # Aquí podrías decidir si reintentar o fallar
                return False

            # 6. Actualizar estado y lanzar hilo de lectura
            self._state = ConnectionState.SAMPLING
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop_adquisicion)
            self._thread.start()
            
            return True

        except Exception as e:
            self.logger.critical(f"Error fatal en proceso de conexión: {e}")
            self.desconectar()
            return False

    def _preparar_y_agregar_nodo(self, node_address: int) -> bool:
        """
        Contacta, resetea a Idle, configura y añade un nodo a la red.
        """
        try:
            self.logger.info(f"[{node_address}] Conectando nodo...")
            node = mscl.WirelessNode(node_address, self.base_station)
            
            # A. Ping para verificar presencia
            response = node.ping()
            if not response.success():
                self.logger.error(f"[{node_address}] No responde al Ping. ¿Está encendido?")
                return False
                
            # B. Forzar IDLE (Crítico para poder configurar y añadir a red)
            self.logger.debug(f"[{node_address}] Forzando modo IDLE...")
            node.setToIdle()
            
            # C. Configuración (Ejemplo: Hardcodear configuración ideal)
            # Esto asegura que el nodo siempre tenga la config correcta, venga de donde venga.
            # Puedes sacar estos valores de un archivo de configuración si prefieres.
            config = mscl.WirelessNodeConfig(node)
            
            # Ejemplo: Configurar a 32 Hz
            if config.sampleRate() != mscl.SampleRate.Hertz(32):
                self.logger.info(f"[{node_address}] Configurando Sample Rate a 32Hz...")
                config.sampleRate(mscl.SampleRate.Hertz(32))
                config.apply()
            
            # D. Añadir a la red de software
            self.logger.info(f"[{node_address}] Añadiendo a la red sincronizada...")
            self.network.addNode(node)
            
            return True
            
        except mscl.Error as e:
            self.logger.error(f"[{node_address}] Error MSCL al preparar nodo: {e}")
            return False
        except Exception as e:
            self.logger.error(f"[{node_address}] Error general: {e}")
            return False

    def _force_reset_connection(self):
        try:
            if self._base_station:
                try:
                    self._base_station.disableBeacon()
                except:
                    pass
        finally:
            self._base_station = None
            self._connection = None
            self._active_node_ids.clear()
            self._frame_buffer.clear()
            self._state = ConnectionState.DISCONNECTED


    def desconectar(self):
        self.logger.info("Desconectando sistema...")
        self._stop_event.set()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        try:
            # Detener la red si existe
            if hasattr(self, 'base_station') and self.base_station:
                self.logger.info("Desactivando Beacon...")
                self.base_station.disableBeacon()
                
                # Opcional: Mandar comando de 'Set to Idle' a los nodos conocidos
                # para que dejen de buscar la red inmediatamente.
                if hasattr(self, 'network'):
                    # Nota: SyncSamplingNetwork no tiene un 'stop' global que ponga en idle a todos
                    # automáticamente en versiones viejas, pero apagar el beacon suele bastar.
                    pass

        except Exception as e:
            self.logger.error(f"Error durante la desconexión de MSCL: {e}")
        
        # Cerrar conexión serial
        if hasattr(self, 'connection'):
            try:
                self.connection.disconnect()
            except:
                pass
                
        self._state = ConnectionState.DISCONNECTED
        self.logger.info("Sistema desconectado.")


    # =========================================================================
    # LECTURA INTELIGENTE (AUTO-ENROLAMIENTO)
    # =========================================================================

    def obtener_datos(self) -> List[Dict[str, Any]]:
        if not self._base_station or self._state not in (ConnectionState.CONNECTED, ConnectionState.SAMPLING):
            return []

        now = time.time()

        try:
            sweeps = self._base_station.getData(self.DATA_TIMEOUT_MS)
            if sweeps:
                for sweep in sweeps:
                    self._process_sweep_atomic(sweep)
        except Exception as e:
            self._log(f"Error en adquisición de datos: {e}")
            self._state = ConnectionState.ERROR
            return []

        frames = self._collect_frames(now)
        if frames:
            try:
                # Log síntesis de lo que se va a devolver al procesador
                first = frames[0]
                keys = list(first.get('values', {}).keys())
                sample = {k: first.get('values', {}).get(k) for k in keys[:6]}
                #self._log(f"obtener_datos -> frames={len(frames)} keys_sample={keys[:6]} sample={sample}")
            except Exception:
                pass

        return frames

    def _process_sweep_atomic(self, sweep):
        try:
            nid = sweep.nodeAddress()

            # Filtro de red
            if nid not in self._config_node_ids:
                return

            # Auto-enrolamiento
            if nid not in self._active_node_ids:
                self._active_node_ids.add(nid)
                self._log(f"Nodo {nid} activo.")

            ts_ns = sweep.timestamp().nanoseconds()
            rssi = sweep.nodeRssi()

            # Extraer TODOS los datapoints primero
            values = {}

            for dp in sweep.data():
                try:
                    ch_name = str(dp.channelName()).lower()
                except:
                    continue

                ch_key = self._map_channel_name(ch_name)
                if not ch_key:
                    continue

                full_key = f"{nid}:{ch_key}"

                if full_key not in self._config_data_keys:
                    continue

                try:
                    val = dp.as_float()
                    values[full_key] = val
                    self._value_cache[full_key].append(val)
                except:
                    continue

            if values:
                self._insert_sweep_frame(ts_ns, values, nid, rssi)

        except Exception:
            pass

    def _map_channel_name(self, ch_name: str) -> Optional[str]:
        # Normalizar
        name = ch_name.lower().strip()
        
        # Lógica prioritaria para MSCL estándar
        if name in ('ch1', 'val1', 'strain1', 'load1'): return 'ch1'
        if name in ('ch2', 'val2', 'strain2', 'load2'): return 'ch2'
        if name in ('ch3', 'val3', 'strain3', 'load3'): return 'ch3'
        if name in ('ch4', 'val4', 'strain4', 'load4'): return 'ch4'
        
        # Lógica fallback (contiene el número pero no es un número random del timestamp)
        if '1' in name and ('ch' in name or 'val' in name): return 'ch1'
        if '2' in name and ('ch' in name or 'val' in name): return 'ch2'
        
        return None

    def _insert_sweep_frame(self, ts_ns, values, nid, rssi):
        with self._lock:
            # Buscar frame cercano (ventana temporal)
            target_ts = None
            for t in self._frame_buffer:
                if abs(t - ts_ns) <= self.TIMESTAMP_TOLERANCE_NS:
                    target_ts = t
                    break

            if target_ts is None:
                frame = AggregatedFrame(timestamp_ns=ts_ns)
                self._frame_buffer[ts_ns] = frame
            else:
                frame = self._frame_buffer[target_ts]

            frame.readings.update(values)
            frame.rssi_map[nid] = rssi


    def _process_active_sweep(self, sweep):
        """Procesa datos y detecta nodos activos."""
        try:
            nid = sweep.nodeAddress()
            
            # FILTRO: ¿Es un nodo de los nuestros?
            if nid not in self._config_node_ids: 
                return # Ignorar nodos vecinos

            # AUTO-ENROLAMIENTO
            if nid not in self._active_node_ids:
                self._active_node_ids.add(nid)
                self._log(f"¡Nodo {nid} detectado y activo! Recibiendo datos.")

            # Procesamiento Normal
            ts_ns = sweep.timestamp().nanoseconds()
            rssi = sweep.nodeRssi()
            
            for dp in sweep.data():
                # Sin chequeo .valid() por compatibilidad
                try:
                    ch_name = str(dp.channelName()).lower()
                except:
                    ch_name = "unknown"
                
                ch_key = None
                if "1" in ch_name and ("ch" in ch_name or "strain" in ch_name or "val" in ch_name):
                    ch_key = "ch1"
                elif "2" in ch_name and ("ch" in ch_name or "strain" in ch_name or "val" in ch_name):
                    ch_key = "ch2"
                elif "3" in ch_name: ch_key = "ch3"
                elif "4" in ch_name: ch_key = "ch4"
                
                if ch_key:
                    try:
                        val = dp.as_float()
                        full_key = f"{nid}:{ch_key}"
                        
                        # Solo procesamos canales que esperamos en config
                        if full_key in self._config_data_keys:
                            self._add_to_frame_buffer(ts_ns, full_key, val, rssi)
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
            frames = list(self._frame_buffer.items())

            for ts, frame in frames:
                # Claves esperadas SOLO de nodos activos
                expected = {
                    k for k in self._config_data_keys
                    if int(k.split(":")[0]) in self._active_node_ids
                }

                is_complete = expected.issubset(frame.readings.keys())
                is_expired = (now - frame.creation_time) > self.FRAME_TIMEOUT_S

                if is_complete or is_expired:
                    completed.append({
                        'timestamp': frame.timestamp_ns / 1e9,
                        'values': frame.readings.copy(),
                        'rssi': frame.rssi_map.copy(),
                        'complete': is_complete
                    })
                    expired.append(ts)
            for ts in expired:
                del self._frame_buffer[ts]

        return completed

    # =========================================================================
    # DESCUBRIMIENTO (Para el botón de la UI)
    # =========================================================================

    def descubrir_nodos(self, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        if not self._base_station: 
            return []

        self._log(f"Escaneando ({timeout_ms}ms)...")
        found = {}
        start = time.time()
        
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
            
        return res

    # COMPATIBILIDAD
    @property
    def state(self) -> ConnectionState: return self._state
    def esta_conectado(self) -> bool: return self._state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING)
    def get_statistics(self) -> Dict: return {'connection_state': self._state.value}

    def get_node_status(self, nid: int) -> Optional[Dict]: 
        # Determinar último `last_seen` agregando los timestamps de claves compuestas
        last = 0.0
        for k, t in getattr(self, '_last_seen', {}).items():
            try:
                num = int(str(k).split(":")[0])
                if num == nid and t > last:
                    last = t
            except Exception:
                continue
        is_online = (time.time() - last) < 5.0 if last > 0 else False
        return {'node_id': nid, 'is_online': is_online, 'last_seen': last}


    def tarar(self, nid=None): pass
    def reset_tarar(self): pass

def create_driver(nodos_config: Optional[Dict] = None, avoid_eeprom: bool = True) -> MSCLDriver:
    return MSCLDriver(nodos_config, avoid_eeprom=avoid_eeprom)