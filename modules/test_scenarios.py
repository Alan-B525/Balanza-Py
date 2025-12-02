"""
Sistema de Escenarios de Prueba para Balanza-Py

Este módulo proporciona escenarios de simulación configurables para:
- Probar fallos de sensores
- Simular condiciones adversas (ruido, pérdida de señal)
- Validar lógica de recuperación
- Generar datos de carga específicos (rampa, pulso, etc.)

Uso:
    from modules.test_scenarios import TestScenarioManager
    
    # Crear gestor con el sistema de pesaje mock
    manager = TestScenarioManager(sistema_pesaje)
    
    # Activar escenario
    manager.activate_scenario("sensor_failure", node_id=12345)
"""

import time
import random
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any, Optional
from enum import Enum


class ScenarioType(Enum):
    """Tipos de escenarios de prueba disponibles."""
    NORMAL = "normal"
    SENSOR_FAILURE = "sensor_failure"
    SIGNAL_LOSS = "signal_loss"
    HIGH_NOISE = "high_noise"
    DRIFT = "drift"
    SPIKE = "spike"
    RAMP_UP = "ramp_up"
    RAMP_DOWN = "ramp_down"
    INTERMITTENT = "intermittent"
    OVERLOAD = "overload"
    CALIBRATION_ERROR = "calibration_error"


@dataclass
class TestScenario:
    """Definición de un escenario de prueba."""
    name: str
    scenario_type: ScenarioType
    description: str
    duration_seconds: float = 0  # 0 = indefinido
    parameters: Dict[str, Any] = field(default_factory=dict)
    affected_nodes: List[int] = field(default_factory=list)  # vacío = todos
    

class ScenarioPresets:
    """Escenarios predefinidos comunes."""
    
    @staticmethod
    def sensor_offline(node_id: int, duration: float = 10.0) -> TestScenario:
        """Simula un sensor que deja de responder."""
        return TestScenario(
            name=f"Sensor {node_id} Offline",
            scenario_type=ScenarioType.SENSOR_FAILURE,
            description=f"Simula fallo completo del sensor {node_id}",
            duration_seconds=duration,
            parameters={"failure_type": "offline", "rssi": -100},
            affected_nodes=[node_id]
        )
    
    @staticmethod
    def signal_degradation(node_id: int, rssi_target: int = -85) -> TestScenario:
        """Simula degradación gradual de señal."""
        return TestScenario(
            name=f"Señal Degradada {node_id}",
            scenario_type=ScenarioType.SIGNAL_LOSS,
            description=f"Simula pérdida gradual de señal en sensor {node_id}",
            duration_seconds=30.0,
            parameters={"rssi_start": -50, "rssi_end": rssi_target, "packet_loss": 0.3},
            affected_nodes=[node_id]
        )
    
    @staticmethod
    def high_noise(noise_amplitude: float = 0.5) -> TestScenario:
        """Simula ambiente con mucho ruido eléctrico."""
        return TestScenario(
            name="Alto Ruido",
            scenario_type=ScenarioType.HIGH_NOISE,
            description="Simula interferencia electromagnética alta",
            parameters={"noise_amplitude": noise_amplitude, "noise_frequency": 10},
            affected_nodes=[]  # Todos los nodos
        )
    
    @staticmethod
    def sensor_drift(node_id: int, drift_rate: float = 0.01) -> TestScenario:
        """Simula deriva del sensor (descalibración gradual)."""
        return TestScenario(
            name=f"Deriva Sensor {node_id}",
            scenario_type=ScenarioType.DRIFT,
            description=f"Simula descalibración gradual del sensor {node_id}",
            duration_seconds=120.0,
            parameters={"drift_rate": drift_rate, "direction": "positive"},
            affected_nodes=[node_id]
        )
    
    @staticmethod
    def load_ramp(target_weight: float = 50.0, duration: float = 30.0) -> TestScenario:
        """Simula carga gradual (camión entrando)."""
        return TestScenario(
            name="Rampa de Carga",
            scenario_type=ScenarioType.RAMP_UP,
            description=f"Simula carga gradual hasta {target_weight}t en {duration}s",
            duration_seconds=duration,
            parameters={"target_weight": target_weight, "distribution": "linear"},
            affected_nodes=[]
        )
    
    @staticmethod
    def unload_ramp(duration: float = 20.0) -> TestScenario:
        """Simula descarga gradual (camión saliendo)."""
        return TestScenario(
            name="Rampa de Descarga",
            scenario_type=ScenarioType.RAMP_DOWN,
            description=f"Simula descarga gradual en {duration}s",
            duration_seconds=duration,
            parameters={"target_weight": 0.0, "distribution": "linear"},
            affected_nodes=[]
        )
    
    @staticmethod
    def spike_load(magnitude: float = 10.0, duration: float = 0.5) -> TestScenario:
        """Simula impacto súbito (objeto cayendo)."""
        return TestScenario(
            name="Impacto Súbito",
            scenario_type=ScenarioType.SPIKE,
            description=f"Simula impacto de {magnitude}t por {duration}s",
            duration_seconds=duration,
            parameters={"magnitude": magnitude, "decay_time": 2.0},
            affected_nodes=[]
        )
    
    @staticmethod
    def intermittent_connection(node_id: int, interval: float = 5.0) -> TestScenario:
        """Simula conexión intermitente (sensor con problemas)."""
        return TestScenario(
            name=f"Conexión Intermitente {node_id}",
            scenario_type=ScenarioType.INTERMITTENT,
            description=f"Sensor {node_id} conecta/desconecta cada {interval}s",
            duration_seconds=60.0,
            parameters={"interval": interval, "online_probability": 0.7},
            affected_nodes=[node_id]
        )
    
    @staticmethod
    def overload_warning(threshold_percent: float = 95.0) -> TestScenario:
        """Simula peso cercano al límite de capacidad."""
        return TestScenario(
            name="Sobrecarga",
            scenario_type=ScenarioType.OVERLOAD,
            description=f"Simula carga al {threshold_percent}% de capacidad",
            parameters={"threshold_percent": threshold_percent, "max_capacity": 100.0},
            affected_nodes=[]
        )


class TestScenarioManager:
    """
    Gestor de escenarios de prueba.
    
    Se integra con el sistema de pesaje Mock para modificar
    el comportamiento de los sensores simulados.
    """
    
    def __init__(self, sistema_pesaje):
        """
        Args:
            sistema_pesaje: Instancia de ISistemaPesaje (preferiblemente Mock)
        """
        self.sistema = sistema_pesaje
        self.active_scenarios: Dict[str, TestScenario] = {}
        self._scenario_threads: Dict[str, threading.Thread] = {}
        self._stop_flags: Dict[str, threading.Event] = {}
        self._modifiers: Dict[int, Dict[str, float]] = {}  # node_id -> modificadores
        
    def activate_scenario(self, scenario: TestScenario) -> bool:
        """
        Activa un escenario de prueba.
        
        Returns:
            True si se activó correctamente
        """
        scenario_id = f"{scenario.scenario_type.value}_{id(scenario)}"
        
        if scenario_id in self.active_scenarios:
            print(f"[TEST] Escenario ya activo: {scenario.name}")
            return False
        
        self.active_scenarios[scenario_id] = scenario
        self._stop_flags[scenario_id] = threading.Event()
        
        # Aplicar modificadores iniciales
        self._apply_scenario(scenario, scenario_id)
        
        print(f"[TEST] ✓ Escenario activado: {scenario.name}")
        print(f"       Descripción: {scenario.description}")
        if scenario.duration_seconds > 0:
            print(f"       Duración: {scenario.duration_seconds}s")
        
        return True
    
    def deactivate_scenario(self, scenario_id: str) -> bool:
        """Desactiva un escenario específico."""
        if scenario_id not in self.active_scenarios:
            return False
        
        # Señalar stop al thread
        if scenario_id in self._stop_flags:
            self._stop_flags[scenario_id].set()
        
        # Esperar thread
        if scenario_id in self._scenario_threads:
            self._scenario_threads[scenario_id].join(timeout=2.0)
            del self._scenario_threads[scenario_id]
        
        scenario = self.active_scenarios.pop(scenario_id)
        self._cleanup_scenario(scenario)
        
        print(f"[TEST] ✗ Escenario desactivado: {scenario.name}")
        return True
    
    def deactivate_all(self):
        """Desactiva todos los escenarios y restaura estado normal."""
        for scenario_id in list(self.active_scenarios.keys()):
            self.deactivate_scenario(scenario_id)
        
        self._modifiers.clear()
        print("[TEST] Todos los escenarios desactivados. Sistema en modo normal.")
    
    def get_active_scenarios(self) -> List[str]:
        """Retorna lista de escenarios activos."""
        return [s.name for s in self.active_scenarios.values()]
    
    def get_node_modifier(self, node_id: int) -> Dict[str, float]:
        """
        Obtiene los modificadores actuales para un nodo.
        Usado por el Mock para ajustar valores.
        """
        return self._modifiers.get(node_id, {})
    
    def _apply_scenario(self, scenario: TestScenario, scenario_id: str):
        """Aplica los efectos de un escenario."""
        
        nodes = scenario.affected_nodes or self._get_all_nodes()
        
        if scenario.scenario_type == ScenarioType.SENSOR_FAILURE:
            for node_id in nodes:
                self._modifiers.setdefault(node_id, {})['offline'] = True
                self._modifiers[node_id]['rssi'] = scenario.parameters.get('rssi', -100)
                
                # Intentar usar método del mock si existe
                if hasattr(self.sistema, 'simular_desconexao_no'):
                    self.sistema.simular_desconexao_no(node_id)
        
        elif scenario.scenario_type == ScenarioType.HIGH_NOISE:
            noise = scenario.parameters.get('noise_amplitude', 0.5)
            for node_id in nodes:
                self._modifiers.setdefault(node_id, {})['noise'] = noise
        
        elif scenario.scenario_type == ScenarioType.DRIFT:
            drift_rate = scenario.parameters.get('drift_rate', 0.01)
            for node_id in nodes:
                self._modifiers.setdefault(node_id, {})['drift_rate'] = drift_rate
                self._modifiers[node_id]['drift_accumulated'] = 0.0
            
            # Iniciar thread de drift
            self._start_drift_thread(scenario, scenario_id, nodes)
        
        elif scenario.scenario_type == ScenarioType.RAMP_UP:
            target = scenario.parameters.get('target_weight', 50.0)
            duration = scenario.duration_seconds
            self._start_ramp_thread(scenario, scenario_id, nodes, target, duration, "up")
        
        elif scenario.scenario_type == ScenarioType.RAMP_DOWN:
            duration = scenario.duration_seconds
            self._start_ramp_thread(scenario, scenario_id, nodes, 0.0, duration, "down")
        
        elif scenario.scenario_type == ScenarioType.INTERMITTENT:
            self._start_intermittent_thread(scenario, scenario_id, nodes)
        
        elif scenario.scenario_type == ScenarioType.SPIKE:
            magnitude = scenario.parameters.get('magnitude', 10.0)
            for node_id in nodes:
                self._modifiers.setdefault(node_id, {})['spike'] = magnitude / len(nodes)
            
            # Thread para decay del spike
            self._start_spike_thread(scenario, scenario_id, nodes)
    
    def _cleanup_scenario(self, scenario: TestScenario):
        """Limpia los efectos de un escenario al desactivarlo."""
        nodes = scenario.affected_nodes or self._get_all_nodes()
        
        if scenario.scenario_type == ScenarioType.SENSOR_FAILURE:
            for node_id in nodes:
                if node_id in self._modifiers:
                    self._modifiers[node_id].pop('offline', None)
                if hasattr(self.sistema, 'simular_reconexao_no'):
                    self.sistema.simular_reconexao_no(node_id)
        
        # Limpiar otros modificadores
        for node_id in nodes:
            if node_id in self._modifiers:
                for key in ['noise', 'drift_rate', 'drift_accumulated', 'spike', 'ramp_offset']:
                    self._modifiers[node_id].pop(key, None)
    
    def _get_all_nodes(self) -> List[int]:
        """Obtiene todos los IDs de nodo del sistema."""
        if hasattr(self.sistema, 'nodos_config'):
            return [cfg['id'] for cfg in self.sistema.nodos_config.values()]
        if hasattr(self.sistema, '_mock_nodes'):
            return list(self.sistema._mock_nodes.keys())
        return []
    
    def _start_drift_thread(self, scenario: TestScenario, scenario_id: str, nodes: List[int]):
        """Inicia thread para simular drift gradual."""
        def drift_loop():
            drift_rate = scenario.parameters.get('drift_rate', 0.01)
            while not self._stop_flags[scenario_id].is_set():
                for node_id in nodes:
                    if node_id in self._modifiers:
                        current = self._modifiers[node_id].get('drift_accumulated', 0.0)
                        self._modifiers[node_id]['drift_accumulated'] = current + drift_rate
                time.sleep(1.0)
        
        thread = threading.Thread(target=drift_loop, daemon=True)
        self._scenario_threads[scenario_id] = thread
        thread.start()
    
    def _start_ramp_thread(self, scenario: TestScenario, scenario_id: str, 
                           nodes: List[int], target: float, duration: float, direction: str):
        """Inicia thread para rampa de carga/descarga."""
        def ramp_loop():
            start_time = time.time()
            initial_values = {n: self._modifiers.get(n, {}).get('ramp_offset', 0) for n in nodes}
            
            while not self._stop_flags[scenario_id].is_set():
                elapsed = time.time() - start_time
                if elapsed >= duration:
                    break
                
                progress = elapsed / duration
                per_node_target = target / max(len(nodes), 1)
                
                for node_id in nodes:
                    if direction == "up":
                        offset = per_node_target * progress
                    else:
                        offset = initial_values[node_id] * (1 - progress)
                    
                    self._modifiers.setdefault(node_id, {})['ramp_offset'] = offset
                
                time.sleep(0.1)
            
            # Aplicar valor final
            for node_id in nodes:
                if direction == "up":
                    self._modifiers.setdefault(node_id, {})['ramp_offset'] = target / len(nodes)
                else:
                    self._modifiers[node_id]['ramp_offset'] = 0
        
        thread = threading.Thread(target=ramp_loop, daemon=True)
        self._scenario_threads[scenario_id] = thread
        thread.start()
    
    def _start_intermittent_thread(self, scenario: TestScenario, scenario_id: str, nodes: List[int]):
        """Inicia thread para conexión intermitente."""
        def intermittent_loop():
            interval = scenario.parameters.get('interval', 5.0)
            online_prob = scenario.parameters.get('online_probability', 0.7)
            
            while not self._stop_flags[scenario_id].is_set():
                for node_id in nodes:
                    is_online = random.random() < online_prob
                    self._modifiers.setdefault(node_id, {})['offline'] = not is_online
                    
                    if hasattr(self.sistema, 'simular_desconexao_no') and not is_online:
                        self.sistema.simular_desconexao_no(node_id)
                    elif hasattr(self.sistema, 'simular_reconexao_no') and is_online:
                        self.sistema.simular_reconexao_no(node_id)
                
                time.sleep(interval)
        
        thread = threading.Thread(target=intermittent_loop, daemon=True)
        self._scenario_threads[scenario_id] = thread
        thread.start()
    
    def _start_spike_thread(self, scenario: TestScenario, scenario_id: str, nodes: List[int]):
        """Inicia thread para decay del spike."""
        def spike_loop():
            decay_time = scenario.parameters.get('decay_time', 2.0)
            start_time = time.time()
            initial_spike = scenario.parameters.get('magnitude', 10.0) / len(nodes)
            
            while not self._stop_flags[scenario_id].is_set():
                elapsed = time.time() - start_time
                if elapsed >= decay_time:
                    break
                
                # Decay exponencial
                remaining = initial_spike * (1 - elapsed / decay_time) ** 2
                
                for node_id in nodes:
                    self._modifiers.setdefault(node_id, {})['spike'] = remaining
                
                time.sleep(0.05)
            
            # Limpiar spike
            for node_id in nodes:
                if node_id in self._modifiers:
                    self._modifiers[node_id]['spike'] = 0
        
        thread = threading.Thread(target=spike_loop, daemon=True)
        self._scenario_threads[scenario_id] = thread
        thread.start()


# ============== Interfaz de línea de comandos para testing ==============

def run_interactive_test():
    """
    Ejecuta una sesión interactiva de pruebas.
    Útil para testing manual sin GUI.
    """
    print("=" * 60)
    print("  BALANZA-PY - Consola de Pruebas Interactiva")
    print("=" * 60)
    print()
    print("Comandos disponibles:")
    print("  1. offline <node_id>     - Simular sensor offline")
    print("  2. noise                 - Activar alto ruido")
    print("  3. ramp <peso>           - Simular rampa de carga")
    print("  4. spike <magnitud>      - Simular impacto")
    print("  5. drift <node_id>       - Simular deriva de sensor")
    print("  6. intermittent <node_id>- Conexión intermitente")
    print("  7. list                  - Listar escenarios activos")
    print("  8. reset                 - Desactivar todos")
    print("  9. quit                  - Salir")
    print()
    
    # Esta función sería integrada con el sistema real
    print("[INFO] Esta es una demostración. Integrar con main.py para uso real.")


if __name__ == "__main__":
    run_interactive_test()
