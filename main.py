import sys
import os
import time
import threading
import queue
from typing import Dict

# Ensure modules can be imported
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from config import MODO_EJECUCION, PUERTO_COM, NODOS_CONFIG
from modules.data_processor import DataProcessor
from modules.gui import BalanzaGUI

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
                        connected = sistema_pesaje.conectar(PUERTO_COM)
                        data_queue.put({'type': 'STATUS', 'payload': connected})
                        if connected:
                            data_queue.put({'type': 'LOG', 'payload': f"Conectado exitosamente a {PUERTO_COM}"})
                        else:
                            data_queue.put({'type': 'LOG', 'payload': f"Fallo al conectar a {PUERTO_COM}"})
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
    # Colas de comunicación thread-safe
    data_queue = queue.Queue()
    command_queue = queue.Queue()
    
    # Inicializar Lógica de Negocio
    procesador = DataProcessor(NODOS_CONFIG)
    
    # Inicializar Hardware (Mock o Real)
    sistema_pesaje = crear_sistema_pesaje(MODO_EJECUCION, NODOS_CONFIG)
    
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
