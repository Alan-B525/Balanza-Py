import time
import threading
import random
from collections import deque
from typing import Dict, Any, List, Optional

from .interfaces import ISistemaPesaje


class MockDriver(ISistemaPesaje):
    """Driver simulado para pruebas sin hardware.

    Genera frames periódicos con valores aleatorios para los nodos configurados.
    """

    def __init__(self, nodos_config: Optional[Dict[str, Any]] = None, use_sensor_config: bool = False):
        self.nodos_config = nodos_config or {}
        self.use_sensor_config = use_sensor_config

        self._stair_min = 0.0
        self._stair_max = 1200.0
        self._stair_step = 1
        self._stair_value = self._stair_min
        self._stair_direction = 1
        self._mock_frequency_hz = self._resolve_mock_frequency_hz()
        
        self._running = False
        self._thread = None
        self._frames = deque()
        self._state = 'disconnected'
        self._stats = {'total_packets': 0, 'valid_packets': 0, 'start_time': None}

        # Inicializar canales y estructuras usando la lógica centralizada
        self.update_nodes_config(self.nodos_config)

    def conectar(self, puerto: str) -> bool:
        self._running = True
        self._state = 'sampling' if self._expected_node_ids else 'connected'
        self._stats['start_time'] = time.time()
        # Iniciar productor de frames
        self._thread = threading.Thread(target=self._producer_loop, daemon=True)
        self._thread.start()
        return True

    def _producer_loop(self):
        # Gerar frames com frequência configurável
        period = 1.0 / max(self._mock_frequency_hz, 0.1)
        while self._running:
            ts_ns = int(time.time() * 1e9)
            readings = {}
            rssi = {}
            for nid in sorted(self._expected_node_ids):
                channels = sorted(list(self._node_channels.get(nid, {'ch1'})))
                
                # Determine role based on config for this node
                # Since we force single node, we can look up config easily
                try:
                     # Find config for this nid
                    node_cfg = None
                    if self.nodos_config:
                        for cfg in self.nodos_config.values():
                            if cfg.get('id') == nid:
                                node_cfg = cfg
                                break
                    
                    ch_angle = node_cfg.get('ch_angle', 'ch2') if node_cfg else 'ch2'
                except:
                    ch_angle = 'ch2'

                for channel in channels:
                    # Valores simulados por canal (escada na carga)
                    if channel == ch_angle:
                        # Ângulo fixo para não interferir na visualização da escada
                        val = 0.0
                    else:
                        # Carga em escada: 0 -> 1200 -> 0
                        val = self._next_stair_value()
                    
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
            self._frames.append(frame)
            # mantener un buffer razonable
            while len(self._frames) > 200:
                self._frames.popleft()
            time.sleep(period)

    def _next_stair_value(self) -> float:
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

        # Default
        return 20.0

    def esta_conectado(self) -> bool:
        return self._state in ('connected', 'sampling')

    def obtener_datos(self) -> List[Dict[str, Any]]:
        frames = []
        while self._frames:
            frames.append(self._frames.popleft())
        return frames

    def desconectar(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._state = 'disconnected'

    def descubrir_nodos(self, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        nodos = []
        # Construir lista de nodos basada en la configuración lógica cuando sea posible
        if self.nodos_config:
            # Agrupar por node id para listar todos los canales configurados por nodo
            nid_map = {}
            for logical, cfg in self.nodos_config.items():
                nid = cfg.get('id', 0) or self._logical_to_id.get(logical)
                ch = cfg.get('ch', 'ch1')
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
            for nid in sorted(self._expected_node_ids):
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
        return None

    def reset_tarar(self) -> None:
        return None

    def get_node_status(self, node_id: int):
        return {
            'node_id': node_id,
            'channel': 'ch1',
            'is_online': True,
            'is_configured': node_id in self._expected_node_ids,
            'last_seen': time.time(),
            'last_value': None,
            'last_rssi': -40,
            'avg_rssi': -40,
            'packet_count': 0,
            'error_count': 0
        }

    def get_statistics(self):
        uptime = 0.0
        if self._stats['start_time']:
            uptime = time.time() - self._stats['start_time']
        return {
            **self._stats,
            'uptime_seconds': uptime,
            'connection_state': self._state,
            'nodes_online': len(self._expected_node_ids),
            'nodes_configured': len(self._expected_node_ids)
        }

    def get_last_cached_value(self, node_id: int):
        # Retornar None como placeholder
        return None

    def update_nodes_config(self, new_nodes_config: Dict[str, Any]):
        """Actualiza la configuración de nodos en tiempo real."""
        self.nodos_config = new_nodes_config
        self._expected_node_ids = set()
        self._node_channels = {}
        self._logical_to_id = {}
        
        # Re-inicializar estructuras internas con la nueva config
        # (Lógica simplificada duplicada de __init__)
        if isinstance(self.nodos_config, dict) and len(self.nodos_config) > 0:
            # En mock forzamos single node
            first_logical = next(iter(self.nodos_config))
            cfg = self.nodos_config[first_logical]
            nid = cfg.get('id', 4248)
            ch_load = cfg.get('ch_load', 'ch1')
            ch_angle = cfg.get('ch_angle', 'ch2')
            
            self._logical_to_id[first_logical] = nid
            self._expected_node_ids.add(nid)
            self._node_channels[nid] = {ch_load, ch_angle}

        # Recalcular frequência após atualização de config
        self._mock_frequency_hz = self._resolve_mock_frequency_hz()


RealPesajeMock = MockDriver
