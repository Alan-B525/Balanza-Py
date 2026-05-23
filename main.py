import sys
import os
import time
import threading
import queue
import struct
from collections import deque
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
_SINGLE_INSTANCE_MUTEX = None

RUNTIME_TUNING = getattr(config, 'RUNTIME_TUNING', {})
DEBUG_PRINT_GETDATA_CALLS = bool(RUNTIME_TUNING.get('debug_print_getdata_calls', False))


def _acquire_single_instance() -> bool:
    """Evita ejecutar más de una instancia simultánea en Windows."""
    global _SINGLE_INSTANCE_MUTEX
    if os.name != 'nt':
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Global\\BalanzaPyMainMutex"
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            return True
        already_exists = (kernel32.GetLastError() == 183)  # ERROR_ALREADY_EXISTS
        if already_exists:
            print("[ERRO] Ya existe una instancia activa de la aplicación.")
            return False
        _SINGLE_INSTANCE_MUTEX = handle
        return True
    except Exception:
        return True


def load_custom_settings():
    """Carga los parametros desde settings.json si existe."""
    global ACTIVE_COM, ACTIVE_NODOS, ACTIVE_MODE, USE_SENSOR_CONFIG, RUNTIME_TUNING
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

            # Leer el puerto COM del primer nodo (fuente de verdad)
            if "nodes" in settings and isinstance(settings["nodes"], dict):
                first_node = next(iter(settings["nodes"].values()), {})
                ACTIVE_COM = first_node.get("com_port", "") or DEFAULT_COM
            elif "gateway" in settings and isinstance(settings["gateway"], dict):
                # Compatibilidad con settings.json anteriores
                ACTIVE_COM = settings["gateway"].get("porta", DEFAULT_COM)
            else:
                ACTIVE_COM = settings.get("serial_port", DEFAULT_COM)
                
            # Configurar Nos
            if "nodes" in settings:
                ACTIVE_NODOS = settings["nodes"]

            # Actualizar RUNTIME_TUNING con valores de settings.json (deep merge)
            if "runtime_tuning" in settings and isinstance(settings["runtime_tuning"], dict):
                RUNTIME_TUNING = {**RUNTIME_TUNING, **settings["runtime_tuning"]}
                
            print(f"[INFO] Configuracao carregada de settings.json")
            print(f"       Modo: {ACTIVE_MODE}")
            print(f"       Porta: {ACTIVE_COM}")
            print(f"       Nos: {len(ACTIVE_NODOS)}")
            print(f"       modbus_net_window_size: {RUNTIME_TUNING.get('modbus_net_window_size', 30)}")
            
        except Exception as e:
            print(f"[ERRO] Erro carregando settings.json: {e}")



def show_startup_info():
    """Muestra la informacion de inicio."""
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


def _float_to_float32_registers(value: float, swap_words: bool = False) -> list:
    """Convierte un float a dos registros Modbus (float32 IEEE754)."""
    try:
        packed = struct.pack('>f', float(value))
    except Exception:
        packed = struct.pack('>f', 0.0)
    hi = (packed[0] << 8) | packed[1]
    lo = (packed[2] << 8) | packed[3]
    if swap_words:
        return [lo, hi]
    return [hi, lo]


def hilo_adquisicion(data_queue, command_queue, sistema_pesaje, procesador, modbus_params=None, modbus_server=None, execution_mode=None):
    """

    Hilo secundario (Backend) que gestiona el hardware y el procesamiento.
    Incluye el manejo de desconexión de sensores y reconexión automática.
    """
    running = True
    acquisition_paused = False      # Flag para pausar adquisición
    reconnecting_nodes = set()      # Nodos en proceso de reconexión
    reconnect_attempts = {}         # {node_id: intentos}
    MAX_AUTO_RECONNECT = 5          # Máximo intentos automáticos
    reconnect_check_counter = {}    # Contador para espaciar notificaciones
    GUI_PUBLISH_INTERVAL_S = float(RUNTIME_TUNING.get('gui_publish_interval_s', 0.05))
    GUI_KEEPALIVE_S = float(RUNTIME_TUNING.get('gui_keepalive_s', 0.5))
    last_gui_publish_ts = 0.0
    last_gui_sample_ts = None
    # Diagnóstico breve: registrar solo algunas muestras tras conectar (sin spam)
    diag_samples_budget = 0
    diag_last_log_ts = 0.0
    
    # Variables para conexión asíncrona
    connection_thread = None
    connection_in_progress = False
    last_modbus_retry_ts = 0.0
    modbus_retry_interval_s = float(RUNTIME_TUNING.get('modbus_retry_interval_s', 2.0))
    modbus_last_not_started_reason = None
    last_modbus_sample_ts = None
    last_modbus_status = 'idle' # Track status to avoid spamming GUI updates
    modbus_start_ts = None
    modbus_start_grace_s = float(RUNTIME_TUNING.get('modbus_start_grace_s', 1.5))
    modbus_fail_count = 0
    modbus_fail_threshold = int(RUNTIME_TUNING.get('modbus_fail_threshold', 3))
    modbus_waiting_config_change = False
    modbus_state_lock = threading.Lock()
    modbus_block_size = max(1, int(RUNTIME_TUNING.get('modbus_net_window_size', 30)))
    modbus_net_window = deque(maxlen=modbus_block_size)
    last_angles = [0.0, 0.0, 0.0, 0.0, 0.0]
    cancel_connect_requested = False

    def _is_serial_port_available(port_name):
        try:
            if not port_name:
                return False
            import serial.tools.list_ports
            available = {str(p.device).strip().upper() for p in serial.tools.list_ports.comports()}
            return str(port_name).strip().upper() in available
        except Exception:
            # Si no podemos listar puertos, no bloquear el arranque por este chequeo
            return True
    
    def _start_modbus_if_needed():
        nonlocal modbus_server, modbus_last_not_started_reason, modbus_start_ts, modbus_fail_count, last_modbus_status, modbus_waiting_config_change
        with modbus_state_lock:
            if modbus_server is not None:
                return
            if not modbus_params:
                return
            if not bool(modbus_params.get('enabled', True)):
                return
            serial_port = modbus_params.get('serial_port')
            if not serial_port:
                reason = "porta serial não configurada"
                if modbus_last_not_started_reason != reason:
                    data_queue.put({'type': 'LOG', 'payload': "Modbus RTU não iniciado: porta serial não configurada."})
                    modbus_last_not_started_reason = reason
                return
            if modbus_waiting_config_change:
                if not _is_serial_port_available(serial_port):
                    return
                modbus_waiting_config_change = False
                modbus_last_not_started_reason = None
                data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU: porta {serial_port} voltou a ficar disponível, tentando reconectar..."})
            if not _is_serial_port_available(serial_port):
                reason = f"porta serial indisponível: {serial_port}"
                if modbus_last_not_started_reason != reason:
                    data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU em espera: porta {serial_port} não disponível. Altere em Configuração para tentar novamente."})
                    modbus_last_not_started_reason = reason
                modbus_waiting_config_change = True
                modbus_start_ts = None
                modbus_fail_count = 0
                if last_modbus_status != 'idle':
                    data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'idle'})
                    last_modbus_status = 'idle'
                return
            try:
                modbus_server = ModbusDataServer(
                    serial_port=serial_port,
                    baudrate=modbus_params.get('baudrate', 115200),
                    parity=modbus_params.get('parity', 'N'),
                    stopbits=modbus_params.get('stopbits', 1),
                    bytesize=modbus_params.get('bytesize', 8),
                    timeout=modbus_params.get('timeout', 0.05),
                )
                modbus_server.start()
                modbus_start_ts = time.monotonic()
                modbus_fail_count = 0
                modbus_waiting_config_change = False
                data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU iniciado em {serial_port}"})
                # Status update removed here; handled in main loop by checking push_data result
                modbus_last_not_started_reason = None
            except Exception as e:
                modbus_server = None
                modbus_start_ts = None
                modbus_fail_count = 0
                modbus_waiting_config_change = False
                reason = f"{type(e).__name__}: {e}"
                if modbus_last_not_started_reason != reason:
                    data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU não iniciado: {e}"})
                    data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'error'})
                    last_modbus_status = 'error'
                    modbus_last_not_started_reason = reason

    last_loop_time = time.perf_counter()

    while running:
        # Iniciar automaticamente o servidor Modbus RTU se o sistema está conectado
        try:
            if modbus_server is None and sistema_pesaje.esta_conectado() and not acquisition_paused:
                now_modbus = time.monotonic()
                if (now_modbus - last_modbus_retry_ts) >= modbus_retry_interval_s:
                    last_modbus_retry_ts = now_modbus
                    _start_modbus_if_needed()
        except Exception:
            pass

        # 1. Processar Comandos da GUI
        try:
            while True:
                cmd_msg = command_queue.get_nowait()
                cmd = cmd_msg['cmd']
                
                if cmd in ('CONNECT', 'CONNECT_WITH_PROGRESS'):
                    if not connection_in_progress:
                        connection_in_progress = True
                        
                        def do_connect():
                            nonlocal connection_in_progress, acquisition_paused, diag_samples_budget, diag_last_log_ts
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
                                if cancel_connect_requested:
                                    try:
                                        sistema_pesaje.desconectar()
                                    except Exception:
                                        pass
                                    data_queue.put({'type': 'STATUS', 'payload': False})
                                    data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'cancelled', 'message': 'Conexão cancelada'}})
                                    data_queue.put({'type': 'LOG', 'payload': 'Conexão cancelada pelo usuário.'})
                                    cancel_connect_requested = False
                                else:
                                    connected_effective = bool(connected or recovered > 0)
                                    data_queue.put({'type': 'STATUS', 'payload': connected_effective})
                                    if connected_effective:
                                        if connected:
                                            data_queue.put({'type': 'LOG', 'payload': f"Conectado com sucesso a {ACTIVE_COM}"})
                                            data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'success', 'message': 'Conexão estabelecida'}})
                                        else:
                                            try:
                                                expected = len(ACTIVE_NODOS) if ACTIVE_NODOS else 0
                                            except Exception:
                                                expected = 0
                                            data_queue.put({'type': 'LOG', 'payload': f"Conexão parcial: {recovered}/{expected} nós"})
                                            data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'partial', 'message': f'Conexão parcial: {recovered}/{expected} nós', 'recovered': recovered, 'expected': expected}})
                                        acquisition_paused = False
                                        modbus_net_window.clear()
                                        diag_samples_budget = 6
                                        diag_last_log_ts = 0.0
                                        reconnecting_nodes.clear()
                                        reconnect_attempts.clear()
                                        _start_modbus_if_needed()
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
                
                elif cmd == 'CANCEL_CONNECT':
                    cancel_connect_requested = True
                    data_queue.put({'type': 'LOG', 'payload': 'Cancelamento solicitado. Aguardando término da conexão...'} )
                    
                elif cmd == 'DISCONNECT':
                    sistema_pesaje.desconectar()
                    data_queue.put({'type': 'STATUS', 'payload': False})
                    data_queue.put({'type': 'LOG', 'payload': "Sistema desconectado pelo usuário."})
                    acquisition_paused = True
                    modbus_net_window.clear()
                    cancel_connect_requested = False
                    if modbus_server is not None:
                        try:
                            modbus_server.stop()
                        except Exception:
                            pass
                        modbus_server = None
                    modbus_last_not_started_reason = None
                    modbus_start_ts = None
                    modbus_fail_count = 0
                    modbus_waiting_config_change = False
                    last_modbus_status = 'idle'
                    data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'idle'})
                
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
                    new_transmissao = payload.get('transmissao')
                    try:
                        global ACTIVE_COM, ACTIVE_NODOS
                        # Fallback: si serial_port no viene o está vacío, leer com_port del primer nodo
                        if not new_port and new_nodes:
                            try:
                                first_node = next(iter(new_nodes.values()), {})
                                new_port = first_node.get('com_port', '')
                            except Exception:
                                pass
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

                            # Recalcular canal de publicação Modbus (celda_1 ch_load)
                            try:
                                if modbus_params is None:
                                    modbus_params = {}
                                modbus_params['data_source_key'] = None
                                cfg_c1 = ACTIVE_NODOS.get('celda_1', {}) if isinstance(ACTIVE_NODOS, dict) else {}
                                node_id = cfg_c1.get('id') if isinstance(cfg_c1, dict) else None
                                ch_load = None
                                if isinstance(cfg_c1, dict):
                                    ch_load = cfg_c1.get('ch_load') or cfg_c1.get('ch')
                                if node_id is not None:
                                    modbus_params['data_source_key'] = f"{node_id}:{ch_load or 'ch1'}"
                            except Exception:
                                pass

                        # Actualizar parámetros de Modbus RTU en caliente
                        if isinstance(new_transmissao, dict):
                            if modbus_params is None:
                                modbus_params = {}
                            old_modbus_conf = {
                                'serial_port': str(modbus_params.get('serial_port') or '').strip(),
                                'baudrate': modbus_params.get('baudrate'),
                                'parity': modbus_params.get('parity'),
                                'stopbits': modbus_params.get('stopbits'),
                                'bytesize': modbus_params.get('bytesize'),
                                'timeout': modbus_params.get('timeout'),
                                'enabled': bool(modbus_params.get('enabled', True)),
                            }
                            porta_conf = new_transmissao.get('porta')
                            if isinstance(porta_conf, str) and porta_conf.strip():
                                modbus_params['serial_port'] = porta_conf.strip()
                            elif 'porta' in new_transmissao:
                                modbus_params['serial_port'] = None
                            if 'enabled' in new_transmissao:
                                modbus_params['enabled'] = bool(new_transmissao.get('enabled'))
                            else:
                                modbus_params['enabled'] = bool(modbus_params.get('enabled', True) and modbus_params.get('serial_port'))
                            if 'swap_words' in new_transmissao:
                                modbus_params['swap_words'] = bool(new_transmissao.get('swap_words'))
                            try:
                                modbus_params['baudrate'] = int(new_transmissao.get('velocidade', modbus_params.get('baudrate', 3000000)))
                            except Exception:
                                pass
                            p = new_transmissao.get('paridade', modbus_params.get('parity', 'Nenhuma'))
                            if isinstance(p, str):
                                mp = p.lower()
                                if 'par' in mp and 'impar' not in mp:
                                    modbus_params['parity'] = 'E'
                                elif 'impar' in mp or 'ímpar' in mp:
                                    modbus_params['parity'] = 'O'
                                else:
                                    modbus_params['parity'] = 'N'
                            try:
                                modbus_params['stopbits'] = int(new_transmissao.get('stopbits', modbus_params.get('stopbits', 1)))
                            except Exception:
                                pass
                            try:
                                modbus_params['bytesize'] = int(new_transmissao.get('bytesize', modbus_params.get('bytesize', 8)))
                            except Exception:
                                pass
                            try:
                                modbus_params['timeout'] = float(new_transmissao.get('timeout', modbus_params.get('timeout', 0.05)))
                            except Exception:
                                pass
                            # Si cambia el puerto/config de Modbus, permitir nuevo intento de arranque
                            new_modbus_conf = {
                                'serial_port': str(modbus_params.get('serial_port') or '').strip(),
                                'baudrate': modbus_params.get('baudrate'),
                                'parity': modbus_params.get('parity'),
                                'stopbits': modbus_params.get('stopbits'),
                                'bytesize': modbus_params.get('bytesize'),
                                'timeout': modbus_params.get('timeout'),
                                'enabled': bool(modbus_params.get('enabled', True)),
                            }
                            modbus_waiting_config_change = False
                            modbus_last_not_started_reason = None
                            modbus_start_ts = None
                            modbus_fail_count = 0
                            modbus_conf_changed = (old_modbus_conf != new_modbus_conf)
                            if modbus_server is not None and (modbus_conf_changed or not new_modbus_conf.get('enabled', True)):
                                try:
                                    modbus_server.stop()
                                except Exception:
                                    pass
                                modbus_server = None
                                if last_modbus_status != 'idle':
                                    data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'idle'})
                                    last_modbus_status = 'idle'
                            data_queue.put({'type': 'LOG', 'payload': "Configuração de transmissão Modbus atualizada."})

                        # Si ya estamos conectados, desconectar y reconectar usando la nueva configuración
                        def do_reconnect():
                            nonlocal connection_in_progress, acquisition_paused, diag_samples_budget, diag_last_log_ts
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
                                    modbus_net_window.clear()
                                    diag_samples_budget = 6
                                    diag_last_log_ts = 0.0
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

                        # Solo reconectar automáticamente si el sistema YA estaba conectado.
                        # En primer guardado (instalación nueva) esto evita bloqueos percibidos
                        # por intentos de conexión largos desde estado desconectado.
                        try:
                            was_connected = bool(sistema_pesaje.esta_conectado())
                        except Exception:
                            was_connected = False

                        if was_connected:
                            if not connection_in_progress:
                                connection_in_progress = True
                                connection_thread = threading.Thread(target=do_reconnect, daemon=True)
                                connection_thread.start()
                        else:
                            data_queue.put({'type': 'LOG', 'payload': "Configuração salva. Reconexão automática ignorada (sistema desconectado)."})

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
                    modbus_last_not_started_reason = None
                    modbus_start_ts = None
                    modbus_fail_count = 0
                    modbus_waiting_config_change = False
                    last_modbus_status = 'idle'
                    
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

                # Actualizar ultimo snapshot de angulos para Modbus
                try:
                    angles = datos_procesados.get('angles')
                    if isinstance(angles, list) and angles:
                        cleaned = []
                        for val in angles[:5]:
                            try:
                                cleaned.append(float(val))
                            except Exception:
                                cleaned.append(0.0)
                        while len(cleaned) < 5:
                            cleaned.append(0.0)
                        last_angles = cleaned
                except Exception:
                    pass
                
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
                
                # Enviar datos a GUI sólo ante muestra nueva (o keepalive), evitando render redundante
                now_ts = time.monotonic()
                latest_sample_ts = None
                try:
                    last_frame = raw_data[-1] if isinstance(raw_data, list) and raw_data else {}
                    if isinstance(last_frame, dict):
                        latest_sample_ts = last_frame.get('timestamp_ns', None)
                        if latest_sample_ts is None:
                            latest_sample_ts = last_frame.get('timestamp', None)
                except Exception:
                    latest_sample_ts = None

                has_new_sample = latest_sample_ts is not None and latest_sample_ts != last_gui_sample_ts
                periodic_keepalive = (now_ts - last_gui_publish_ts) >= GUI_KEEPALIVE_S
                rate_ok = (now_ts - last_gui_publish_ts) >= GUI_PUBLISH_INTERVAL_S

                if (has_new_sample and rate_ok) or periodic_keepalive:
                    data_queue.put({'type': 'DATA', 'payload': datos_procesados})
                    last_gui_publish_ts = now_ts
                    if has_new_sample:
                        last_gui_sample_ts = latest_sample_ts

                    # Diagnóstico resumido de muestras (primeras tras conectar)
                    try:
                        if has_new_sample and diag_samples_budget > 0:
                            now_diag = time.monotonic()
                            if (now_diag - diag_last_log_ts) >= 0.20:
                                total_val = float(datos_procesados.get('total', 0.0) or 0.0)
                                total_raw = float(datos_procesados.get('total_raw', 0.0) or 0.0)
                                sensores = datos_procesados.get('sensores', {}) or {}
                                connected_count = 0
                                for info in sensores.values():
                                    try:
                                        if info.get('connected', False):
                                            connected_count += 1
                                    except Exception:
                                        continue
                                data_queue.put({'type': 'LOG', 'payload': f"[DIAG] sample ts={latest_sample_ts} total={total_val:.3f}kg raw={total_raw:.3f} sensores_on={connected_count}/{len(sensores)}"})
                                diag_samples_budget -= 1
                                diag_last_log_ts = now_diag
                    except Exception:
                        pass

                # Empujar datos al servidor Modbus (si está activo)
                try:
                        if modbus_server is not None and raw_data:
                            # Publicar sólo ante nueva muestra recibida del sensor
                            latest_ts = None
                            try:
                                last_frame = raw_data[-1] if isinstance(raw_data, list) and raw_data else {}
                                if isinstance(last_frame, dict):
                                    latest_ts = last_frame.get('timestamp_ns', None)
                                    if latest_ts is None:
                                        latest_ts = last_frame.get('timestamp', None)
                            except Exception:
                                latest_ts = None

                            # Publicar inmediatamente ante nueva muestra recibida del sensor
                            if latest_ts is None or latest_ts != last_modbus_sample_ts:
                                total_neto = float(datos_procesados.get('total', 0.0) or 0.0)
                                modbus_value = total_neto
                                try:
                                    if modbus_params and modbus_params.get('data_source_key'):
                                        src = modbus_params.get('data_source_key')
                                        sensores = datos_procesados.get('sensores', {}) or {}
                                        sensor_info = sensores.get('celda_1')
                                        if isinstance(sensor_info, dict) and sensor_info.get('key') == src:
                                            modbus_value = float(sensor_info.get('valor', total_neto))
                                        else:
                                            try:
                                                for info in sensores.values():
                                                    if isinstance(info, dict) and info.get('key') == src:
                                                        modbus_value = float(info.get('valor', total_neto))
                                                        break
                                            except Exception:
                                                pass
                                except Exception:
                                    modbus_value = total_neto
                                if latest_ts is not None:
                                    last_modbus_sample_ts = latest_ts

                            swap_words = False
                            try:
                                swap_words = bool((modbus_params or {}).get('swap_words', False))
                            except Exception:
                                swap_words = False

                            regs = _float_to_float32_registers(modbus_value, swap_words)

                            modbus_ok = modbus_server.push_data(regs)
                            if modbus_ok:
                                modbus_fail_count = 0
                                if last_modbus_status != 'connected':
                                    data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'connected'})
                                    last_modbus_status = 'connected'
                            else:
                                in_start_grace = (
                                    modbus_start_ts is not None
                                    and (time.monotonic() - modbus_start_ts) < modbus_start_grace_s
                                )
                                if not in_start_grace:
                                    modbus_fail_count += 1
                                    if modbus_fail_count >= modbus_fail_threshold:
                                        last_mb_error = ""
                                        try:
                                            if hasattr(modbus_server, 'get_last_error'):
                                                last_mb_error = str(modbus_server.get_last_error() or "")
                                        except Exception:
                                            last_mb_error = ""

                                        err_lower = last_mb_error.lower()
                                        port_blocked = (
                                            'permissionerror' in err_lower
                                            or 'acceso denegado' in err_lower
                                            or 'access is denied' in err_lower
                                            or 'could not open port' in err_lower
                                        )

                                        if last_modbus_status != 'error':
                                            data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'error'})
                                            data_queue.put({'type': 'LOG', 'payload': 'Modbus RTU inativo; aquisição seguirá sem Modbus.'})
                                            last_modbus_status = 'error'
                                        if port_blocked:
                                            modbus_waiting_config_change = True
                                            try:
                                                serial_conf = (modbus_params or {}).get('serial_port', '')
                                            except Exception:
                                                serial_conf = ''
                                            data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU em espera: porta {serial_conf} ocupada/sem acesso. Altere em Configuração para tentar novamente."})
                                        try:
                                            if modbus_server is not None:
                                                modbus_server.stop()
                                        except Exception:
                                            pass
                                        modbus_server = None
                                        modbus_start_ts = None
                                        modbus_fail_count = 0
                except Exception:
                    pass
                
            except Exception as e:
                data_queue.put({'type': 'LOG', 'payload': f"Erro na aquisicao: {e}"})
        
        # Pausa dinámica para garantizar una frecuencia de adquisición estable
        if sistema_pesaje.esta_conectado() and not acquisition_paused:
            target_interval = float(RUNTIME_TUNING.get('backend_sleep_connected_s', 0.003))
            now = time.perf_counter()
            elapsed = now - last_loop_time
            sleep_s = target_interval - elapsed
            
            if sleep_s > 0:
                time.sleep(sleep_s)
                last_loop_time = now + sleep_s
            else:
                last_loop_time = now  # Sin espera, el loop va retrasado
        else:
            time.sleep(float(RUNTIME_TUNING.get('backend_sleep_idle_s', 0.05)))
            last_loop_time = time.perf_counter()


def main():
    """Funcao principal da aplicacao."""
    # Otimizar temporizador no Windows para maior precisión de sleep (~1ms)
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass

    # El modo de pantalla se determina por configuración
    # Si el modo es 'tablet', se usará pantalla completa sin barra
    # Si no, se usará ventana normal
    
    load_custom_settings()
    show_startup_info()
    data_queue = queue.Queue()
    command_queue = queue.Queue()
    procesador = DataProcessor(ACTIVE_NODOS)
    if procesador.load_tara_state():
        import datetime
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
        modbus_enabled = False
        baudrate = 3000000
        parity = 'N'
        stopbits = 1
        bytesize = 8
        timeout = 0.05
        swap_words = False

        if settings and isinstance(settings.get('transmissao'), dict):
            t = settings.get('transmissao')
            if 'enabled' in t:
                modbus_enabled = bool(t.get('enabled'))
            else:
                modbus_enabled = True
            porta_conf = t.get('porta')
            if isinstance(porta_conf, str) and porta_conf.strip():
                serial_port = porta_conf.strip()
            swap_words = bool(t.get('swap_words', swap_words))
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

        # Determinar fuente de datos Modbus: celda_1 ch_load por defecto
        data_source_key = None
        try:
            if isinstance(ACTIVE_NODOS, dict):
                cfg_c1 = ACTIVE_NODOS.get('celda_1', {})
                if isinstance(cfg_c1, dict):
                    node_id = cfg_c1.get('id')
                    ch_load = cfg_c1.get('ch_load') or cfg_c1.get('ch')
                    if node_id is not None:
                        data_source_key = f"{node_id}:{ch_load or 'ch1'}"
        except Exception:
            data_source_key = None

        modbus_params = {
            'enabled': bool(modbus_enabled and serial_port),
            'serial_port': serial_port,
            'baudrate': baudrate,
            'parity': parity,
            'stopbits': stopbits,
            'bytesize': bytesize,
            'timeout': timeout,
            'swap_words': swap_words,
            'data_source_key': data_source_key,
        }
    except Exception:
        modbus_params = None
    modbus_server = None

    backend_thread = threading.Thread(
        target=hilo_adquisicion,
        args=(data_queue, command_queue, sistema_pesaje, procesador, modbus_params, modbus_server, ACTIVE_MODE),
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
    if _acquire_single_instance():
        main()
