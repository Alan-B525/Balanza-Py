"""
Script de Pruebas Interactivas para Balanza-Py

Ejecutar: python run_tests.py

Este script permite probar diferentes escenarios de fallo y comportamiento
de los sensores sin necesidad de hardware real.
"""

import sys
import os
import time
import threading

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import NODOS_CONFIG
from modules.factory import criar_sistema_pesaje
from modules.test_scenarios import (
    TestScenarioManager, 
    ScenarioPresets,
    ScenarioType
)


class TestConsole:
    """Consola interactiva para pruebas de sensores."""
    
    def __init__(self):
        self.sistema = None
        self.scenario_manager = None
        self.running = False
        self.data_thread = None
        
    def setup(self):
        """Inicializa el sistema en modo mock."""
        print("\n" + "="*60)
        print("  BALANZA-PY - Consola de Pruebas")
        print("="*60)
        
        # Crear sistema mock
        print("\n[INIT] Creando sistema de pesaje simulado...")
        self.sistema = criar_sistema_pesaje("MSCL_MOCK", NODOS_CONFIG)
        
        # Conectar
        self.sistema.conectar("COM_TEST")
        
        # Crear gestor de escenarios
        self.scenario_manager = TestScenarioManager(self.sistema)
        
        print("[INIT] Sistema listo.\n")
        
    def start_data_display(self):
        """Inicia thread que muestra datos en tiempo real."""
        self.running = True
        
        def display_loop():
            while self.running:
                datos = self.sistema.obtener_datos()
                if datos:
                    # Aplicar modificadores de escenarios
                    for node_id in [cfg['id'] for cfg in NODOS_CONFIG.values()]:
                        mods = self.scenario_manager.get_node_modifier(node_id)
                        if mods:
                            self.sistema.apply_test_modifiers({node_id: mods})
                    
                    # Mostrar datos
                    total = sum(d['value'] for d in datos)
                    os.system('cls' if os.name == 'nt' else 'clear')
                    
                    print("="*60)
                    print("  DATOS EN TIEMPO REAL")
                    print("="*60)
                    
                    for d in datos:
                        status = "🟢" if d['rssi'] > -80 else "🟡" if d['rssi'] > -90 else "🔴"
                        print(f"  Sensor {d['node_id']}: {d['value']:>8.2f} t  RSSI: {d['rssi']} dBm {status}")
                    
                    print("-"*60)
                    print(f"  TOTAL: {total:>10.2f} t")
                    print("-"*60)
                    
                    # Mostrar escenarios activos
                    active = self.scenario_manager.get_active_scenarios()
                    if active:
                        print(f"\n  📋 Escenarios activos: {', '.join(active)}")
                    
                    print("\n  [Presiona Enter para menú de comandos]")
                
                time.sleep(0.5)
        
        self.data_thread = threading.Thread(target=display_loop, daemon=True)
        self.data_thread.start()
    
    def stop_data_display(self):
        """Detiene el thread de datos."""
        self.running = False
        if self.data_thread:
            self.data_thread.join(timeout=1.0)
    
    def show_menu(self):
        """Muestra menú de comandos."""
        print("\n" + "="*60)
        print("  COMANDOS DISPONIBLES")
        print("="*60)
        print("""
  ESCENARIOS DE FALLO:
    1. offline <sensor>     - Desconectar sensor (1-4)
    2. reconnect <sensor>   - Reconectar sensor
    3. noise                - Activar ruido alto
    4. drift <sensor>       - Activar deriva en sensor
    5. intermittent <sensor>- Conexión intermitente
    
  ESCENARIOS DE CARGA:
    6. ramp <peso>          - Rampa de carga (ej: ramp 50)
    7. unload               - Descarga gradual
    8. spike <magnitud>     - Impacto súbito (ej: spike 10)
    9. overload             - Simular sobrecarga
    
  CONTROL:
    10. list                - Listar escenarios activos
    11. reset               - Desactivar todos los escenarios
    12. tare                - Aplicar tara
    13. status              - Ver estado de sensores
    
    q. Salir
""")
    
    def get_node_id(self, sensor_num: int) -> int:
        """Convierte número de sensor (1-4) a node_id."""
        keys = list(NODOS_CONFIG.keys())
        if 1 <= sensor_num <= len(keys):
            return NODOS_CONFIG[keys[sensor_num - 1]]['id']
        return None
    
    def process_command(self, cmd: str) -> bool:
        """Procesa un comando. Retorna False para salir."""
        parts = cmd.strip().lower().split()
        if not parts:
            return True
        
        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []
        
        try:
            if command == 'q' or command == 'quit':
                return False
            
            elif command == '1' or command == 'offline':
                sensor = int(args[0]) if args else 1
                node_id = self.get_node_id(sensor)
                if node_id:
                    scenario = ScenarioPresets.sensor_offline(node_id, duration=0)
                    self.scenario_manager.activate_scenario(scenario)
                    print(f"✓ Sensor {sensor} (ID: {node_id}) marcado como offline")
            
            elif command == '2' or command == 'reconnect':
                sensor = int(args[0]) if args else 1
                node_id = self.get_node_id(sensor)
                if node_id:
                    self.sistema.simular_reconexao_no(node_id)
                    print(f"✓ Sensor {sensor} reconectado")
            
            elif command == '3' or command == 'noise':
                scenario = ScenarioPresets.high_noise(noise_amplitude=0.5)
                self.scenario_manager.activate_scenario(scenario)
                print("✓ Ruido alto activado en todos los sensores")
            
            elif command == '4' or command == 'drift':
                sensor = int(args[0]) if args else 1
                node_id = self.get_node_id(sensor)
                if node_id:
                    scenario = ScenarioPresets.sensor_drift(node_id, drift_rate=0.05)
                    self.scenario_manager.activate_scenario(scenario)
                    print(f"✓ Deriva activada en sensor {sensor}")
            
            elif command == '5' or command == 'intermittent':
                sensor = int(args[0]) if args else 1
                node_id = self.get_node_id(sensor)
                if node_id:
                    scenario = ScenarioPresets.intermittent_connection(node_id, interval=3.0)
                    self.scenario_manager.activate_scenario(scenario)
                    print(f"✓ Conexión intermitente activada en sensor {sensor}")
            
            elif command == '6' or command == 'ramp':
                weight = float(args[0]) if args else 50.0
                scenario = ScenarioPresets.load_ramp(target_weight=weight, duration=10.0)
                self.scenario_manager.activate_scenario(scenario)
                print(f"✓ Rampa de carga iniciada: 0 → {weight}t en 10s")
            
            elif command == '7' or command == 'unload':
                scenario = ScenarioPresets.unload_ramp(duration=8.0)
                self.scenario_manager.activate_scenario(scenario)
                print("✓ Descarga gradual iniciada")
            
            elif command == '8' or command == 'spike':
                magnitude = float(args[0]) if args else 10.0
                scenario = ScenarioPresets.spike_load(magnitude=magnitude)
                self.scenario_manager.activate_scenario(scenario)
                print(f"✓ Impacto de {magnitude}t aplicado")
            
            elif command == '9' or command == 'overload':
                scenario = ScenarioPresets.overload_warning(threshold_percent=95)
                self.scenario_manager.activate_scenario(scenario)
                print("✓ Escenario de sobrecarga activado")
            
            elif command == '10' or command == 'list':
                active = self.scenario_manager.get_active_scenarios()
                if active:
                    print("Escenarios activos:")
                    for name in active:
                        print(f"  • {name}")
                else:
                    print("No hay escenarios activos")
            
            elif command == '11' or command == 'reset':
                self.scenario_manager.deactivate_all()
                print("✓ Todos los escenarios desactivados")
            
            elif command == '12' or command == 'tare':
                self.sistema.tarar()
                print("✓ Tara aplicada")
            
            elif command == '13' or command == 'status':
                datos = self.sistema.obtener_datos()
                print("\nEstado de sensores:")
                for d in datos:
                    print(f"  Node {d['node_id']}: {d['value']:.2f}t, RSSI: {d['rssi']}dBm")
            
            else:
                print(f"Comando no reconocido: {command}")
                self.show_menu()
        
        except Exception as e:
            print(f"Error: {e}")
        
        return True
    
    def run(self):
        """Ejecuta la consola interactiva."""
        self.setup()
        self.show_menu()
        
        # No iniciar display automático, dejar que el usuario controle
        print("\nEscribe un comando (o 'q' para salir):")
        
        running = True
        while running:
            try:
                cmd = input("\n> ").strip()
                running = self.process_command(cmd)
            except KeyboardInterrupt:
                print("\n[Ctrl+C] Saliendo...")
                break
            except EOFError:
                break
        
        # Cleanup
        self.scenario_manager.deactivate_all()
        self.sistema.desconectar()
        print("\n¡Hasta luego!")


def run_automated_test():
    """
    Ejecuta una secuencia de pruebas automatizada.
    Útil para validar que todo funciona.
    """
    print("\n" + "="*60)
    print("  TEST AUTOMATIZADO")
    print("="*60)
    
    # Setup
    sistema = criar_sistema_pesaje("MSCL_MOCK", NODOS_CONFIG)
    sistema.conectar("COM_TEST")
    manager = TestScenarioManager(sistema)
    
    tests_passed = 0
    tests_failed = 0
    
    def check(name, condition):
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"  ✓ {name}")
            tests_passed += 1
        else:
            print(f"  ✗ {name}")
            tests_failed += 1
    
    # Test 1: Lectura normal
    print("\n[TEST 1] Lectura de datos normal")
    datos = sistema.obtener_datos()
    check("Obtener datos", len(datos) > 0)
    check("Datos tienen valor", all('value' in d for d in datos))
    check("Datos tienen RSSI", all('rssi' in d for d in datos))
    
    # Test 2: Escenario offline
    print("\n[TEST 2] Escenario sensor offline")
    node_id = list(NODOS_CONFIG.values())[0]['id']
    scenario = ScenarioPresets.sensor_offline(node_id)
    manager.activate_scenario(scenario)
    time.sleep(0.5)
    datos = sistema.obtener_datos()
    check("Sensor offline activo", len(manager.get_active_scenarios()) > 0)
    manager.deactivate_all()
    
    # Test 3: Escenario ruido
    print("\n[TEST 3] Escenario alto ruido")
    scenario = ScenarioPresets.high_noise(0.5)
    manager.activate_scenario(scenario)
    check("Escenario ruido activo", "Alto Ruido" in manager.get_active_scenarios())
    manager.deactivate_all()
    
    # Test 4: Tara
    print("\n[TEST 4] Funcionalidad de tara")
    sistema.tarar()
    check("Tara aplicada", True)  # Si no hay excepción
    sistema.reset_tarar()
    check("Tara reseteada", True)
    
    # Test 5: Múltiples escenarios
    print("\n[TEST 5] Múltiples escenarios simultáneos")
    manager.activate_scenario(ScenarioPresets.high_noise(0.3))
    manager.activate_scenario(ScenarioPresets.sensor_drift(node_id))
    check("Múltiples escenarios", len(manager.get_active_scenarios()) >= 2)
    manager.deactivate_all()
    check("Limpieza completa", len(manager.get_active_scenarios()) == 0)
    
    # Cleanup
    sistema.desconectar()
    
    # Resumen
    print("\n" + "="*60)
    print(f"  RESULTADOS: {tests_passed} pasados, {tests_failed} fallidos")
    print("="*60)
    
    return tests_failed == 0


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Pruebas de Balanza-Py")
    parser.add_argument('--auto', action='store_true', help='Ejecutar tests automatizados')
    args = parser.parse_args()
    
    if args.auto:
        success = run_automated_test()
        sys.exit(0 if success else 1)
    else:
        console = TestConsole()
        console.run()
