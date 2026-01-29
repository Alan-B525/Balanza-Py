import sys
import os
import time
import threading
import queue
from typing import Dict


# Usar la lógica de rutas de config.py para máxima compatibilidad (EXE/script)
import config
current_dir = config.get_writable_dir()
sys.path.append(current_dir)

from config import MODO_EJECUCION, PUERTO_COM as DEFAULT_COM, NODOS_CONFIG as DEFAULT_NODOS
from modules.data_processor import DataProcessor
from modules.gui import BalanzaGUI
from modules.factory import criar_sistema_pesaje, check_mscl_installation
from modules.modbus_server import ModbusDataServer


ACTIVE_COM = DEFAULT_COM
ACTIVE_NODOS = DEFAULT_NODOS
ACTIVE_MODE = MODO_EJECUCION
USE_SENSOR_CONFIG = True


def load_custom_settings():
    """Carrega configuracao de settings.json se existir."""
    global ACTIVE_COM, ACTIVE_NODOS, ACTIVE_MODE, USE_SENSOR_CONFIG
    import json
    
    settings_path = os.path.join(current_dir, "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            # Leer si se debe usar la configuración cargada en el nodo
            USE_SENSOR_CONFIG = settings.get("use_sensor_config", True)

            # Configurar Modo de Execucao
            if "execution_mode" in settings:
                ACTIVE_MODE = settings["execution_mode"]

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
    # Usar logger central para mensajes de inicio (conciso)
    try:
        from modules import logger
        logger.step('startup', f"Modo={ACTIVE_MODE} | use_sensor_config={USE_SENSOR_CONFIG}")
        mscl_info = check_mscl_installation()
        if mscl_info.get('installed'):
            logger.info(f"MSCL instalado | version={mscl_info.get('version')}")
        else:
            logger.warning("MSCL no encontrado")
    except Exception:
        pass


def _float_to_int32_registers(value: float, scale: int = 1000) -> list:
    """Convierte un float a dos registros Modbus (int32) con escala."""
    try:
        ival = int(round(value * scale))
    except Exception:
        ival = 0
    # convertir a signed 32
    if ival < 0:
        ival = (1 << 32) + ival
    hi = (ival >> 16) & 0xFFFF
    lo = ival & 0xFFFF
    return [hi, lo]


def hilo_adquisicion(data_queue, command_queue, sistema_pesaje, procesador, modbus_server=None):
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
                    if not connection_in_progress:
                        connection_in_progress = True
                        
                        def do_connect():
                            nonlocal connection_in_progress, acquisition_paused
                            try:
                                # Registrar callback de progreso si el driver lo soporta
                                try:
                                    if hasattr(sistema_pesaje, 'set_progress_callback'):
                                        # Forward driver progress messages to GUI as CONNECTION_PROGRESS
                                        sistema_pesaje.set_progress_callback(lambda msg: data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'message': msg}}))
                                except Exception:
                                    pass

                                connected = sistema_pesaje.conectar(ACTIVE_COM)
                                # Obtener recuento de nodos recuperados, si está disponible
                                recovered = 0
                                try:
                                    if hasattr(sistema_pesaje, 'get_recovered_count'):
                                        recovered = int(sistema_pesaje.get_recovered_count() or 0)
                                except Exception:
                                    recovered = 0

                                data_queue.put({'type': 'STATUS', 'payload': connected})
                                if connected:
                                    data_queue.put({'type': 'LOG', 'payload': f"Conectado com sucesso a {ACTIVE_COM}"})
                                    # Notify GUI progress finished
                                    data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'success', 'message': 'Conexión establecida'}})
                                    acquisition_paused = False
                                    reconnecting_nodes.clear()
                                    reconnect_attempts.clear()
                                else:
                                    # Si hubo recuperación parcial, reportar 'partial' en lugar de 'failed'
                                    if recovered > 0:
                                        try:
                                            expected = len(ACTIVE_NODOS) if ACTIVE_NODOS else 0
                                        except Exception:
                                            expected = 0
                                        data_queue.put({'type': 'LOG', 'payload': f"Conexión parcial: {recovered}/{expected} nodos"})
                                        data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'partial', 'message': f'Conexión parcial: {recovered}/{expected} nodos', 'recovered': recovered, 'expected': expected}})
                                    else:
                                        data_queue.put({'type': 'LOG', 'payload': f"Falha ao conectar a {ACTIVE_COM}"})
                                        data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'failed', 'message': 'Falha ao conectar'}})
                            except Exception as e:
                                data_queue.put({'type': 'STATUS', 'payload': False})
                                data_queue.put({'type': 'LOG', 'payload': f"Erro: {str(e)}"})
                            finally:
                                try:
                                    if hasattr(sistema_pesaje, 'set_progress_callback'):
                                        sistema_pesaje.set_progress_callback(None)
                                except Exception:
                                    pass
                                connection_in_progress = False
                        
                        connection_thread = threading.Thread(target=do_connect, daemon=True)
                        connection_thread.start()
                
                elif cmd == 'CONNECT_WITH_PROGRESS':
                    pass
                
                elif cmd == 'CANCEL_CONNECT':
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
                    try:
                        new_tare = procesador.set_tara()
                        # Enviar actualización inmediata a la GUI para refrescar labels
                        data_queue.put({'type': 'DATA', 'payload': {'total_tare': new_tare}})
                        data_queue.put({'type': 'LOG', 'payload': "Tara aplicada."})
                    except Exception:
                        data_queue.put({'type': 'LOG', 'payload': "Erro aplicando tara."})
                    
                elif cmd == 'RESET_TARE':
                    try:
                        procesador.reset_tara()
                        # Notificar GUI inmediatamente
                        data_queue.put({'type': 'DATA', 'payload': {'total_tare': 0.0}})
                        data_queue.put({'type': 'LOG', 'payload': "Tara reiniciada para 0."})
                    except Exception:
                        data_queue.put({'type': 'LOG', 'payload': "Erro reiniciando tara."})
                    
                elif cmd == 'DISCOVER_NODES':
                    # Descobrir nos usando MSCL (WSDA-USB-200 Gateway)
                    if hasattr(sistema_pesaje, 'descubrir_nodos'):
                        try:
                            data_queue.put({'type': 'LOG', 'payload': "Buscando nós SG-Link via WSDA-USB-200..."})
                            nodos = sistema_pesaje.descubrir_nodos(timeout_ms=5000)
                            
                            if nodos:
                                # Enviar datos estructurados a la GUI
                                data_queue.put({
                                    'type': 'DISCOVERED_NODES',
                                    'payload': nodos
                                })
                                
                                # También log resumen
                                total_channels = sum(len(n.get('channels', [])) for n in nodos)
                                data_queue.put({
                                    'type': 'LOG', 
                                    'payload': f"✓ Encontrados {len(nodos)} nodo(s) com {total_channels} canal(is) total"
                                })
                            else:
                                data_queue.put({
                                    'type': 'DISCOVERED_NODES',
                                    'payload': []
                                })
                                data_queue.put({
                                    'type': 'LOG', 
                                    'payload': "⚠️ Nenhum nó encontrado. Verifique se os nós estão transmitindo."
                                })
                        except Exception as e:
                            data_queue.put({'type': 'LOG', 'payload': f"Erro buscando nós: {e}"})
                            data_queue.put({'type': 'DISCOVERED_NODES', 'payload': []})
                    else:
                        data_queue.put({'type': 'LOG', 'payload': "Descoberta não disponível em modo simulação."})
                        data_queue.put({'type': 'DISCOVERED_NODES', 'payload': []})
                    
                elif cmd == 'APPLY_CONFIG':
                    # Aplicar nueva configuración en caliente: puerto serial y asignación de nodos
                    payload = cmd_msg.get('payload', {}) or {}
                    new_port = payload.get('serial_port')
                    new_nodes = payload.get('nodes')
                    try:
                        global ACTIVE_COM, ACTIVE_NODOS
                        if new_port:
                            ACTIVE_COM = new_port
                            data_queue.put({'type': 'LOG', 'payload': f"Puerto serial actualizado a {ACTIVE_COM}"})
                        if new_nodes:
                            ACTIVE_NODOS = new_nodes
                            data_queue.put({'type': 'LOG', 'payload': f"Asignación de nodos actualizada ({len(ACTIVE_NODOS)} nodos)"})

                        # Si ya estamos conectados, desconectar y reconectar usando la nueva configuración
                        def do_reconnect():
                            nonlocal connection_in_progress, acquisition_paused
                            try:
                                try:
                                    if hasattr(sistema_pesaje, 'set_progress_callback'):
                                        sistema_pesaje.set_progress_callback(lambda msg: data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'message': msg}}))
                                except Exception:
                                    pass

                                # Forzar desconexión limpia
                                try:
                                    sistema_pesaje.desconectar()
                                except Exception:
                                    pass

                                connected = sistema_pesaje.conectar(ACTIVE_COM)
                                recovered = 0
                                try:
                                    if hasattr(sistema_pesaje, 'get_recovered_count'):
                                        recovered = int(sistema_pesaje.get_recovered_count() or 0)
                                except Exception:
                                    recovered = 0

                                data_queue.put({'type': 'STATUS', 'payload': connected})
                                if connected:
                                    data_queue.put({'type': 'LOG', 'payload': f"Re-conectado con éxito en {ACTIVE_COM}"})
                                    data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'success', 'message': 'Re-conexión establecida'}})
                                    acquisition_paused = False
                                else:
                                    if recovered > 0:
                                        try:
                                            expected = len(ACTIVE_NODOS) if ACTIVE_NODOS else 0
                                        except Exception:
                                            expected = 0
                                        data_queue.put({'type': 'LOG', 'payload': f"Conexión parcial tras aplicar config: {recovered}/{expected} nodos"})
                                        data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'partial', 'message': f'Conexión parcial: {recovered}/{expected} nodos', 'recovered': recovered, 'expected': expected}})
                                    else:
                                        data_queue.put({'type': 'LOG', 'payload': f"Fallo al reconectar en {ACTIVE_COM}"})
                                        data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'failed', 'message': 'Fallo al reconectar'}})
                            except Exception as e:
                                data_queue.put({'type': 'LOG', 'payload': f"Error durante reconexión: {e}"})
                            finally:
                                try:
                                    if hasattr(sistema_pesaje, 'set_progress_callback'):
                                        sistema_pesaje.set_progress_callback(None)
                                except Exception:
                                    pass
                                connection_in_progress = False

                        # Lanzar reconexión en hilo si ya conectado o intentar conectar si estaba desconectado
                        if not connection_in_progress:
                            connection_in_progress = True
                            connection_thread = threading.Thread(target=do_reconnect, daemon=True)
                            connection_thread.start()

                    except Exception as e:
                        data_queue.put({'type': 'LOG', 'payload': f"Error aplicando configuración: {e}"})
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

                # Debug: registrar resumen rápido de lo que devolvió el procesador
                try:
                    sensor_keys = list(datos_procesados.get('sensores', {}).keys())
                    data_queue.put({'type': 'LOG', 'payload': f"Procesador: sensores={sensor_keys} total={datos_procesados.get('total')} any_disconnected={datos_procesados.get('any_disconnected', False)}"})
                except Exception:
                    pass
                
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

                # Empujar datos al servidor Modbus (si está activo)
                try:
                    if modbus_server is not None:
                        # Enviar el total neto como int32 (2 registros) escalado x1000
                        total = float(datos_procesados.get('total', 0.0) or 0.0)
                        regs = _float_to_int32_registers(total, scale=1000)
                        modbus_server.push_data(regs)
                except Exception:
                    pass
                
            except Exception as e:
                data_queue.put({'type': 'LOG', 'payload': f"Erro na aquisicao: {e}"})
        
        # Pequena pausa para nao saturar CPU
        time.sleep(0.05)


def main():
    """Funcao principal da aplicacao."""
    # El modo de pantalla se determina por configuración
    # Si el modo es 'tablet', se usará pantalla completa sin barra
    # Si no, se usará ventana normal
    
    load_custom_settings()
    show_startup_info()
    data_queue = queue.Queue()
    command_queue = queue.Queue()
    procesador = DataProcessor(ACTIVE_NODOS)
    if procesador.load_tara_state():
        import datetime, os
        try:
            from modules import logger
            logger.info('Estado de tara cargado de settings.json')
        except Exception:
            pass
    try:
        from modules import logger
        logger.step('init', f'Creando sistema de pesaje | modo={ACTIVE_MODE}')
    except Exception:
        pass
    # Crear el driver en modo normal (permitir configuración de la red)
    # para intentar iniciar muestreo sincronizado y ver datos en tiempo real.
    sistema_pesaje = criar_sistema_pesaje(ACTIVE_MODE, ACTIVE_NODOS, use_sensor_config=USE_SENSOR_CONFIG, avoid_eeprom=False)
    try:
        from modules import logger
        # Log mapping lógico -> físico para diagnóstico rápido
        mapping_lines = []
        for name, cfg in ACTIVE_NODOS.items():
            mapping_lines.append(f"{name} -> id={cfg.get('id')} ch={cfg.get('ch')} serial={cfg.get('serial')}")
        logger.info('Mapping lógico→físico: ' + '; '.join(mapping_lines))
    except Exception:
        pass
    # Iniciar servidor Modbus (si la configuracion indica uso de transmissao TCP esperamos puerto en config)
    modbus_server = None
    try:
        settings = None
        try:
            import json
            with open(config.SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except Exception:
            settings = None

            # Forzar uso exclusivo de Modbus RTU (RS-485) por puerto serie.
            # Tomar `porta` de settings.transmissao si existe, sino usar `ACTIVE_COM`.
            serial_port = None
            baudrate = 9600
            parity = 'N'
            stopbits = 1
            bytesize = 8
            timeout = 1.0

            if settings and isinstance(settings.get('transmissao'), dict):
                t = settings.get('transmissao')
                porta_conf = t.get('porta')
                # Preferir valor explícito en transmissao.porta
                if isinstance(porta_conf, str) and porta_conf.strip():
                    serial_port = porta_conf.strip()
                # Configurar baudrate y paridad si vienen en settings
                try:
                    baudrate = int(t.get('velocidade', t.get('baudrate', baudrate)))
                except Exception:
                    pass
                p = t.get('paridade', t.get('parity', 'Nenhuma'))
                if isinstance(p, str):
                    mp = p.lower()
                    if 'par' in mp and 'impar' not in mp:
                        parity = 'E'
                    elif 'impar' in mp or 'ímpar' in mp:
                        parity = 'O'
                    else:
                        parity = 'N'

            # Si no se especificó en settings, usar ACTIVE_COM
            if not serial_port:
                try:
                    serial_port = ACTIVE_COM
                except Exception:
                    serial_port = None

            if not serial_port:
                # No hay puerto serie disponible: informar y no iniciar servidor
                print("[WARN] No se encontró puerto serie para Modbus RTU (transmissao.porta ni ACTIVE_COM). No se inicia servidor Modbus.")
                modbus_server = None
            else:
                modbus_server = ModbusDataServer(serial_port=serial_port, baudrate=baudrate, parity=parity, stopbits=stopbits, bytesize=bytesize, timeout=timeout)
                try:
                    modbus_server.start()
                except Exception as e:
                    print(f"[ERROR] No se pudo iniciar Modbus RTU: {e}")
                    modbus_server = None
    except Exception:
        modbus_server = None

    backend_thread = threading.Thread(
        target=hilo_adquisicion,
        args=(data_queue, command_queue, sistema_pesaje, procesador, modbus_server),
        daemon=True
    )
    backend_thread.start()
    # Solo modo tablet: sin barra superior
    app = BalanzaGUI(data_queue, command_queue, procesador)
    # Establecer icono de la ventana usando assets/icon.ico (fallback a icon.png)
    try:
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        assets_dir = os.path.join(base_path, 'assets')
        ico_path = os.path.join(assets_dir, 'icon.ico')
        png_path = os.path.join(assets_dir, 'icon.png')
        if os.path.exists(ico_path):
            try:
                app.iconbitmap(ico_path)
            except Exception:
                # En algunas plataformas/tk versiones puede fallar; intentar iconphoto
                try:
                    img = None
                    from PIL import Image, ImageTk
                    img = ImageTk.PhotoImage(Image.open(ico_path))
                    app.iconphoto(False, img)
                    # Mantener referencia para evitar GC
                    app._icon_img = img
                except Exception:
                    pass
        elif os.path.exists(png_path):
            try:
                from PIL import Image, ImageTk
                img = ImageTk.PhotoImage(Image.open(png_path))
                app.iconphoto(False, img)
                app._icon_img = img
            except Exception:
                pass
    except Exception:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()
