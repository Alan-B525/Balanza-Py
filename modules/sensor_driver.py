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

# =============================================================================
# ESTRUCTURAS DE DATOS (Compatibilidad Main App)
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
        return expected_keys.issubset(set(self.readings.keys()))

try:
    from .interfaces import ISistemaPesaje
except ImportError:
    class ISistemaPesaje: pass

# =============================================================================
# CLASE PRINCIPAL DEL DRIVER
# =============================================================================

class MSCLDriver(ISistemaPesaje):

    # Configuración de Hardware
    BAUD_RATE = 3000000
    DATA_TIMEOUT_MS = 100    # Timeout corto para lectura no bloqueante
    FRAME_TIMEOUT_S = 0.05   # Ventana de agregación
    TIMESTAMP_TOLERANCE_NS = 20_000_000 # 20ms tolerancia de sincronización
    
    # Configuración
    RECOVERY_TIMEOUT_S = 30  # Tiempo máx intentando despertar un nodo
    SAMPLE_RATE_HZ = 0.5     # 1 muestra cada 2 segundos

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

        self._parse_config()
        # Último recuento de nodos recuperados tras intentar conectar
        self._last_recovered_count = 0

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
            nid = cfg.get('id', 0)
            if nid <= 0: continue
            self._config_node_ids.add(nid)

            # Usar canales configurados (permite mover ángulo a ch3, etc.)
            ch_load = cfg.get('ch_load', cfg.get('ch', 'ch1'))
            ch_angle = cfg.get('ch_angle', 'ch2')

            # Channel Load
            key_load = f"{nid}:{ch_load}"
            self._config_data_keys.add(key_load)
            self._value_cache[key_load] = deque(maxlen=10)

            # Channel Angle
            key_angle = f"{nid}:{ch_angle}"
            self._config_data_keys.add(key_angle)
            self._value_cache[key_angle] = deque(maxlen=10)

    def _log(self, msg):
        """Wrapper de log para integrarse con el sistema o imprimir."""
        try:
            from . import logger
            logger.info(f"[MSCL] {msg}")
        except:
            print(f"[MSCL] {msg}")

    # =========================================================================
    # LÓGICA DE CONEXIÓN
    # =========================================================================

    def conectar(self, puerto: str) -> bool:
        with self._lock:
            if self._state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING):
                return True

            self._state = ConnectionState.CONNECTING
            self._emit_progress(f"Iniciando Conexão em {puerto} @ {self.BAUD_RATE}...")

            try:
                # 1. Conexión Física
                self._connection = mscl.Connection.Serial(puerto, self.BAUD_RATE)
                self._base_station = mscl.BaseStation(self._connection)

                # 2. SILENCIO RADIAL (CRÍTICO)
                # Apagamos el Beacon y esperamos a que los nodos "zombies" (que creen que siguen midiendo)
                # se den cuenta de que la red cayó y pasen a modo escucha.
                self._emit_progress("Passo 1: Silenciando rede (6s)...")
                try:
                    self._base_station.disableBeacon()
                except: 
                    pass
                
                # Pausa obligatoria
                time.sleep(6)

                # 3. GESTIÓN Y RECUPERACIÓN DE NODOS
                self._network = mscl.SyncSamplingNetwork(self._base_station)
                nodos_recuperados = 0
                
                if not self._config_node_ids:
                    self._emit_progress("AVISO: Nenhum nó configurado em settings.json.")

                for nid in self._config_node_ids:
                    self._emit_progress(f"Tentando recuperar nó {nid}...")
                    if self._recuperar_y_preparar_nodo(nid):
                        self._emit_progress(f"Nó {nid} recuperado.")
                        nodos_recuperados += 1
                    else:
                        self._emit_progress(f"Nó {nid} NÃO recuperado.")
                
                if nodos_recuperados == 0 and self._config_node_ids:
                    self._log("ERRO: Não foi possível conectar a nenhum nó configurado.")
                    self.desconectar()
                    return False

                # Si la recuperación fue parcial, intentar reset del beacon/base station y reintentar nodos faltantes
                total_expected = len(self._config_node_ids) if self._config_node_ids else 0
                if total_expected and nodos_recuperados < total_expected:
                    missing = set(self._config_node_ids) - set(self._active_node_ids)
                    if missing:
                        self._emit_progress(f"Conexão parcial ({nodos_recuperados}/{total_expected}). Tentando reset do beacon e reintentar {len(missing)} nó(s)...")
                        # Intentar desactivar beacon -> esperar -> reactivar
                        try:
                            try:
                                self._base_station.disableBeacon()
                            except Exception:
                                pass
                            time.sleep(1.0)
                            if hasattr(self._base_station, 'enableBeacon'):
                                try:
                                    self._base_station.enableBeacon()
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # Si la base station no responde, intentar recrear la conexión física
                        try:
                            try:
                                if self._connection:
                                    try:
                                        self._connection.disconnect()
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            try:
                                self._connection = mscl.Connection.Serial(puerto, self.BAUD_RATE)
                                self._base_station = mscl.BaseStation(self._connection)
                                self._network = mscl.SyncSamplingNetwork(self._base_station)
                            except Exception:
                                pass
                        except Exception:
                            pass

                        # Reintentar nodos faltantes
                        for nid in list(missing):
                            try:
                                self._emit_progress(f"Tentando novamente o nó {nid} após reset do beacon...")
                                if self._recuperar_y_preparar_nodo(nid):
                                    self._emit_progress(f"Nó {nid} recuperado após reset.")
                                    nodos_recuperados += 1
                            except Exception:
                                continue

                        # Estado final tras reintentos
                        try:
                            self._emit_progress(f"Tentativas concluídas. Nós recuperados agora: {nodos_recuperados}/{total_expected}")
                        except Exception:
                            pass

                # 4. APLICAR CONFIGURACIÓN A LA RED
                # Este paso envía la tabla de slots TDMA al Gateway
                self._emit_progress("Passo 3: Aplicando configuração de rede ao Gateway...")
                try:
                    self._network.applyConfiguration()
                except Exception as e:
                    self._log(f"Aviso: falha ao aplicar configuração de rede: {e}")

                # 5. INICIAR MUESTREO (Fix V5/V6)
                self._emit_progress(f"Passo 4: Iniciando amostragem ({nodos_recuperados} nós)...")
                try:
                    self._network.startSampling()
                    self._emit_progress(">>> REDE OPERACIONAL (Beacon Ativo) <<<")
                except Exception as e:
                    self._log(f"Erro crítico ao iniciar rede: {e}")
                    self.desconectar()
                    return False

                # Informar cuántos nodos se recuperaron
                try:
                    total_configured = len(self._config_node_ids) if self._config_node_ids else 0
                    self._emit_progress(f"Nós recuperados: {nodos_recuperados}/{total_configured}")
                except Exception:
                    pass

                self._state = ConnectionState.SAMPLING
                # Guardar el recuento para consultas externas
                try:
                    self._last_recovered_count = nodos_recuperados
                except Exception:
                    self._last_recovered_count = 0
                # Considerar conexión exitosa sólo si recuperamos todos los nodos configurados
                if self._config_node_ids:
                    if nodos_recuperados == len(self._config_node_ids):
                        return True
                    else:
                        # Recuperación parcial: iniciamos muestreo pero devolvemos False
                        return False
                else:
                    # Si no hay nodos configurados, tratamos como éxito
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
            while not status.complete(timeout_ms):
                pass
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
        node = mscl.WirelessNode(node_id, self._base_station)
        
        start_time = time.time()
        encontrado = False

        # Bucle de persistencia para despertar nodos dormidos
        attempts = 0
        while (time.time() - start_time) < self.RECOVERY_TIMEOUT_S:
            attempts += 1
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
                    # ping falló; seguiremos intentando y usaremos fallback discovery cada cierto número de intentos
                    pass

                # Fallback: cada 8 intentos verificar descubrimientos pasivos
                if attempts % 8 == 0:
                    try:
                        self._log(f"[{node_id}] Ping falló; verificando descubrimientos pendientes...")
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
                    except:
                        pass # Si falla, no importa, ya lo intentamos

            # 2. Apagar Beacon (Fundamental para detener sincronización)
            if self._base_station:
                try:
                    self._base_station.disableBeacon()
                    self._log("Beacon desativado.")
                except:
                    pass
            
            # 3. Cerrar conexión física
            if self._connection:
                try:
                    self._connection.disconnect()
                except:
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
                    ch_str = str(dp.channelName()).lower()
                    ch_key = None
                    
                    if "1" in ch_str and ("ch" in ch_str or "val" in ch_str): ch_key = "ch1"
                    elif "2" in ch_str and ("ch" in ch_str or "val" in ch_str): ch_key = "ch2"
                    elif "3" in ch_str: ch_key = "ch3"
                    elif "4" in ch_str: ch_key = "ch4"

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
                            except:
                                # Fallback extremo si as_float falla
                                continue
                            
                            values[full_key] = val
                            
                            # Cache simple para debug
                            if full_key in self._value_cache:
                                self._value_cache[full_key].append(val)
                except:
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
        except:
            self._log("Fallo en AutoDiscovery, retornando vacío.")

        return list(found.values())

    # =========================================================================
    # INTERFAZ Y COMPATIBILIDAD
    # =========================================================================

    @property
    def state(self) -> ConnectionState: 
        return self._state
    
    def esta_conectado(self) -> bool: 
        return self._state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING)
    
    def get_statistics(self) -> Dict: 
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

# Factory function requerida por main.py
def create_driver(nodos_config: Optional[Dict] = None, avoid_eeprom: bool = True) -> MSCLDriver:
    return MSCLDriver(nodos_config, avoid_eeprom=avoid_eeprom)