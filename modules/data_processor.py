from collections import deque
from typing import Dict, List, Any
import time

class DataProcessor:
    """
    Maneja la lógica de negocio: filtrado, mapeo y tara matemática.
    """
    def __init__(self, nodos_config: Dict, window_size: int = 10):
        self.nodos_config = nodos_config
        self.window_size = window_size
        
        # Buffers para promedio móvil: {node_id: deque([val1, val2...])}
        self._buffers = {}
        
        # Valores de tara actuales: {node_id: float}
        self._tares = {}
        
        # Última vez que se vio cada nodo: {node_id: timestamp}
        self._last_seen = {}
        
        # Estado de conexión previo para evitar spam de logs
        self._node_connected_state = {}

        # Inicializar estructuras
        for key, cfg in self.nodos_config.items():
            nid = cfg['id']
            self._buffers[nid] = deque(maxlen=window_size)
            self._tares[nid] = 0.0
            self._last_seen[nid] = 0.0
            self._node_connected_state[nid] = False

    def procesar(self, raw_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Recibe lista de datos crudos, aplica filtros y mapea a nombres lógicos.
        Retorna un diccionario con el estado actual del sistema y logs.
        """
        resultado = {
            'sensores': {},
            'total': 0.0,
            'total_tare': 0.0,
            'logs': []
        }
        
        current_time = time.time()
        
        # Organizar datos por nodo para procesamiento rápido
        datos_por_nodo = {d['node_id']: d['value'] for d in raw_data}
        
        # Actualizar timestamps
        for d in raw_data:
            nid = d['node_id']
            self._last_seen[nid] = current_time
            if not self._node_connected_state.get(nid, False):
                self._node_connected_state[nid] = True
                resultado['logs'].append(f"Nodo {nid} reconectado/detectado.")
        
        total_peso = 0.0
        total_tare = 0.0
        
        for nombre_logico, cfg in self.nodos_config.items():
            node_id = cfg['id']
            
            # Verificar Timeout (ej. 3 segundos)
            is_connected = True
            if current_time - self._last_seen.get(node_id, 0) > 3.0:
                is_connected = False
                if self._node_connected_state.get(node_id, False):
                    self._node_connected_state[node_id] = False
                    resultado['logs'].append(f"ALERTA: Nodo {node_id} ({nombre_logico}) perdió conexión.")
            
            # Obtener valor crudo si llegó en este ciclo
            if node_id in datos_por_nodo:
                val_crudo = datos_por_nodo[node_id]
                self._buffers[node_id].append(val_crudo)
            
            # Calcular promedio móvil (si hay datos)
            if self._buffers[node_id]:
                promedio = sum(self._buffers[node_id]) / len(self._buffers[node_id])
            else:
                promedio = 0.0
                
            # Aplicar Tara
            tara_actual = self._tares.get(node_id, 0.0)
            valor_neto = promedio - tara_actual
            
            # Sumar al total (solo si está conectado para no sumar basura o ceros engañosos)
            if is_connected:
                total_peso += valor_neto
                total_tare += tara_actual
            
            resultado['sensores'][nombre_logico] = {
                'valor': valor_neto,
                'raw': promedio, # Promedio sin tara
                'id': node_id,
                'connected': is_connected
            }
            
        resultado['total'] = total_peso
        resultado['total_tare'] = total_tare
        return resultado

    def set_tara(self):
        """Establece la tara actual basada en el último promedio conocido."""
        for nid, buffer in self._buffers.items():
            if buffer:
                # La nueva tara es el promedio actual
                self._tares[nid] = sum(buffer) / len(buffer)
                
    def reset_tara(self):
        """Reinicia las taras a 0."""
        for nid in self._tares:
            self._tares[nid] = 0.0
