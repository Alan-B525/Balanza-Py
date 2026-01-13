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
        self._expected_node_ids = set()
        for k, v in self.nodos_config.items():
            nid = v.get('id', 0)
            if nid > 0:
                self._expected_node_ids.add(nid)

        self._running = False
        self._thread = None
        self._frames = deque()
        self._state = 'disconnected'
        self._stats = {'total_packets': 0, 'valid_packets': 0, 'start_time': None}

    def conectar(self, puerto: str) -> bool:
        self._running = True
        self._state = 'sampling' if self._expected_node_ids else 'connected'
        self._stats['start_time'] = time.time()
        # Iniciar productor de frames
        self._thread = threading.Thread(target=self._producer_loop, daemon=True)
        self._thread.start()
        return True

    def _producer_loop(self):
        # Generar frames a 1 Hz
        period = 1
        while self._running:
            ts_ns = int(time.time() * 1e9)
            readings = {}
            rssi = {}
            for nid in self._expected_node_ids:
                # Valores simulados en rango típico
                val = random.uniform(1000.0, 2000.0)
                readings[nid] = val
                rssi[nid] = random.randint(-80, -30)

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
        for nid in sorted(self._expected_node_ids):
            nodos.append({
                'id': nid,
                'rssi': -40,
                'status': 'mock',
                'model': 'Mock-SG-Link',
                'serial': str(nid),
                'channels': [
                    {'channel': 'ch1', 'type': 'strain', 'value': 0.0, 'last_value': 0.0},
                    {'channel': 'ch2', 'type': 'strain', 'value': 0.0, 'last_value': 0.0}
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


RealPesajeMock = MockDriver
