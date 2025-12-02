"""
Balanza-Py - Sistema de Pesagem Industrial
Ponto de entrada principal da aplicacao.

Arquitetura: Producer-Consumer com threads
- Thread Principal: GUI (Tkinter)
- Thread Backend: Aquisicao de dados e processamento
"""

import sys
import os
import time
import threading
import queue
import random
from typing import Dict

# Garantir que os modulos podem ser importados
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from config import MODO_EJECUCION, PUERTO_COM as DEFAULT_COM, NODOS_CONFIG as DEFAULT_NODOS
from modules.data_processor import DataProcessor
from modules.gui import BalanzaGUI
from modules.factory import criar_sistema_pesaje, check_mscl_installation

# Variaveis globais de configuracao (podem ser sobrescritas por settings.json)
ACTIVE_COM = DEFAULT_COM
ACTIVE_NODOS = DEFAULT_NODOS
ACTIVE_MODE = MODO_EJECUCION


def load_custom_settings():
    """Carrega configuracao de settings.json se existir."""
    global ACTIVE_COM, ACTIVE_NODOS, ACTIVE_MODE
    import json
    
    settings_path = os.path.join(current_dir, "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            # Configurar Modo de Execucao
            if "execution_mode" in settings:
                ACTIVE_MODE = settings["execution_mode"]
                
            # Configurar Porta / Conexao
            conn_type = settings.get("connection_type", "SERIAL")
            if conn_type == "TCP":
                ip = settings.get("tcp_ip", "127.0.0.1")
                port = settings.get("tcp_port", "8000")
                ACTIVE_COM = f"{ip}:{port}"
            else:
                ACTIVE_COM = settings.get("serial_port", DEFAULT_COM)
                
            # Configurar Nos
            if "nodes" in settings:
                ACTIVE_NODOS = settings["nodes"]
                
            print(f"[INFO] Configuracao carregada de settings.json")
            print(f"       Modo: {ACTIVE_MODE}")
            print(f"       Porta: {ACTIVE_COM}")
            print(f"       Nos: {len(ACTIVE_NODOS)}")
            
        except Exception as e:
            print(f"[ERRO] Erro carregando settings.json: {e}")


def show_startup_info():
    """Mostra informacoes de inicializacao."""
    print("=" * 60)
    print("  BALANZA-PY - Sistema de Pesagem Industrial")
    print("=" * 60)
    print(f"  Modo de Execucao: {ACTIVE_MODE}")
    
    # Verificar MSCL
    mscl_info = check_mscl_installation()
    if mscl_info["installed"]:
        print(f"  MSCL: Instalado")
        if mscl_info["version"]:
            print(f"  MSCL Versao: {mscl_info['version']}")
    else:
        print(f"  MSCL: Nao encontrado")
    
    print("=" * 60)


def hilo_adquisicion(data_queue, command_queue, sistema_pesaje, procesador):
    """
    Thread secundaria (Backend) que gerencia o hardware e o processamento.
    """
    running = True
    
    while running:
        # 1. Processar Comandos da GUI
        try:
            while True:
                cmd_msg = command_queue.get_nowait()
                cmd = cmd_msg['cmd']
                
                if cmd == 'CONNECT':
                    try:
                        # Usar a configuracao ativa
                        connected = sistema_pesaje.conectar(ACTIVE_COM)
                        data_queue.put({'type': 'STATUS', 'payload': connected})
                        if connected:
                            data_queue.put({'type': 'LOG', 'payload': f"Conectado com sucesso a {ACTIVE_COM}"})
                        else:
                            data_queue.put({'type': 'LOG', 'payload': f"Falha ao conectar a {ACTIVE_COM}"})
                    except Exception as e:
                        data_queue.put({'type': 'ERROR', 'payload': str(e)})
                    
                elif cmd == 'DISCONNECT':
                    sistema_pesaje.desconectar()
                    data_queue.put({'type': 'STATUS', 'payload': False})
                    data_queue.put({'type': 'LOG', 'payload': "Sistema desconectado pelo usuario."})
                    
                elif cmd == 'TARE':
                    procesador.set_tara()
                    data_queue.put({'type': 'LOG', 'payload': "Tara aplicada."})
                    
                elif cmd == 'RESET_TARE':
                    procesador.reset_tara()
                    data_queue.put({'type': 'LOG', 'payload': "Tara reiniciada para 0."})
                    
                elif cmd == 'DISCOVER_NODES':
                    # Descobrir nos usando MSCL
                    if hasattr(sistema_pesaje, 'descubrir_nodos'):
                        try:
                            nodos = sistema_pesaje.descubrir_nodos()
                            if nodos:
                                data_queue.put({'type': 'LOG', 'payload': f"Nos encontrados: {nodos}"})
                            else:
                                data_queue.put({'type': 'LOG', 'payload': "Nenhum no encontrado. Verifique a conexao."})
                        except Exception as e:
                            data_queue.put({'type': 'LOG', 'payload': f"Erro buscando nos: {e}"})
                    else:
                        data_queue.put({'type': 'LOG', 'payload': "Descoberta nao disponivel em modo simulacao."})
                    
                elif cmd == 'EXIT':
                    running = False
                    sistema_pesaje.desconectar()
                
                # === Comandos de TEST (solo en modo MOCK) ===
                elif cmd == 'TEST_SENSOR_OFFLINE':
                    node_id = cmd_msg.get('node_id')
                    if hasattr(sistema_pesaje, 'simular_desconexao_no'):
                        sistema_pesaje.simular_desconexao_no(node_id)
                        data_queue.put({'type': 'LOG', 'payload': f"[TEST] Sensor {node_id} marcado como offline"})
                    else:
                        data_queue.put({'type': 'LOG', 'payload': "[TEST] Comando não disponível neste modo"})
                
                elif cmd == 'TEST_SENSOR_ONLINE':
                    node_id = cmd_msg.get('node_id')
                    if hasattr(sistema_pesaje, 'simular_reconexao_no'):
                        sistema_pesaje.simular_reconexao_no(node_id)
                        data_queue.put({'type': 'LOG', 'payload': f"[TEST] Sensor {node_id} reconectado"})
                
                elif cmd == 'TEST_RAMP_UP':
                    weight = cmd_msg.get('weight', 50.0)
                    # Soportar MSCL_MOCK con _mock_nodes
                    if hasattr(sistema_pesaje, '_mock_nodes'):
                        per_node = weight / len(sistema_pesaje._mock_nodes)
                        for node in sistema_pesaje._mock_nodes.values():
                            if hasattr(node, 'apply_load'):
                                node.apply_load(per_node)
                        data_queue.put({'type': 'LOG', 'payload': f"[TEST] Rampa de carga: +{weight}t distribuídos"})
                    # Soportar MOCK simple con _base_values
                    elif hasattr(sistema_pesaje, '_base_values'):
                        per_node = weight / len(sistema_pesaje._base_values)
                        for node_id in sistema_pesaje._base_values:
                            sistema_pesaje._base_values[node_id] += per_node
                        data_queue.put({'type': 'LOG', 'payload': f"[TEST] Rampa de carga: +{weight}t distribuídos"})
                
                elif cmd == 'TEST_RAMP_DOWN':
                    if hasattr(sistema_pesaje, '_mock_nodes'):
                        for node in sistema_pesaje._mock_nodes.values():
                            if hasattr(node, 'reset_to_base'):
                                node.reset_to_base(5.0)
                        data_queue.put({'type': 'LOG', 'payload': "[TEST] Descarga simulada"})
                    elif hasattr(sistema_pesaje, '_base_values'):
                        for node_id in sistema_pesaje._base_values:
                            sistema_pesaje._base_values[node_id] = random.uniform(5.0, 8.0)
                        data_queue.put({'type': 'LOG', 'payload': "[TEST] Descarga simulada"})
                
                elif cmd == 'TEST_SPIKE':
                    magnitude = cmd_msg.get('magnitude', 10.0)
                    if hasattr(sistema_pesaje, '_mock_nodes'):
                        per_node = magnitude / len(sistema_pesaje._mock_nodes)
                        for node in sistema_pesaje._mock_nodes.values():
                            if hasattr(node, 'apply_modifiers'):
                                node.apply_modifiers({'spike': per_node})
                        data_queue.put({'type': 'LOG', 'payload': f"[TEST] Impacto: +{magnitude}t"})
                    elif hasattr(sistema_pesaje, '_base_values'):
                        # Para MOCK simple, solo incrementar temporalmente
                        per_node = magnitude / len(sistema_pesaje._base_values)
                        for node_id in sistema_pesaje._base_values:
                            sistema_pesaje._base_values[node_id] += per_node
                        data_queue.put({'type': 'LOG', 'payload': f"[TEST] Impacto: +{magnitude}t"})
                
                elif cmd == 'TEST_NOISE':
                    if hasattr(sistema_pesaje, '_mock_nodes'):
                        for node in sistema_pesaje._mock_nodes.values():
                            if hasattr(node, 'apply_modifiers'):
                                node.apply_modifiers({'noise': 0.5})
                        data_queue.put({'type': 'LOG', 'payload': "[TEST] Alto ruído activado"})
                    elif hasattr(sistema_pesaje, '_test_modifiers') or hasattr(sistema_pesaje, '_base_values'):
                        sistema_pesaje._test_modifiers = {nid: {'noise': 0.5} for nid in sistema_pesaje._base_values}
                        data_queue.put({'type': 'LOG', 'payload': "[TEST] Alto ruído activado"})
                
                elif cmd == 'TEST_RESET_ALL':
                    if hasattr(sistema_pesaje, '_mock_nodes'):
                        for node in sistema_pesaje._mock_nodes.values():
                            if hasattr(node, 'set_offline'):
                                node.set_offline(False)
                            if hasattr(node, 'apply_modifiers'):
                                node.apply_modifiers({})
                            if hasattr(node, 'reset_to_base'):
                                node.reset_to_base()
                        data_queue.put({'type': 'LOG', 'payload': "[TEST] Todos os testes resetados"})
                    elif hasattr(sistema_pesaje, '_base_values'):
                        sistema_pesaje._offline_nodes = set()
                        sistema_pesaje._test_modifiers = {}
                        for node_id in sistema_pesaje._base_values:
                            sistema_pesaje._base_values[node_id] = random.uniform(5.0, 15.0)
                        data_queue.put({'type': 'LOG', 'payload': "[TEST] Todos os testes resetados"})
                    
        except queue.Empty:
            pass
            
        # 2. Aquisicao de Dados (Se esta conectado)
        if sistema_pesaje.esta_conectado():
            try:
                raw_data = sistema_pesaje.obtener_datos()
                
                # Sempre processamos para verificar timeouts
                datos_procesados = procesador.procesar(raw_data)
                
                # Extrair logs do processador e enviar
                if 'logs' in datos_procesados:
                    for log_msg in datos_procesados['logs']:
                        data_queue.put({'type': 'LOG', 'payload': log_msg})
                
                # 4. Enviar a GUI
                data_queue.put({'type': 'DATA', 'payload': datos_procesados})
            except Exception as e:
                data_queue.put({'type': 'LOG', 'payload': f"Erro na aquisicao: {e}"})
        
        # Pequena pausa para nao saturar CPU
        time.sleep(0.05)


def main():
    """Funcao principal da aplicacao."""
    # Carregar configuracao personalizada primeiro (para ter ACTIVE_MODE)
    load_custom_settings()
    
    # Mostrar informacoes de inicializacao
    show_startup_info()

    # Filas de comunicacao thread-safe
    data_queue = queue.Queue()
    command_queue = queue.Queue()
    
    # Inicializar Logica de Negocio
    procesador = DataProcessor(ACTIVE_NODOS)
    
    # Inicializar Hardware (Mock ou Real) usando a factory e modo configurado
    print(f"[INFO] Criando sistema de pesagem no modo: {ACTIVE_MODE}")
    sistema_pesaje = criar_sistema_pesaje(ACTIVE_MODE, ACTIVE_NODOS)
    
    # Iniciar Thread de Backend
    backend_thread = threading.Thread(
        target=hilo_adquisicion,
        args=(data_queue, command_queue, sistema_pesaje, procesador),
        daemon=True
    )
    backend_thread.start()
    
    # Iniciar GUI (Thread Principal)
    app = BalanzaGUI(data_queue, command_queue)
    app.mainloop()


if __name__ == "__main__":
    main()
