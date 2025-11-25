import time
import random
import threading
from typing import List, Dict, Any
from .interfaces import ISistemaPesaje

class MockPesaje(ISistemaPesaje):
    """
    Simulación del sistema de pesaje para desarrollo sin hardware.
    Genera datos con ruido y simula latencia de red.
    """
    
    def __init__(self, nodos_config: Dict):
        self.nodos_config = nodos_config
        self._conectado = False
        self._tares = {} # Almacena el valor de tara para cada nodo/canal
        self._base_values = {} # Valores base simulados para cada nodo
        
        # Inicializar valores base aleatorios para simular carga inicial
        for key, cfg in self.nodos_config.items():
            node_id = cfg['id']
            self._base_values[node_id] = random.uniform(5.0, 15.0) # Carga inicial simulada
            self._tares[node_id] = 0.0

    def conectar(self, puerto: str) -> bool:
        print(f"[MOCK] Intentando conectar en {puerto}...")
        time.sleep(1.5) # Simular latencia de conexión
        self._conectado = True
        print("[MOCK] Conexión exitosa.")
        return True

    def desconectar(self) -> None:
        print("[MOCK] Desconectando...")
        time.sleep(0.5)
        self._conectado = False

    def obtener_datos(self) -> List[Dict[str, Any]]:
        if not self._conectado:
            return []

        datos = []
        # Simular latencia de lectura de hardware
        time.sleep(0.05) 

        timestamp = time.time()

        for key, cfg in self.nodos_config.items():
            node_id = cfg['id']
            ch_name = cfg['ch']
            
            # Generar valor: Base + Ruido - Tara
            ruido = random.uniform(-0.05, 0.05)
            valor_bruto = self._base_values[node_id] + ruido
            valor_neto = valor_bruto - self._tares.get(node_id, 0.0)

            datos.append({
                'node_id': node_id,
                'ch_name': ch_name,
                'value': valor_neto,
                'rssi': random.randint(-80, -40), # Simular señal fuerte
                'timestamp': timestamp
            })
            
        return datos

    def tarar(self, node_id: int = None) -> None:
        """
        En el Mock, 'tarar' significa guardar el valor base actual como offset.
        """
        if node_id:
            # Tarar un nodo específico (simplificado: usa el valor base actual)
            self._tares[node_id] = self._base_values[node_id]
            print(f"[MOCK] Tara aplicada a nodo {node_id}")
        else:
            # Tarar todos
            for nid in self._base_values:
                self._tares[nid] = self._base_values[nid]
            print("[MOCK] Tara global aplicada.")

    def reset_tarar(self) -> None:
        self._tares = {nid: 0.0 for nid in self._tares}
        print("[MOCK] Tara reseteada.")

    def esta_conectado(self) -> bool:
        return self._conectado
