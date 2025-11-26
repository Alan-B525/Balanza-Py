import time
import random
import threading
from typing import List, Dict, Any
from .interfaces import ISistemaPesaje

class MockPesaje(ISistemaPesaje):
    """
    Simulação do sistema de pesagem para desenvolvimento sem hardware.
    Gera dados com ruído e simula latência de rede.
    """
    
    def __init__(self, nodos_config: Dict):
        self.nodos_config = nodos_config
        self._conectado = False
        self._tares = {} # Armazena o valor de tara para cada nó/canal
        self._base_values = {} # Valores base simulados para cada nó
        
        # Inicializar valores base aleatórios para simular carga inicial
        for key, cfg in self.nodos_config.items():
            node_id = cfg['id']
            self._base_values[node_id] = random.uniform(5.0, 15.0) # Carga inicial simulada
            self._tares[node_id] = 0.0

    def conectar(self, puerto: str) -> bool:
        print(f"[MOCK] Tentando conectar em {puerto}...")
        time.sleep(1.5) # Simular latência de conexão
        self._conectado = True
        print("[MOCK] Conexão bem-sucedida.")
        return True

    def desconectar(self) -> None:
        print("[MOCK] Desconectando...")
        time.sleep(0.5)
        self._conectado = False

    def obtener_datos(self) -> List[Dict[str, Any]]:
        if not self._conectado:
            return []

        datos = []
        # Simular latência de leitura do hardware
        time.sleep(0.05) 

        timestamp = time.time()

        for key, cfg in self.nodos_config.items():
            node_id = cfg['id']
            ch_name = cfg['ch']
            
            # Gerar valor: Base + Ruído - Tara
            ruido = random.uniform(-0.05, 0.05)
            valor_bruto = self._base_values[node_id] + ruido
            valor_neto = valor_bruto - self._tares.get(node_id, 0.0)

            datos.append({
                'node_id': node_id,
                'ch_name': ch_name,
                'value': valor_neto,
                'rssi': random.randint(-80, -40), # Simular sinal forte
                'timestamp': timestamp
            })
            
        return datos

    def tarar(self, node_id: int = None) -> None:
        """
        No Mock, 'tarar' significa salvar o valor base atual como offset.
        """
        if node_id:
            # Tarar um nó específico (simplificado: usa o valor base atual)
            self._tares[node_id] = self._base_values[node_id]
            print(f"[MOCK] Tara aplicada ao nó {node_id}")
        else:
            # Tarar todos
            for nid in self._base_values:
                self._tares[nid] = self._base_values[nid]
            print("[MOCK] Tara global aplicada.")

    def reset_tarar(self) -> None:
        self._tares = {nid: 0.0 for nid in self._tares}
        print("[MOCK] Tara reiniciada.")

    def esta_conectado(self) -> bool:
        return self._conectado
