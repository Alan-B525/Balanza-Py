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
    Incluye manejo de desconexión de sensores y reconexión automática.
    """
    running = True
    acquisition_paused = False      # Flag para pausar adquisición
    reconnecting_nodes = set()      # Nodos en proceso de reconexión
    reconnect_attempts = {}         # {node_id: intentos}
    MAX_AUTO_RECONNECT = 5          # Máximo intentos automáticos
    reconnect_check_counter = {}    # Contador para espaciar notificaciones
    
    # Variables para conexión asíncrona
    connection_thread = None
    connection_in_progress = False
    
    while running:
        # 1. Processar Comandos da GUI
        try:
            while True:
                cmd_msg = command_queue.get_nowait()
                cmd = cmd_msg['cmd']
                
                if cmd == 'CONNECT':
                    # Ejecutar conexión en hilo separado para no bloquear
                    if not connection_in_progress:
                        connection_in_progress = True
                        
                        def do_connect():
                            nonlocal connection_in_progress, acquisition_paused
                            try:
                                connected = sistema_pesaje.conectar(ACTIVE_COM)
                                data_queue.put({'type': 'STATUS', 'payload': connected})
                                if connected:
                                    data_queue.put({'type': 'LOG', 'payload': f"Conectado com sucesso a {ACTIVE_COM}"})
                                    acquisition_paused = False
                                    reconnecting_nodes.clear()
                                    reconnect_attempts.clear()
                                else:
                                    data_queue.put({'type': 'LOG', 'payload': f"Falha ao conectar a {ACTIVE_COM}"})
                            except Exception as e:
                                data_queue.put({'type': 'STATUS', 'payload': False})
                                data_queue.put({'type': 'LOG', 'payload': f"Erro: {str(e)}"})
                            finally:
                                connection_in_progress = False
                        
                        connection_thread = threading.Thread(target=do_connect, daemon=True)
                        connection_thread.start()
                
                elif cmd == 'CONNECT_WITH_PROGRESS':
                    # Mismo comportamiento que CONNECT
                    pass
                
                elif cmd == 'CANCEL_CONNECT':
                    # La cancelación se maneja en la GUI
                    pass
                    
                elif cmd == 'DISCONNECT':
                    sistema_pesaje.desconectar()
                    data_queue.put({'type': 'STATUS', 'payload': False})
                    data_queue.put({'type': 'LOG', 'payload': "Sistema desconectado pelo usuario."})
                    acquisition_paused = True
                
                elif cmd == 'PAUSE_ACQUISITION':
                    acquisition_paused = True
                    data_queue.put({'type': 'LOG', 'payload': "Aquisição pausada - aguardando reconexão"})
                
                elif cmd == 'RESUME_ACQUISITION':
                    acquisition_paused = False
                    reconnecting_nodes.clear()
                    reconnect_attempts.clear()
                    data_queue.put({'type': 'LOG', 'payload': "Aquisição retomada"})
                
                elif cmd == 'MANUAL_RECONNECT':
                    node_id = cmd_msg.get('node_id')
                    data_queue.put({'type': 'LOG', 'payload': f"Reconexão manual solicitada para sensor {node_id}"})
                    reconnect_attempts[node_id] = 0
                    reconnecting_nodes.discard(node_id)
                    acquisition_paused = False
                    
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
                    
        except queue.Empty:
            pass
            
        # 2. Aquisicao de Dados (Se esta conectado e nao pausado)
        if sistema_pesaje.esta_conectado() and not acquisition_paused:
            try:
                raw_data = sistema_pesaje.obtener_datos()
                
                # Sempre processamos para verificar timeouts
                datos_procesados = procesador.procesar(raw_data)
                
                # Extrair logs do processador e enviar
                if 'logs' in datos_procesados:
                    for log_msg in datos_procesados['logs']:
                        data_queue.put({'type': 'LOG', 'payload': log_msg})
                
                # === DETECCION DE DESCONEXION DE SENSORES ===
                if datos_procesados.get('disconnect_events'):
                    for event in datos_procesados['disconnect_events']:
                        node_id = event['node_id']
                        nombre = event['nombre']
                        
                        # Notificar a la GUI sobre desconexion
                        data_queue.put({
                            'type': 'SENSOR_DISCONNECT',
                            'payload': {
                                'node_id': node_id,
                                'nombre': nombre,
                                'timestamp': event['timestamp'],
                                'max_attempts': MAX_AUTO_RECONNECT
                            }
                        })
                        
                        # Iniciar reconexion automatica
                        if node_id not in reconnecting_nodes:
                            reconnecting_nodes.add(node_id)
                            reconnect_attempts[node_id] = 0
                            reconnect_check_counter[node_id] = 0
                
                # === MANEJO DE RECONEXION AUTOMATICA ===
                for node_id in list(reconnecting_nodes):
                    attempts = reconnect_attempts.get(node_id, 0)
                    reconnect_check_counter[node_id] = reconnect_check_counter.get(node_id, 0) + 1
                    
                    # Verificar si el nodo volvio a conectarse
                    is_connected = False
                    for sensor_data in datos_procesados.get('sensores', {}).values():
                        if sensor_data.get('id') == node_id and sensor_data.get('connected'):
                            is_connected = True
                            break
                    
                    if is_connected:
                        # Sensor reconectado exitosamente
                        reconnecting_nodes.discard(node_id)
                        reconnect_attempts.pop(node_id, None)
                        reconnect_check_counter.pop(node_id, None)
                        data_queue.put({
                            'type': 'SENSOR_RECONNECTED',
                            'payload': {'node_id': node_id}
                        })
                        data_queue.put({
                            'type': 'LOG',
                            'payload': f"Sensor {node_id} reconectado exitosamente"
                        })
                    elif reconnect_check_counter[node_id] >= 20:  # Cada ~1 segundo (20 * 50ms)
                        reconnect_check_counter[node_id] = 0
                        reconnect_attempts[node_id] = attempts + 1
                        
                        if attempts + 1 < MAX_AUTO_RECONNECT:
                            # Notificar progreso
                            data_queue.put({
                                'type': 'RECONNECT_PROGRESS',
                                'payload': {
                                    'node_id': node_id,
                                    'attempt': attempts + 1,
                                    'max_attempts': MAX_AUTO_RECONNECT
                                }
                            })
                        else:
                            # Maximo de intentos alcanzado
                            reconnecting_nodes.discard(node_id)
                            reconnect_check_counter.pop(node_id, None)
                            data_queue.put({
                                'type': 'RECONNECT_FAILED',
                                'payload': {
                                    'node_id': node_id,
                                    'attempts': MAX_AUTO_RECONNECT
                                }
                            })
                            data_queue.put({
                                'type': 'LOG',
                                'payload': f"Fallo reconexion de sensor {node_id} despues de {MAX_AUTO_RECONNECT} intentos"
                            })
                
                # Enviar datos a GUI
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
