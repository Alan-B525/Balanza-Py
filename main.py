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


def hilo_adquisicion(data_queue, command_queue, sistema_pesaje, procesador, modbus_params=None, modbus_server=None):
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
    GUI_PUBLISH_INTERVAL_S = 0.05   # Limitar refresco GUI (~20 Hz) para mantener UI responsiva
    last_gui_publish_ts = 0.0
    
    # Variables para conexión asíncrona
    connection_thread = None
    connection_in_progress = False
    
    def _start_modbus_if_needed():
        nonlocal modbus_server
        if modbus_server is not None:
            return
        if not modbus_params:
            return
        serial_port = modbus_params.get('serial_port')
        if not serial_port:
            data_queue.put({'type': 'LOG', 'payload': "Modbus RTU não iniciado: porta serial não configurada."})
            return
        port_ok = True
        try:
            from serial.tools import list_ports
            ports = {p.device for p in list_ports.comports()}
            port_ok = serial_port in ports
        except Exception:
            port_ok = True
        if not port_ok:
            data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU não iniciado: porta {serial_port} indisponível."})
            return
        try:
            modbus_server = ModbusDataServer(
                serial_port=serial_port,
                baudrate=modbus_params.get('baudrate', 3000000),
                parity=modbus_params.get('parity', 'N'),
                stopbits=modbus_params.get('stopbits', 1),
                bytesize=modbus_params.get('bytesize', 8),
                timeout=modbus_params.get('timeout', 0.05),
            )
            modbus_server.start()
            data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU iniciado en {serial_port}"})
        except Exception as e:
            modbus_server = None
            data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU no iniciado: {e}"})

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
                                    data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'success', 'message': 'Conexão estabelecida'}})
                                    acquisition_paused = False
                                    reconnecting_nodes.clear()
                                    reconnect_attempts.clear()
                                    _start_modbus_if_needed()
                                else:
                                    # Si hubo recuperación parcial, reportar 'partial' en lugar de 'failed'
                                    if recovered > 0:
                                        try:
                                            expected = len(ACTIVE_NODOS) if ACTIVE_NODOS else 0
                                        except Exception:
                                            expected = 0
                                        data_queue.put({'type': 'LOG', 'payload': f"Conexão parcial: {recovered}/{expected} nós"})
                                        data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'partial', 'message': f'Conexão parcial: {recovered}/{expected} nós', 'recovered': recovered, 'expected': expected}})
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
                    data_queue.put({'type': 'LOG', 'payload': "Sistema desconectado pelo usuário."})
                    acquisition_paused = True
                    if modbus_server is not None:
                        try:
                            modbus_server.stop()
                        except Exception:
                            pass
                        modbus_server = None
                
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
                        data_queue.put({'type': 'LOG', 'payload': "Tara redefinida para 0."})
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
                            data_queue.put({'type': 'LOG', 'payload': f"Porta serial atualizada para {ACTIVE_COM}"})
                        if new_nodes:
                            ACTIVE_NODOS = new_nodes
                            # IMPORTANTE: Actualizar también el procesador con la nueva config
                            try:
                                procesador.update_config(ACTIVE_NODOS)
                                data_queue.put({'type': 'LOG', 'payload': "Configuração do processador atualizada."})
                            except Exception as e:
                                data_queue.put({'type': 'LOG', 'payload': f"Erro ao atualizar processador: {e}"})

                            # IMPORTANTE: Actualizar también el DRIVER (Mock) si lo soporta
                            try:
                                if hasattr(sistema_pesaje, 'update_nodes_config'):
                                    sistema_pesaje.update_nodes_config(ACTIVE_NODOS)
                                    data_queue.put({'type': 'LOG', 'payload': "Configuração do driver atualizada."})
                            except Exception as e:
                                data_queue.put({'type': 'LOG', 'payload': f"Erro ao atualizar driver: {e}"})

                            data_queue.put({'type': 'LOG', 'payload': f"Mapeamento de nós atualizado ({len(ACTIVE_NODOS)} nós)"})

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
                                    data_queue.put({'type': 'LOG', 'payload': f"Reconectado com sucesso em {ACTIVE_COM}"})
                                    data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'success', 'message': 'Reconexão estabelecida'}})
                                    acquisition_paused = False
                                    _start_modbus_if_needed()
                                else:
                                    if recovered > 0:
                                        try:
                                            expected = len(ACTIVE_NODOS) if ACTIVE_NODOS else 0
                                        except Exception:
                                            expected = 0
                                        data_queue.put({'type': 'LOG', 'payload': f"Conexão parcial após aplicar configuração: {recovered}/{expected} nós"})
                                        data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'partial', 'message': f'Conexão parcial: {recovered}/{expected} nós', 'recovered': recovered, 'expected': expected}})
                                    else:
                                        data_queue.put({'type': 'LOG', 'payload': f"Falha ao reconectar em {ACTIVE_COM}"})
                                        data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'failed', 'message': 'Falha ao reconectar'}})
                            except Exception as e:
                                data_queue.put({'type': 'LOG', 'payload': f"Erro durante reconexão: {e}"})
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
                        data_queue.put({'type': 'LOG', 'payload': f"Erro ao aplicar configuração: {e}"})
                elif cmd == 'EXIT':
                    running = False
                    sistema_pesaje.desconectar()
                    if modbus_server is not None:
                        try:
                            modbus_server.stop()
                        except Exception:
                            pass
                        modbus_server = None
                    
        except queue.Empty:
            pass
            
        # 2. Aquisicao de Dados (Se esta conectado e nao pausado)
        if sistema_pesaje.esta_conectado() and not acquisition_paused:
            try:
                raw_data = sistema_pesaje.obtener_datos()
                
                # Sempre processamos para verificar timeouts
                datos_procesados = procesador.procesar(raw_data)

                # Debug: registrar resumen rápido de lo que devolvió el procesador
                # (Comentado para evitar exceso de logs)
                # try:
                #     sensor_keys = list(datos_procesados.get('sensores', {}).keys())
                #     data_queue.put({'type': 'LOG', 'payload': f"Procesador: sensores={sensor_keys} total={datos_procesados.get('total')} any_disconnected={datos_procesados.get('any_disconnected', False)}"})
                # except Exception:
                #     pass
                
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
                    elif reconnect_check_counter[node_id] >= 333:  # Cada ~1 segundo con loop ~3ms
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
                
                # Enviar datos a GUI con tasa limitada para evitar congelamiento por cola
                now_ts = time.monotonic()
                if (now_ts - last_gui_publish_ts) >= GUI_PUBLISH_INTERVAL_S:
                    data_queue.put({'type': 'DATA', 'payload': datos_procesados})
                    last_gui_publish_ts = now_ts

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
        
        # Pausa dinámica para evitar saturar CPU y mantener UI responsiva
        if sistema_pesaje.esta_conectado() and not acquisition_paused:
            time.sleep(0.003)
        else:
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
    # Preparar configuración Modbus (RTU) usando settings.json/config
    modbus_params = None
    try:
        settings = config.load_settings()

        serial_port = None
        baudrate = 3000000
        parity = 'N'
        stopbits = 1
        bytesize = 8
        timeout = 0.05

        if settings and isinstance(settings.get('transmissao'), dict):
            t = settings.get('transmissao')
            porta_conf = t.get('porta')
            if isinstance(porta_conf, str) and porta_conf.strip():
                serial_port = porta_conf.strip()
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
            try:
                stopbits = int(t.get('stopbits', stopbits))
            except Exception:
                pass
            try:
                bytesize = int(t.get('bytesize', bytesize))
            except Exception:
                pass
            try:
                timeout = float(t.get('timeout', timeout))
            except Exception:
                pass

        if not serial_port:
            try:
                serial_port = ACTIVE_COM
            except Exception:
                serial_port = None

        modbus_params = {
            'serial_port': serial_port,
            'baudrate': baudrate,
            'parity': parity,
            'stopbits': stopbits,
            'bytesize': bytesize,
            'timeout': timeout,
        }
    except Exception:
        modbus_params = None
    modbus_server = None

    backend_thread = threading.Thread(
        target=hilo_adquisicion,
        args=(data_queue, command_queue, sistema_pesaje, procesador, modbus_params, modbus_server),
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
