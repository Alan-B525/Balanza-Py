import os
import sys
import time
import struct
import threading
import queue
from collections import deque
from typing import Dict, Any, List, Optional, Set

import config
from modules import logger
from modules.interfaces import ConnectionState
from modules.modbus_server import ModbusDataServer


class BackendController:
    """
    Controlador del Backend que gestiona el hardware de pesaje, el procesamiento
    de datos en segundo plano y la publicación en Modbus RTU.
    """

    def __init__(
        self,
        data_queue: queue.Queue,
        command_queue: queue.Queue,
        sistema_pesaje,
        procesador,
        modbus_params: Optional[Dict[str, Any]] = None,
        execution_mode: str = "MOCK",
    ):
        self.data_queue = data_queue
        self.command_queue = command_queue
        self.sistema_pesaje = sistema_pesaje
        self.procesador = procesador
        self.execution_mode = execution_mode

        # Lock para proteger las variables compartidas de configuración
        self.state_lock = threading.Lock()
        
        # Parámetros compartidos (protegidos por state_lock)
        self.active_com = config.PUERTO_COM
        self.active_nodos = config.NODOS_CONFIG
        self.use_sensor_config = True
        self.modbus_params = modbus_params or {}

        # Modbus server lifecycle variables (protegidos por modbus_state_lock)
        self.modbus_state_lock = threading.Lock()
        self.modbus_server: Optional[ModbusDataServer] = None
        self.modbus_last_not_started_reason: Optional[str] = None
        self.modbus_waiting_config_change = False
        self.modbus_start_ts: Optional[float] = None
        self.modbus_fail_count = 0
        self.last_modbus_status = 'idle'
        self.last_modbus_sample_ts = None
        self.last_modbus_retry_ts = 0.0

        # Control de ejecución y flags asíncronos (Thread-safe Events)
        self.running = False
        self.acquisition_paused = False
        self.connection_in_progress = threading.Event()
        self.cancel_connect_requested = threading.Event()

        # Reconexión automática de nodos
        self.reconnecting_nodes: Set[int] = set()
        self.reconnect_attempts: Dict[int, int] = {}
        self.reconnect_check_counter: Dict[int, int] = {}
        self.MAX_AUTO_RECONNECT = 5

        # Diagnóstico y publicación en GUI
        self.RUNTIME_TUNING = getattr(config, 'RUNTIME_TUNING', {})
        self.GUI_PUBLISH_INTERVAL_S = float(self.RUNTIME_TUNING.get('gui_publish_interval_s', 0.05))
        self.GUI_KEEPALIVE_S = float(self.RUNTIME_TUNING.get('gui_keepalive_s', 0.5))
        self.last_gui_publish_ts = 0.0
        self.last_gui_sample_ts = None
        self.diag_samples_budget = 0
        self.diag_last_log_ts = 0.0

        # Modbus config tuning
        self.modbus_retry_interval_s = float(self.RUNTIME_TUNING.get('modbus_retry_interval_s', 2.0))
        self.modbus_start_grace_s = float(self.RUNTIME_TUNING.get('modbus_start_grace_s', 1.5))
        self.modbus_fail_threshold = int(self.RUNTIME_TUNING.get('modbus_fail_threshold', 3))
        self.modbus_block_size = max(1, int(self.RUNTIME_TUNING.get('modbus_net_window_size', 30)))
        self.modbus_net_window = deque(maxlen=self.modbus_block_size)
        self.last_angles = [0.0, 0.0, 0.0, 0.0, 0.0]

        # Referencia al thread principal
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Inicia el bucle de procesamiento del controlador en segundo plano."""
        self.running = True
        self._thread = threading.Thread(target=self._main_loop, name="BackendThread", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Detiene el controlador y libera recursos."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _get_active_com(self) -> str:
        with self.state_lock:
            return self.active_com

    def _get_active_nodos(self) -> Dict[str, Any]:
        with self.state_lock:
            return self.active_nodos.copy() if self.active_nodos else {}

    def _is_serial_port_available(self, port_name: Optional[str]) -> bool:
        if not port_name:
            return False
        try:
            import serial.tools.list_ports
            available = {str(p.device).strip().upper() for p in serial.tools.list_ports.comports()}
            return str(port_name).strip().upper() in available
        except Exception:
            return True

    def _float_to_float32_registers(self, value: float, swap_words: bool = False) -> list:
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

    def _start_modbus_if_needed(self) -> None:
        """Inicia el servidor Modbus RTU si está habilitado y configurado."""
        with self.modbus_state_lock:
            if self.modbus_server is not None:
                return

            with self.state_lock:
                mb_params = self.modbus_params.copy() if self.modbus_params else {}

            if not mb_params or not bool(mb_params.get('enabled', True)):
                return

            serial_port = mb_params.get('serial_port')
            if not serial_port:
                reason = "porta serial não configurada"
                if self.modbus_last_not_started_reason != reason:
                    self.data_queue.put({'type': 'LOG', 'payload': "Modbus RTU não iniciado: porta serial não configurada."})
                    self.modbus_last_not_started_reason = reason
                return

            if self.modbus_waiting_config_change:
                if not self._is_serial_port_available(serial_port):
                    return
                self.modbus_waiting_config_change = False
                self.modbus_last_not_started_reason = None
                self.data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU: porta {serial_port} voltou a ficar disponível, tentando reconectar..."})

            if not self._is_serial_port_available(serial_port):
                reason = f"porta serial indisponível: {serial_port}"
                if self.modbus_last_not_started_reason != reason:
                    self.data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU em espera: porta {serial_port} não disponible. Altere em Configuração para tentar novamente."})
                    self.modbus_last_not_started_reason = reason
                self.modbus_waiting_config_change = True
                self.modbus_start_ts = None
                self.modbus_fail_count = 0
                if self.last_modbus_status != 'idle':
                    self.data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'idle'})
                    self.last_modbus_status = 'idle'
                return

            try:
                self.modbus_server = ModbusDataServer(
                    serial_port=serial_port,
                    baudrate=mb_params.get('baudrate', 115200),
                    parity=mb_params.get('parity', 'N'),
                    stopbits=mb_params.get('stopbits', 1),
                    bytesize=mb_params.get('bytesize', 8),
                    timeout=mb_params.get('timeout', 0.05),
                )
                self.modbus_server.start()
                self.modbus_start_ts = time.monotonic()
                self.modbus_fail_count = 0
                self.modbus_waiting_config_change = False
                self.data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU iniciado em {serial_port}"})
                self.modbus_last_not_started_reason = None
            except Exception as e:
                self.modbus_server = None
                self.modbus_start_ts = None
                self.modbus_fail_count = 0
                self.modbus_waiting_config_change = False
                reason = f"{type(e).__name__}: {e}"
                if self.modbus_last_not_started_reason != reason:
                    self.data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU não iniciado: {e}"})
                    self.data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'error'})
                    self.last_modbus_status = 'error'
                    self.modbus_last_not_started_reason = reason

    def _do_connect(self) -> None:
        """Operación de conexión en un hilo secundario para evitar congelar la GUI."""
        try:
            if hasattr(self.sistema_pesaje, 'set_progress_callback'):
                self.sistema_pesaje.set_progress_callback(
                    lambda msg: self.data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'message': msg}})
                )
            
            com_port = self._get_active_com()
            connected = self.sistema_pesaje.conectar(com_port)
            
            recovered = 0
            if hasattr(self.sistema_pesaje, 'get_recovered_count'):
                recovered = int(self.sistema_pesaje.get_recovered_count() or 0)

            if self.cancel_connect_requested.is_set():
                try:
                    self.sistema_pesaje.desconectar()
                except Exception:
                    pass
                self.data_queue.put({'type': 'STATUS', 'payload': False})
                self.data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'cancelled', 'message': 'Conexão cancelada'}})
                self.data_queue.put({'type': 'LOG', 'payload': 'Conexão cancelada pelo usuário.'})
                self.cancel_connect_requested.clear()
            else:
                connected_effective = bool(connected or recovered > 0)
                self.data_queue.put({'type': 'STATUS', 'payload': connected_effective})
                if connected_effective:
                    if connected:
                        self.data_queue.put({'type': 'LOG', 'payload': f"Conectado com sucesso a {com_port}"})
                        self.data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'success', 'message': 'Conexão estabelecida'}})
                    else:
                        expected = 0
                        nodos = self._get_active_nodos()
                        if nodos:
                            expected = len(nodos)
                        self.data_queue.put({'type': 'LOG', 'payload': f"Conexão parcial: {recovered}/{expected} nós"})
                        self.data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'partial', 'message': f'Conexão parcial: {recovered}/{expected} nós', 'recovered': recovered, 'expected': expected}})
                    
                    self.acquisition_paused = False
                    self.modbus_net_window.clear()
                    self.diag_samples_budget = 6
                    self.diag_last_log_ts = 0.0
                    self.reconnecting_nodes.clear()
                    self.reconnect_attempts.clear()
                    self._start_modbus_if_needed()
                else:
                    self.data_queue.put({'type': 'LOG', 'payload': f"Falha ao conectar a {com_port}"})
                    self.data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'failed', 'message': 'Falha ao conectar'}})
        except Exception as e:
            self.data_queue.put({'type': 'STATUS', 'payload': False})
            self.data_queue.put({'type': 'LOG', 'payload': f"Erro: {str(e)}"})
        finally:
            if hasattr(self.sistema_pesaje, 'set_progress_callback'):
                try:
                    self.sistema_pesaje.set_progress_callback(None)
                except Exception:
                    pass
            self.connection_in_progress.clear()

    def _do_reconnect(self) -> None:
        """Reconexión asíncrona tras cambios de configuración en caliente."""
        try:
            if hasattr(self.sistema_pesaje, 'set_progress_callback'):
                self.sistema_pesaje.set_progress_callback(
                    lambda msg: self.data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'message': msg}})
                )

            try:
                self.sistema_pesaje.desconectar()
            except Exception:
                pass

            com_port = self._get_active_com()
            connected = self.sistema_pesaje.conectar(com_port)
            
            recovered = 0
            if hasattr(self.sistema_pesaje, 'get_recovered_count'):
                recovered = int(self.sistema_pesaje.get_recovered_count() or 0)

            self.data_queue.put({'type': 'STATUS', 'payload': connected})
            if connected:
                self.data_queue.put({'type': 'LOG', 'payload': f"Reconectado com sucesso em {com_port}"})
                self.data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'success', 'message': 'Reconexão estabelecida'}})
                self.acquisition_paused = False
                self.modbus_net_window.clear()
                self.diag_samples_budget = 6
                self.diag_last_log_ts = 0.0
                self._start_modbus_if_needed()
            else:
                if recovered > 0:
                    expected = 0
                    nodos = self._get_active_nodos()
                    if nodos:
                        expected = len(nodos)
                    self.data_queue.put({'type': 'LOG', 'payload': f"Conexão parcial após aplicar configuração: {recovered}/{expected} nós"})
                    self.data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'partial', 'message': f'Conexão parcial: {recovered}/{expected} nós', 'recovered': recovered, 'expected': expected}})
                else:
                    self.data_queue.put({'type': 'LOG', 'payload': f"Falha ao reconectar em {com_port}"})
                    self.data_queue.put({'type': 'CONNECTION_PROGRESS', 'payload': {'status': 'failed', 'message': 'Falha ao reconectar'}})
        except Exception as e:
            self.data_queue.put({'type': 'LOG', 'payload': f"Erro durante reconexão: {e}"})
        finally:
            if hasattr(self.sistema_pesaje, 'set_progress_callback'):
                try:
                    self.sistema_pesaje.set_progress_callback(None)
                except Exception:
                    pass
            self.connection_in_progress.clear()

    def _handle_apply_config(self, payload: Dict[str, Any]) -> None:
        """Maneja la actualización de configuración en caliente."""
        new_port = payload.get('serial_port')
        new_nodes = payload.get('nodes')
        new_transmissao = payload.get('transmissao')

        # Fallback: si no viene puerto, usar el com_port del primer nodo
        if not new_port and new_nodes:
            try:
                first_node = next(iter(new_nodes.values()), {})
                new_port = first_node.get('com_port', '')
            except Exception:
                pass

        with self.state_lock:
            if new_port:
                self.active_com = new_port
                self.data_queue.put({'type': 'LOG', 'payload': f"Porta serial atualizada para {self.active_com}"})
            if new_nodes:
                self.active_nodos = new_nodes
                try:
                    self.procesador.update_config(self.active_nodos)
                    self.data_queue.put({'type': 'LOG', 'payload': "Configuração do processador atualizada."})
                except Exception as e:
                    self.data_queue.put({'type': 'LOG', 'payload': f"Erro ao atualizar processador: {e}"})

                if hasattr(self.sistema_pesaje, 'update_nodes_config'):
                    try:
                        self.sistema_pesaje.update_nodes_config(self.active_nodos)
                        self.data_queue.put({'type': 'LOG', 'payload': "Configuração do driver atualizada."})
                    except Exception as e:
                        self.data_queue.put({'type': 'LOG', 'payload': f"Erro ao atualizar driver: {e}"})

                self.data_queue.put({'type': 'LOG', 'payload': f"Mapeamento de nós atualizado ({len(self.active_nodos)} nós)"})

                # Actualizar data_source_key para Modbus
                try:
                    cfg_c1 = self.active_nodos.get('celda_1', {})
                    node_id = cfg_c1.get('id') if isinstance(cfg_c1, dict) else None
                    ch_load = cfg_c1.get('ch_load') or cfg_c1.get('ch') if isinstance(cfg_c1, dict) else None
                    if node_id is not None:
                        self.modbus_params['data_source_key'] = f"{node_id}:{ch_load or 'ch1'}"
                except Exception:
                    pass

        if isinstance(new_transmissao, dict):
            with self.state_lock:
                old_modbus_conf = {
                    'serial_port': str(self.modbus_params.get('serial_port') or '').strip(),
                    'baudrate': self.modbus_params.get('baudrate'),
                    'parity': self.modbus_params.get('parity'),
                    'stopbits': self.modbus_params.get('stopbits'),
                    'bytesize': self.modbus_params.get('bytesize'),
                    'timeout': self.modbus_params.get('timeout'),
                    'enabled': bool(self.modbus_params.get('enabled', True)),
                }
                
                porta_conf = new_transmissao.get('porta')
                if isinstance(porta_conf, str) and porta_conf.strip():
                    self.modbus_params['serial_port'] = porta_conf.strip()
                elif 'porta' in new_transmissao:
                    self.modbus_params['serial_port'] = None

                if 'enabled' in new_transmissao:
                    self.modbus_params['enabled'] = bool(new_transmissao.get('enabled'))
                else:
                    self.modbus_params['enabled'] = bool(self.modbus_params.get('enabled', True) and self.modbus_params.get('serial_port'))

                if 'swap_words' in new_transmissao:
                    self.modbus_params['swap_words'] = bool(new_transmissao.get('swap_words'))

                try:
                    self.modbus_params['baudrate'] = int(new_transmissao.get('velocidade', self.modbus_params.get('baudrate', 3000000)))
                except Exception:
                    pass

                p = new_transmissao.get('paridade', self.modbus_params.get('parity', 'Nenhuma'))
                if isinstance(p, str):
                    mp = p.lower()
                    if 'par' in mp and 'impar' not in mp:
                        self.modbus_params['parity'] = 'E'
                    elif 'impar' in mp or 'ímpar' in mp:
                        self.modbus_params['parity'] = 'O'
                    else:
                        self.modbus_params['parity'] = 'N'

                try:
                    self.modbus_params['stopbits'] = int(new_transmissao.get('stopbits', self.modbus_params.get('stopbits', 1)))
                except Exception:
                    pass

                try:
                    self.modbus_params['bytesize'] = int(new_transmissao.get('bytesize', self.modbus_params.get('bytesize', 8)))
                except Exception:
                    pass

                try:
                    self.modbus_params['timeout'] = float(new_transmissao.get('timeout', self.modbus_params.get('timeout', 0.05)))
                except Exception:
                    pass

                new_modbus_conf = {
                    'serial_port': str(self.modbus_params.get('serial_port') or '').strip(),
                    'baudrate': self.modbus_params.get('baudrate'),
                    'parity': self.modbus_params.get('parity'),
                    'stopbits': self.modbus_params.get('stopbits'),
                    'bytesize': self.modbus_params.get('bytesize'),
                    'timeout': self.modbus_params.get('timeout'),
                    'enabled': bool(self.modbus_params.get('enabled', True)),
                }

            self.modbus_waiting_config_change = False
            self.modbus_last_not_started_reason = None
            self.modbus_start_ts = None
            self.modbus_fail_count = 0
            modbus_conf_changed = (old_modbus_conf != new_modbus_conf)

            with self.modbus_state_lock:
                if self.modbus_server is not None and (modbus_conf_changed or not new_modbus_conf.get('enabled', True)):
                    try:
                        self.modbus_server.stop()
                    except Exception:
                        pass
                    self.modbus_server = None
                    if self.last_modbus_status != 'idle':
                        self.data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'idle'})
                        self.last_modbus_status = 'idle'
            
            self.data_queue.put({'type': 'LOG', 'payload': "Configuração de transmissão Modbus atualizada."})

        # Reconectar si ya estábamos conectados
        was_connected = False
        try:
            was_connected = bool(self.sistema_pesaje.esta_conectado())
        except Exception:
            pass

        if was_connected:
            if not self.connection_in_progress.is_set():
                self.connection_in_progress.set()
                t = threading.Thread(target=self._do_reconnect, daemon=True)
                t.start()
        else:
            self.data_queue.put({'type': 'LOG', 'payload': "Configuração salva. Reconexão automática ignorada (sistema desconectado)."})

    def _process_commands(self) -> None:
        """Consume todos los comandos de command_queue."""
        try:
            while True:
                cmd_msg = self.command_queue.get_nowait()
                cmd = cmd_msg['cmd']

                if cmd in ('CONNECT', 'CONNECT_WITH_PROGRESS'):
                    if not self.connection_in_progress.is_set():
                        self.connection_in_progress.set()
                        t = threading.Thread(target=self._do_connect, daemon=True)
                        t.start()

                elif cmd == 'CANCEL_CONNECT':
                    self.cancel_connect_requested.set()
                    self.data_queue.put({'type': 'LOG', 'payload': 'Cancelamento solicitado. Aguardando término da conexão...'})

                elif cmd == 'DISCONNECT':
                    try:
                        self.sistema_pesaje.desconectar()
                    except Exception:
                        pass
                    self.data_queue.put({'type': 'STATUS', 'payload': False})
                    self.data_queue.put({'type': 'LOG', 'payload': "Sistema desconectado pelo usuário."})
                    self.acquisition_paused = True
                    self.modbus_net_window.clear()
                    self.cancel_connect_requested.clear()
                    
                    with self.modbus_state_lock:
                        if self.modbus_server is not None:
                            try:
                                self.modbus_server.stop()
                            except Exception:
                                pass
                            self.modbus_server = None
                    self.modbus_last_not_started_reason = None
                    self.modbus_start_ts = None
                    self.modbus_fail_count = 0
                    self.modbus_waiting_config_change = False
                    self.last_modbus_status = 'idle'
                    self.data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'idle'})

                elif cmd == 'PAUSE_ACQUISITION':
                    self.acquisition_paused = True
                    self.data_queue.put({'type': 'LOG', 'payload': "Aquisição pausada - aguardando reconexão"})

                elif cmd == 'RESUME_ACQUISITION':
                    self.acquisition_paused = False
                    self.reconnecting_nodes.clear()
                    self.reconnect_attempts.clear()
                    self.data_queue.put({'type': 'LOG', 'payload': "Aquisição retomada"})

                elif cmd == 'MANUAL_RECONNECT':
                    node_id = cmd_msg.get('node_id')
                    self.data_queue.put({'type': 'LOG', 'payload': f"Reconexão manual solicitada para sensor {node_id}"})
                    self.reconnect_attempts[node_id] = 0
                    self.reconnecting_nodes.discard(node_id)
                    self.acquisition_paused = False

                elif cmd == 'TARE':
                    try:
                        new_tare = self.procesador.set_tara()
                        self.data_queue.put({'type': 'DATA', 'payload': {'total_tare': new_tare}})
                        self.data_queue.put({'type': 'LOG', 'payload': "Tara aplicada."})
                    except Exception:
                        self.data_queue.put({'type': 'LOG', 'payload': "Erro aplicando tara."})

                elif cmd == 'RESET_TARE':
                    try:
                        self.procesador.reset_tara()
                        self.data_queue.put({'type': 'DATA', 'payload': {'total_tare': 0.0}})
                        self.data_queue.put({'type': 'LOG', 'payload': "Tara redefinida para 0."})
                    except Exception:
                        self.data_queue.put({'type': 'LOG', 'payload': "Erro reiniciando tara."})

                elif cmd == 'DISCOVER_NODES':
                    if hasattr(self.sistema_pesaje, 'descubrir_nodos'):
                        try:
                            self.data_queue.put({'type': 'LOG', 'payload': "Buscando nós SG-Link via WSDA-USB-200..."})
                            nodos = self.sistema_pesaje.descubrir_nodos(timeout_ms=5000)
                            if nodos:
                                self.data_queue.put({'type': 'DISCOVERED_NODES', 'payload': nodos})
                                total_channels = sum(len(n.get('channels', [])) for n in nodos)
                                self.data_queue.put({'type': 'LOG', 'payload': f"✓ Encontrados {len(nodos)} nodo(s) com {total_channels} canal(is) total"})
                            else:
                                self.data_queue.put({'type': 'DISCOVERED_NODES', 'payload': []})
                                self.data_queue.put({'type': 'LOG', 'payload': "⚠️ Nenhum nó encontrado. Verifique se os nós están transmitindo."})
                        except Exception as e:
                            self.data_queue.put({'type': 'LOG', 'payload': f"Erro buscando nós: {e}"})
                            self.data_queue.put({'type': 'DISCOVERED_NODES', 'payload': []})
                    else:
                        self.data_queue.put({'type': 'LOG', 'payload': "Descoberta não disponível em modo simulação."})
                        self.data_queue.put({'type': 'DISCOVERED_NODES', 'payload': []})

                elif cmd == 'APPLY_CONFIG':
                    payload = cmd_msg.get('payload', {}) or {}
                    self._handle_apply_config(payload)

                elif cmd == 'EXIT':
                    self.running = False
                    try:
                        self.sistema_pesaje.desconectar()
                    except Exception:
                        pass
                    with self.modbus_state_lock:
                        if self.modbus_server is not None:
                            try:
                                self.modbus_server.stop()
                            except Exception:
                                pass
                            self.modbus_server = None
                    self.modbus_last_not_started_reason = None
                    self.modbus_start_ts = None
                    self.modbus_fail_count = 0
                    self.modbus_waiting_config_change = False
                    self.last_modbus_status = 'idle'

        except queue.Empty:
            pass

    def _manage_reconnections(self, datos_procesados: Dict[str, Any]) -> None:
        """Orquesta las reconexiones automáticas de nodos caídos."""
        # Detectar desconexión de sensores
        if datos_procesados.get('disconnect_events'):
            for event in datos_procesados['disconnect_events']:
                node_id = event['node_id']
                nombre = event['nombre']
                
                self.data_queue.put({
                    'type': 'SENSOR_DISCONNECT',
                    'payload': {
                        'node_id': node_id,
                        'nombre': nombre,
                        'timestamp': event['timestamp'],
                        'max_attempts': self.MAX_AUTO_RECONNECT
                    }
                })
                
                if node_id not in self.reconnecting_nodes:
                    self.reconnecting_nodes.add(node_id)
                    self.reconnect_attempts[node_id] = 0
                    self.reconnect_check_counter[node_id] = 0

        # Manejo de reconexión automática
        for node_id in list(self.reconnecting_nodes):
            attempts = self.reconnect_attempts.get(node_id, 0)
            self.reconnect_check_counter[node_id] = self.reconnect_check_counter.get(node_id, 0) + 1
            
            is_connected = False
            for sensor_data in datos_procesados.get('sensores', {}).values():
                if sensor_data.get('id') == node_id and sensor_data.get('connected'):
                    is_connected = True
                    break
            
            if is_connected:
                self.reconnecting_nodes.discard(node_id)
                self.reconnect_attempts.pop(node_id, None)
                self.reconnect_check_counter.pop(node_id, None)
                self.data_queue.put({'type': 'SENSOR_RECONNECTED', 'payload': {'node_id': node_id}})
                self.data_queue.put({'type': 'LOG', 'payload': f"Sensor {node_id} reconectado exitosamente"})
            elif self.reconnect_check_counter[node_id] >= 333:  # Cada ~1 segundo con loop ~3ms
                self.reconnect_check_counter[node_id] = 0
                self.reconnect_attempts[node_id] = attempts + 1
                
                if attempts + 1 < self.MAX_AUTO_RECONNECT:
                    self.data_queue.put({
                        'type': 'RECONNECT_PROGRESS',
                        'payload': {
                            'node_id': node_id,
                            'attempt': attempts + 1,
                            'max_attempts': self.MAX_AUTO_RECONNECT
                        }
                    })
                else:
                    self.reconnecting_nodes.discard(node_id)
                    self.reconnect_check_counter.pop(node_id, None)
                    self.data_queue.put({
                        'type': 'RECONNECT_FAILED',
                        'payload': {
                            'node_id': node_id,
                            'attempts': self.MAX_AUTO_RECONNECT
                        }
                    })
                    self.data_queue.put({'type': 'LOG', 'payload': f"Fallo reconexion de sensor {node_id} despues de {self.MAX_AUTO_RECONNECT} intentos"})

    def _publish_to_modbus(self, raw_data: List[Dict[str, Any]], datos_procesados: Dict[str, Any]) -> None:
        """Envía el valor bruto y los 5 ángulos al servidor Modbus RTU."""
        with self.modbus_state_lock:
            server = self.modbus_server
            start_ts = self.modbus_start_ts
            fail_count = self.modbus_fail_count
            last_status = self.last_modbus_status
        
        if server is None or not raw_data:
            return

        latest_ts = None
        try:
            last_frame = raw_data[-1] if isinstance(raw_data, list) and raw_data else {}
            if isinstance(last_frame, dict):
                latest_ts = last_frame.get('timestamp_ns', None) or last_frame.get('timestamp', None)
        except Exception:
            latest_ts = None

        if latest_ts is None or latest_ts != self.last_modbus_sample_ts:
            total_bruto = float(datos_procesados.get('total_gross', 0.0) or 0.0)
            modbus_value = total_bruto

            with self.state_lock:
                mb_params = self.modbus_params.copy() if self.modbus_params else {}
            
            try:
                src = mb_params.get('data_source_key')
                if src:
                    sensores = datos_procesados.get('sensores', {}) or {}
                    sensor_info = sensores.get('celda_1')
                    if isinstance(sensor_info, dict) and sensor_info.get('key') == src:
                        modbus_value = float(sensor_info.get('bruto', total_bruto))
                    else:
                        for info in sensores.values():
                            if isinstance(info, dict) and info.get('key') == src:
                                modbus_value = float(info.get('bruto', total_bruto))
                                break
            except Exception:
                pass

            if latest_ts is not None:
                self.last_modbus_sample_ts = latest_ts

            swap_words = bool(mb_params.get('swap_words', False))
            
            # Serializar peso bruto de la celda 1 en 2 holding registers (float32)
            regs = self._float_to_float32_registers(modbus_value, swap_words)

            modbus_ok = False
            try:
                modbus_ok = server.push_data(regs)
            except Exception:
                pass

            with self.modbus_state_lock:
                if modbus_ok:
                    self.modbus_fail_count = 0
                    if self.last_modbus_status != 'connected':
                        self.data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'connected'})
                        self.last_modbus_status = 'connected'
                else:
                    in_start_grace = (
                        start_ts is not None
                        and (time.monotonic() - start_ts) < self.modbus_start_grace_s
                    )
                    if not in_start_grace:
                        self.modbus_fail_count = fail_count + 1
                        if self.modbus_fail_count >= self.modbus_fail_threshold:
                            last_mb_error = ""
                            try:
                                if hasattr(server, 'get_last_error'):
                                    last_mb_error = str(server.get_last_error() or "")
                            except Exception:
                                pass

                            err_lower = last_mb_error.lower()
                            port_blocked = (
                                'permissionerror' in err_lower
                                or 'acceso denegado' in err_lower
                                or 'access is denied' in err_lower
                                or 'could not open port' in err_lower
                            )

                            if self.last_modbus_status != 'error':
                                self.data_queue.put({'type': 'MODBUS_STATUS', 'payload': 'error'})
                                self.data_queue.put({'type': 'LOG', 'payload': 'Modbus RTU inativo; aquisição seguirá sem Modbus.'})
                                self.last_modbus_status = 'error'
                            
                            if port_blocked:
                                self.modbus_waiting_config_change = True
                                serial_conf = mb_params.get('serial_port', '')
                                self.data_queue.put({'type': 'LOG', 'payload': f"Modbus RTU em espera: porta {serial_conf} ocupada/sem acceso. Altere em Configuração para tentar nuevamente."})
                            
                            try:
                                server.stop()
                            except Exception:
                                pass
                            self.modbus_server = None
                            self.modbus_start_ts = None
                            self.modbus_fail_count = 0

    def _main_loop(self) -> None:
        """Bucle de ejecución principal del hilo secundario."""
        last_loop_time = time.perf_counter()

        while self.running:
            # Iniciar Modbus RTU automáticamente si está conectado y no pausado
            try:
                is_connected = bool(self.sistema_pesaje.esta_conectado())
            except Exception:
                is_connected = False

            with self.modbus_state_lock:
                m_server = self.modbus_server
            
            if m_server is None and is_connected and not self.acquisition_paused:
                now_modbus = time.monotonic()
                if (now_modbus - self.last_modbus_retry_ts) >= self.modbus_retry_interval_s:
                    self.last_modbus_retry_ts = now_modbus
                    self._start_modbus_if_needed()

            # 1. Procesar Comandos
            self._process_commands()

            # 2. Adquisición de Datos
            try:
                is_connected = bool(self.sistema_pesaje.esta_conectado())
            except Exception:
                is_connected = False

            if is_connected and not self.acquisition_paused:
                try:
                    raw_data = self.sistema_pesaje.obtener_datos()
                    datos_procesados = self.procesador.procesar(raw_data)

                    if 'logs' in datos_procesados:
                        for log_msg in datos_procesados['logs']:
                            self.data_queue.put({'type': 'LOG', 'payload': log_msg})

                    # Guardar último snapshot de ángulos
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
                            self.last_angles = cleaned
                    except Exception:
                        pass

                    # Gestionar reconexión de nodos
                    self._manage_reconnections(datos_procesados)

                    # Enviar datos a la GUI con filtrado/keepalive
                    now_ts = time.monotonic()
                    latest_sample_ts = None
                    try:
                        last_frame = raw_data[-1] if isinstance(raw_data, list) and raw_data else {}
                        if isinstance(last_frame, dict):
                            latest_sample_ts = last_frame.get('timestamp_ns', None) or last_frame.get('timestamp', None)
                    except Exception:
                        latest_sample_ts = None

                    has_new_sample = latest_sample_ts is not None and latest_sample_ts != self.last_gui_sample_ts
                    periodic_keepalive = (now_ts - self.last_gui_publish_ts) >= self.GUI_KEEPALIVE_S
                    rate_ok = (now_ts - self.last_gui_publish_ts) >= self.GUI_PUBLISH_INTERVAL_S

                    if (has_new_sample and rate_ok) or periodic_keepalive:
                        self.data_queue.put({'type': 'DATA', 'payload': datos_procesados})
                        self.last_gui_publish_ts = now_ts
                        if has_new_sample:
                            self.last_gui_sample_ts = latest_sample_ts

                        # Logging diagnóstico (primeras muestras)
                        try:
                            if has_new_sample and self.diag_samples_budget > 0:
                                now_diag = time.monotonic()
                                if (now_diag - self.diag_last_log_ts) >= 0.20:
                                    total_val = float(datos_procesados.get('total', 0.0) or 0.0)
                                    total_raw = float(datos_procesados.get('total_raw', 0.0) or 0.0)
                                    sensores = datos_procesados.get('sensores', {}) or {}
                                    connected_count = sum(1 for info in sensores.values() if isinstance(info, dict) and info.get('connected', False))
                                    self.data_queue.put({
                                        'type': 'LOG',
                                        'payload': f"[DIAG] sample ts={latest_sample_ts} total={total_val:.3f}kg raw={total_raw:.3f} sensores_on={connected_count}/{len(sensores)}"
                                    })
                                    self.diag_samples_budget -= 1
                                    self.diag_last_log_ts = now_diag
                        except Exception:
                            pass

                    # Empujar datos al servidor Modbus
                    self._publish_to_modbus(raw_data, datos_procesados)

                except Exception as e:
                    self.data_queue.put({'type': 'LOG', 'payload': f"Erro na aquisicao: {e}"})

            # 3. Pausa dinámica
            try:
                is_connected = bool(self.sistema_pesaje.esta_conectado())
            except Exception:
                is_connected = False

            if is_connected and not self.acquisition_paused:
                target_interval = float(self.RUNTIME_TUNING.get('backend_sleep_connected_s', 0.003))
                now = time.perf_counter()
                elapsed = now - last_loop_time
                sleep_s = target_interval - elapsed
                if sleep_s > 0:
                    time.sleep(sleep_s)
                    last_loop_time = now + sleep_s
                else:
                    last_loop_time = now
            else:
                time.sleep(float(self.RUNTIME_TUNING.get('backend_sleep_idle_s', 0.05)))
                last_loop_time = time.perf_counter()
