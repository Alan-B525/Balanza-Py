import time
import threading
import random
from collections import deque
from typing import Dict, Any, List, Optional

from .interfaces import ISistemaPesaje, ConnectionState


class MockDriver(ISistemaPesaje):
    """Driver simulado para pruebas sin hardware.

    Genera frames periódicos con valores aleatorios para los nodos configurados.
    """

    def __init__(self, nodos_config: Optional[Dict[str, Any]] = None, use_sensor_config: bool = False):
        self.nodos_config = nodos_config or {}
        self.use_sensor_config = use_sensor_config
        self._lock = threading.Lock()

        self._stair_min = 0.0
        self._stair_max = 1200.0
        self._stair_step = 1
        self._stair_value = self._stair_min
        self._stair_direction = 1
        self._mock_frequency_hz = 20.0
        
        self._running = False
        self._thread = None
        self._frames = deque()
        self._state = ConnectionState.DISCONNECTED
        self._stats = {'total_packets': 0, 'valid_packets': 0, 'start_time': None}
        self._progress_cb = None

        # Inicializar canales y estructuras usando la lógica centralizada
        self.update_nodes_config(self.nodos_config)

    def conectar(self, puerto: str) -> bool:
        with self._lock:
            self._running = True
            self._state = ConnectionState.SAMPLING if self._expected_node_ids else ConnectionState.CONNECTED
            self._stats['start_time'] = time.time()
        # Iniciar productor de frames
        self._thread = threading.Thread(target=self._producer_loop, daemon=True)
        self._thread.start()
        return True

    def _producer_loop(self):
        # Gerar frames com frequência configurável
        while True:
            with self._lock:
                if not self._running:
                    break
                period = 1.0 / max(self._mock_frequency_hz, 0.1)
                ts_ns = int(time.time() * 1e9)
                readings = {}
                rssi = {}
                expected_ids = sorted(self._expected_node_ids)
                nodos_cfg = self.nodos_config
                
            for nid in expected_ids:
                channels = sorted(list(self._node_channels.get(nid, {'ch1'})))
                # Lookup node config for load/angle channels
                try:
                    node_cfg = None
                    if nodos_cfg:
                        for cfg in nodos_cfg.values():
                            if cfg.get('id') == nid:
                                node_cfg = cfg
                                break
                    
                    simulate_failure = bool(node_cfg.get('simulate_failure', False)) if node_cfg else False
                    drop_rate = float(node_cfg.get('packet_drop_rate', 0.0)) if node_cfg else 0.0
                    
                    if simulate_failure:
                        # Simular fallo completo (desconexión)
                        continue
                    if drop_rate > 0.0 and random.random() < drop_rate:
                        # Simular pérdida de paquete transitoria
                        continue

                    ch_load = node_cfg.get('ch_load', 'ch1') if node_cfg else 'ch1'
                    ch_angles = node_cfg.get('ch_angles') if node_cfg else None
                    if not isinstance(ch_angles, list):
                        ch_single = node_cfg.get('ch_angle', 'ch2') if node_cfg else 'ch2'
                        ch_angles = [ch_single]
                    ch_angles = [str(ch).strip() for ch in ch_angles if str(ch).strip()]
                    load_enabled = bool(node_cfg.get('load_enabled', True)) if node_cfg else True
                except Exception:
                    ch_load = 'ch1'
                    ch_angles = ['ch2']
                    load_enabled = True

                for channel in channels:
                    if load_enabled and channel == ch_load:
                        # Carga em escada: 0 -> 1200 -> 0
                        val = self._next_stair_value()
                    elif channel in ch_angles:
                        val = 0.0
                    else:
                        val = 0.0
                    
                    key = f"{nid}:{channel}"
                    readings[key] = val
                    rssi[key] = random.randint(-80, -30)

            frame = {
                'timestamp': ts_ns / 1e9,
                'timestamp_ns': ts_ns,
                'values': readings,
                'rssi': rssi,
                'total': sum(readings.values()),
                'complete': True
            }
            
            with self._lock:
                self._frames.append(frame)
                self._stats['total_packets'] += 1
                self._stats['valid_packets'] += 1
                # mantener un buffer razonable
                while len(self._frames) > 200:
                    self._frames.popleft()
            
            time.sleep(period)

    def _next_stair_value(self) -> float:
        # Nota: llamarse dentro de _producer_loop que ya tiene el lock de _lock
        value = self._stair_value
        next_value = self._stair_value + (self._stair_step * self._stair_direction)
        if next_value >= self._stair_max:
            next_value = self._stair_max
            self._stair_direction = -1
        elif next_value <= self._stair_min:
            next_value = self._stair_min
            self._stair_direction = 1
        self._stair_value = next_value
        return value

    def _resolve_mock_frequency_hz(self) -> float:
        # Prioridade 1: configuração do primeiro nó lógico
        try:
            if isinstance(self.nodos_config, dict) and self.nodos_config:
                first_logical = next(iter(self.nodos_config))
                cfg = self.nodos_config.get(first_logical) or {}
                val = cfg.get('mock_frequency_hz')
                if val is not None:
                    hz = float(val)
                    if hz > 0:
                        return hz
        except Exception:
            pass

        # Prioridade 2: settings.json global
        try:
            import config
            settings = config.load_settings()
            if isinstance(settings, dict):
                val = settings.get('mock_sample_rate_hz')
                if val is not None:
                    hz = float(val)
                    if hz > 0:
                        return hz
        except Exception:
            pass

        return 20.0

    def esta_conectado(self) -> bool:
        with self._lock:
            return self._state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING)

    def obtener_datos(self) -> List[Dict[str, Any]]:
        with self._lock:
            frames = []
            while self._frames:
                frames.append(self._frames.popleft())
            return frames

    def desconectar(self) -> None:
        with self._lock:
            self._running = False
            self._state = ConnectionState.DISCONNECTED
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def set_progress_callback(self, callback) -> None:
        with self._lock:
            self._progress_cb = callback

    def get_recovered_count(self) -> int:
        with self._lock:
            if self._state in (ConnectionState.CONNECTED, ConnectionState.SAMPLING):
                return len(self._expected_node_ids)
            return 0

    def descubrir_nodos(self, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        nodos = []
        with self._lock:
            config_copy = self.nodos_config.copy() if self.nodos_config else {}
            expected_ids = self._expected_node_ids.copy()
            logical_to_id = self._logical_to_id.copy()

        if config_copy:
            nid_map = {}
            for logical, cfg in config_copy.items():
                if not isinstance(cfg, dict):
                    cfg = {}
                nid = cfg.get('id', 0) or logical_to_id.get(logical, 0)
                if nid <= 0:
                    continue
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

                for ch in channels:
                    nid_map.setdefault(nid, set()).add(ch)
            for nid, channels in nid_map.items():
                channels_list = [{'channel': ch, 'type': 'strain', 'value': 0.0, 'last_value': 0.0} for ch in sorted(channels)]
                nodos.append({
                    'id': nid,
                    'rssi': -40,
                    'status': 'mock',
                    'model': 'Mock-SG-Link',
                    'serial': str(nid),
                    'channels': channels_list,
                    'sample_rate': '32'
                })
        else:
            for nid in sorted(expected_ids):
                nodos.append({
                    'id': nid,
                    'rssi': -40,
                    'status': 'mock',
                    'model': 'Mock-SG-Link',
                    'serial': str(nid),
                    'channels': [
                        {'channel': 'ch1', 'type': 'strain', 'value': 0.0, 'last_value': 0.0},
                    ],
                    'sample_rate': '32'
                })
        return nodos

    def tarar(self, node_id: int = None) -> None:
        pass

    def reset_tarar(self) -> None:
        pass

    def get_node_status(self, node_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            configured = node_id in self._expected_node_ids
        return {
            'node_id': node_id,
            'channel': 'ch1',
            'is_online': True,
            'is_configured': configured,
            'last_seen': time.time(),
            'last_value': None,
            'last_rssi': -40,
            'avg_rssi': -40,
            'packet_count': 0,
            'error_count': 0
        }

    def get_statistics(self) -> Dict[str, Any]:
        with self._lock:
            uptime = 0.0
            if self._stats['start_time']:
                uptime = time.time() - self._stats['start_time']
            state_val = self._state.value
            expected_count = len(self._expected_node_ids)
            stats_copy = self._stats.copy()

        return {
            **stats_copy,
            'uptime_seconds': uptime,
            'connection_state': state_val,
            'nodes_online': expected_count,
            'nodes_configured': expected_count
        }

    def update_nodes_config(self, new_nodes_config: Dict[str, Any]) -> None:
        """Actualiza la configuración de nodos en tiempo real."""
        with self._lock:
            self.nodos_config = new_nodes_config
            self._expected_node_ids = set()
            self._node_channels = {}
            self._logical_to_id = {}
            
            if isinstance(self.nodos_config, dict) and len(self.nodos_config) > 0:
                for logical, cfg in self.nodos_config.items():
                    if not isinstance(cfg, dict):
                        cfg = {}
                    nid = cfg.get('id', 0)
                    if nid <= 0:
                        continue
                    ch_load = cfg.get('ch_load', 'ch1')
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

                    self._logical_to_id[logical] = nid
                    self._expected_node_ids.add(nid)
                    self._node_channels[nid] = set(channels)

            self._mock_frequency_hz = self._resolve_mock_frequency_hz()


RealPesajeMock = MockDriver
