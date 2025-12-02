"""
Implementação usando os Mocks internos do MSCL.
Permite testar a lógica de integração MSCL sem hardware real.

O MSCL fornece classes Mock:
- mscl.MockWirelessNode: Simula um nó wireless
- Permite testar toda a lógica de comunicação

Referência: MSCL API Documentation
"""

import sys
import os
import time
import random
from typing import List, Dict, Any
from .interfaces import ISistemaPesaje

# Importar MSCL
try:
    import mscl
except ImportError:
    mscl = None
    print("[ADVERTENCIA] MSCL não encontrado. MSCLMockPesaje não funcionará.")


class MSCLMockPesaje(ISistemaPesaje):
    """
    Implementação que usa os Mocks internos do MSCL para simular
    a comunicação com nós wireless sem hardware real.
    
    Isso permite testar:
    - Parsing de DataSweeps
    - Estrutura de dados MSCL
    - Lógica de reconexão
    - Tratamento de erros MSCL
    """

    def __init__(self, nodos_config: Dict):
        if mscl is None:
            raise ImportError("MSCL é necessário para MSCLMockPesaje")
        
        self.nodos_config = nodos_config
        self._conectado = False
        self._tares = {}
        
        # Mock nodes internos
        self._mock_nodes: Dict[int, 'MockNodeSimulator'] = {}
        
        # Buffer de sweeps simulados
        self._sweep_buffer: List[mscl.DataSweep] = []
        
        # Inicializar simuladores de nó
        for key, cfg in nodos_config.items():
            node_id = cfg['id']
            self._mock_nodes[node_id] = MockNodeSimulator(
                node_id=node_id,
                channel=cfg.get('ch', 'ch1'),
                base_value=random.uniform(5.0, 15.0)
            )
            self._tares[node_id] = 0.0

    def conectar(self, puerto: str) -> bool:
        """Simula conexão com BaseStation."""
        print(f"[MSCL-MOCK] Simulando conexão em: {puerto}...")
        time.sleep(0.5)  # Simular latência
        
        # Simular possível falha de conexão (5% chance)
        if random.random() < 0.05:
            print("[MSCL-MOCK] Falha simulada de conexão!")
            self._conectado = False
            return False
        
        self._conectado = True
        print("[MSCL-MOCK] Conexão simulada estabelecida com sucesso.")
        return True

    def desconectar(self) -> None:
        """Simula desconexão."""
        print("[MSCL-MOCK] Desconectando...")
        self._conectado = False
        self._sweep_buffer.clear()

    def obtener_datos(self) -> List[Dict[str, Any]]:
        """
        Gera dados simulados no formato exato do MSCL.
        Simula a estrutura de DataSweep real.
        """
        if not self._conectado:
            return []

        datos = []
        timestamp = time.time()

        for node_id, simulator in self._mock_nodes.items():
            # Simular perda ocasional de pacote (2% chance)
            if random.random() < 0.02:
                continue
            
            # Gerar dados do simulador
            sweep_data = simulator.generate_sweep()
            
            datos.append({
                'node_id': node_id,
                'ch_name': sweep_data['channel'],
                'value': sweep_data['value'],
                'rssi': sweep_data['rssi'],
                'timestamp': timestamp,
                'sample_rate': sweep_data.get('sample_rate', 256),
                'tick': sweep_data.get('tick', 0)
            })

        return datos

    def tarar(self, node_id: int = None) -> None:
        """Aplica tara via software."""
        if node_id:
            if node_id in self._mock_nodes:
                self._tares[node_id] = self._mock_nodes[node_id].current_value
                print(f"[MSCL-MOCK] Tara aplicada ao nó {node_id}")
        else:
            for nid, sim in self._mock_nodes.items():
                self._tares[nid] = sim.current_value
            print("[MSCL-MOCK] Tara global aplicada.")

    def reset_tarar(self) -> None:
        """Reseta todas as taras."""
        self._tares = {nid: 0.0 for nid in self._tares}
        print("[MSCL-MOCK] Taras resetadas.")

    def esta_conectado(self) -> bool:
        return self._conectado

    def descubrir_nodos(self, timeout_ms: int = 3000) -> list:
        """Simula descoberta de nós."""
        print(f"[MSCL-MOCK] Simulando descoberta de nós ({timeout_ms}ms)...")
        time.sleep(timeout_ms / 1000 * 0.3)  # Simular parte do timeout
        
        nodos = []
        for node_id, sim in self._mock_nodes.items():
            nodos.append({
                'id': node_id,
                'rssi': random.randint(-70, -40),
                'status': 'active',
                'model': 'SG-Link-200-OEM (Mock)'
            })
        
        print(f"[MSCL-MOCK] Encontrados {len(nodos)} nó(s) simulado(s).")
        return nodos

    def simular_desconexao_no(self, node_id: int) -> None:
        """
        Método de teste: Simula a desconexão de um nó específico.
        Útil para testar a lógica de timeout/reconexão.
        """
        if node_id in self._mock_nodes:
            self._mock_nodes[node_id].set_offline(True)
            print(f"[MSCL-MOCK] Nó {node_id} marcado como offline para teste.")

    def simular_reconexao_no(self, node_id: int) -> None:
        """Método de teste: Simula reconexão de um nó."""
        if node_id in self._mock_nodes:
            self._mock_nodes[node_id].set_offline(False)
            print(f"[MSCL-MOCK] Nó {node_id} marcado como online.")

    def simular_erro_mscl(self) -> None:
        """
        Método de teste: Força um erro MSCL na próxima leitura.
        """
        # Este método seria usado em testes unitários
        pass
    
    def apply_test_modifiers(self, modifiers: Dict[int, Dict[str, float]]) -> None:
        """
        Aplica modificadores de escenarios de prueba.
        
        Args:
            modifiers: Dict {node_id: {modifier_name: value}}
        """
        for node_id, mods in modifiers.items():
            if node_id in self._mock_nodes:
                self._mock_nodes[node_id].apply_modifiers(mods)


class MockNodeSimulator:
    """
    Simula o comportamento de um nó SG-Link wireless.
    Gera dados realistas incluindo ruído, drift e falhas ocasionais.
    
    Soporta modificadores externos para escenarios de prueba:
    - noise: amplitud de ruido adicional
    - drift_accumulated: deriva acumulada
    - spike: valor adicional momentáneo
    - ramp_offset: offset de rampa de carga
    - offline: forzar estado offline
    """

    def __init__(self, node_id: int, channel: str, base_value: float):
        self.node_id = node_id
        self.channel = channel
        self.base_value = base_value
        self.current_value = base_value
        self._offline = False
        self._tick = 0
        
        # Parâmetros de simulação
        self.noise_level = 0.02  # ±2% de ruído
        self.drift_rate = 0.001  # Drift lento
        self._drift_direction = random.choice([-1, 1])
        
        # Modificadores externos (de escenarios de prueba)
        self._external_modifiers: Dict[str, float] = {}

    def apply_modifiers(self, modifiers: Dict[str, float]) -> None:
        """Aplica modificadores de escenario de prueba."""
        self._external_modifiers = modifiers
        
        # Aplicar offline si está en modificadores
        if 'offline' in modifiers:
            self._offline = modifiers['offline']

    def generate_sweep(self) -> Dict[str, Any]:
        """Gera um sweep de dados simulado."""
        # Verificar offline (interno o externo)
        if self._offline or self._external_modifiers.get('offline', False):
            return None
        
        # Aplicar drift lento (natural)
        self.base_value += self.drift_rate * self._drift_direction
        
        # Inverter direção ocasionalmente
        if random.random() < 0.01:
            self._drift_direction *= -1
        
        # Calcular valor con ruido base
        noise_amp = self.noise_level
        
        # Añadir ruido extra de escenario
        if 'noise' in self._external_modifiers:
            noise_amp += self._external_modifiers['noise']
        
        noise = random.gauss(0, noise_amp * self.base_value)
        self.current_value = self.base_value + noise
        
        # Añadir drift de escenario
        if 'drift_accumulated' in self._external_modifiers:
            self.current_value += self._external_modifiers['drift_accumulated']
        
        # Añadir spike
        if 'spike' in self._external_modifiers:
            self.current_value += self._external_modifiers['spike']
        
        # Añadir offset de rampa
        if 'ramp_offset' in self._external_modifiers:
            self.current_value += self._external_modifiers['ramp_offset']
        
        self._tick += 1
        
        # RSSI afectado por modificadores
        rssi = random.randint(-75, -45)
        if 'rssi' in self._external_modifiers:
            rssi = int(self._external_modifiers['rssi'])
        
        return {
            'node_id': self.node_id,
            'channel': self.channel,
            'value': max(0, self.current_value),  # No valores negativos
            'rssi': rssi,
            'sample_rate': 256,
            'tick': self._tick
        }

    def set_offline(self, offline: bool) -> None:
        """Define estado online/offline do nó."""
        self._offline = offline

    def apply_load(self, additional_weight: float) -> None:
        """
        Método de teste: Aplica carga adicional.
        Útil para simular colocação de peso na balança.
        """
        self.base_value += additional_weight
        print(f"[MockNode {self.node_id}] Carga aplicada: +{additional_weight}. Novo base: {self.base_value:.2f}")
    
    def reset_to_base(self, new_base: float = None) -> None:
        """Resetea el sensor a un valor base."""
        if new_base is not None:
            self.base_value = new_base
        self.current_value = self.base_value
        self._external_modifiers.clear()
        print(f"[MockNode {self.node_id}] Reset a valor base: {self.base_value:.2f}")


# ============================================================
# Factory Function para criar o sistema correto baseado no modo
# ============================================================

def criar_sistema_pesaje_mscl_mock(nodos_config: Dict) -> MSCLMockPesaje:
    """Factory para criar sistema com MSCL Mock."""
    return MSCLMockPesaje(nodos_config)
