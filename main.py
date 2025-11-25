import sys
import os
import time
import threading
import queue
from typing import Dict

# Ensure modules can be imported
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from config import MODO_EJECUCION, PUERTO_COM as DEFAULT_COM, NODOS_CONFIG as DEFAULT_NODOS
from modules.data_processor import DataProcessor
from modules.gui import BalanzaGUI

# Variables globales de configuración (pueden ser sobreescritas por settings.json)
ACTIVE_COM = DEFAULT_COM
ACTIVE_NODOS = DEFAULT_NODOS

def load_custom_settings():
    """Carga configuración desde settings.json si existe."""
    global ACTIVE_COM, ACTIVE_NODOS
    import json
    
    settings_path = os.path.join(current_dir, "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r') as f:
                settings = json.load(f)
                
            # Configurar Puerto / Conexión
            conn_type = settings.get("connection_type", "SERIAL")
            if conn_type == "TCP":
                ip = settings.get("tcp_ip", "127.0.0.1")
                port = settings.get("tcp_port", "8000")
                ACTIVE_COM = f"{ip}:{port}"
            else:
                ACTIVE_COM = settings.get("serial_port", DEFAULT_COM)
                
            # Configurar Nodos
            if "nodes" in settings:
                ACTIVE_NODOS = settings["nodes"]
                
            print(f"[INFO] Configuración cargada desde settings.json")
            print(f"       Puerto: {ACTIVE_COM}")
            print(f"       Nodos: {len(ACTIVE_NODOS)}")
            
        except Exception as e:
            print(f"[ERROR] Error cargando settings.json: {e}")

# Factory para instanciar el sensor correcto
def crear_sistema_pesaje(modo: str, config: Dict):
    if modo == "REAL":
        from modules.sensor_real import RealPesaje
        return RealPesaje()
    else:
        from modules.sensor_mock import MockPesaje
        return MockPesaje(config)

def hilo_adquisicion(data_queue, command_queue, sistema_pesaje, procesador):
    """
    Hilo secundario (Backend) que maneja el hardware y el procesamiento.
    """
    running = True
    
    while running:
        # 1. Procesar Comandos de la GUI
        try:
            while True:
                cmd_msg = command_queue.get_nowait()
                cmd = cmd_msg['cmd']
                
                if cmd == 'CONNECT':
                    try:
                        # Usar la configuración activa
                        connected = sistema_pesaje.conectar(ACTIVE_COM)
                        data_queue.put({'type': 'STATUS', 'payload': connected})
                        if connected:
                            data_queue.put({'type': 'LOG', 'payload': f"Conectado exitosamente a {ACTIVE_COM}"})
                        else:
                            data_queue.put({'type': 'LOG', 'payload': f"Fallo al conectar a {ACTIVE_COM}"})
                    except Exception as e:
                        data_queue.put({'type': 'ERROR', 'payload': str(e)})
                    
                elif cmd == 'DISCONNECT':
                    sistema_pesaje.desconectar()
                    data_queue.put({'type': 'STATUS', 'payload': False})
                    data_queue.put({'type': 'LOG', 'payload': "Sistema desconectado por el usuario."})
                    
                elif cmd == 'TARE':
                    procesador.set_tara()
                    data_queue.put({'type': 'LOG', 'payload': "Tara aplicada."})
                    # Opcional: sistema_pesaje.tarar() si fuera hardware
                    
                elif cmd == 'RESET_TARE':
                    procesador.reset_tara()
                    data_queue.put({'type': 'LOG', 'payload': "Tara reiniciada a 0."})
                    
                elif cmd == 'EXIT':
                    running = False
                    sistema_pesaje.desconectar()
                    
        except queue.Empty:
            pass
            
        # 2. Adquisición de Datos (Si está conectado)
        if sistema_pesaje.esta_conectado():
            try:
                raw_data = sistema_pesaje.obtener_datos()
                
                # Siempre procesamos para verificar timeouts, incluso si raw_data está vacío
                # (DataProcessor maneja el tiempo)
                datos_procesados = procesador.procesar(raw_data)
                
                # Extraer logs del procesador y enviarlos
                if 'logs' in datos_procesados:
                    for log_msg in datos_procesados['logs']:
                        data_queue.put({'type': 'LOG', 'payload': log_msg})
                
                # 4. Enviar a GUI
                data_queue.put({'type': 'DATA', 'payload': datos_procesados})
            except Exception as e:
                data_queue.put({'type': 'LOG', 'payload': f"Error en adquisición: {e}"})
        
        # Pequeña pausa para no saturar CPU
        time.sleep(0.05)

def main():
    # Cargar configuración personalizada
    load_custom_settings()

    # Colas de comunicación thread-safe
    data_queue = queue.Queue()
    command_queue = queue.Queue()
    
    # Inicializar Lógica de Negocio
    procesador = DataProcessor(ACTIVE_NODOS)
    
    # Inicializar Hardware (Mock o Real)
    sistema_pesaje = crear_sistema_pesaje(MODO_EJECUCION, ACTIVE_NODOS)
    
    # Iniciar Hilo de Backend
    backend_thread = threading.Thread(
        target=hilo_adquisicion,
        args=(data_queue, command_queue, sistema_pesaje, procesador),
        daemon=True
    )
    backend_thread.start()
    
    # Iniciar GUI (Hilo Principal)
    app = BalanzaGUI(data_queue, command_queue)
    app.mainloop()

if __name__ == "__main__":
    main()
