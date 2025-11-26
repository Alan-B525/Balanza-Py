"""
Implementação Real usando a biblioteca MSCL da MicroStrain.
Versão robusta com:
- Reconexão automática
- Tratamento de erros avançado
- Cache de último valor conhecido
- Validação de dados
- Logging detalhado
- Suporte a TCP/IP e Serial
"""

import sys
import os
import time
import threading
from typing import List, Dict, Any, Optional
from collections import deque
from enum import Enum
from .interfaces import ISistemaPesaje

# Importar MSCL
try:
    import mscl
    MSCL_AVAILABLE = True
except ImportError:
    mscl = None
    MSCL_AVAILABLE = False
    print("[AVISO] Biblioteca MSCL não encontrada. RealPesaje requer MSCL.")


class ConnectionState(Enum):
    """Estados possíveis da conexão."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class NodeStatus:
    """Status de um nó individual."""
    def __init__(self, node_id: int):
        self.node_id = node_id
        self.last_seen: float = 0.0
        self.last_value: float = 0.0
        self.last_rssi: int = 0
        self.packet_count: int = 0
        self.error_count: int = 0
        self.is_online: bool = False
        self.channel: str = "ch1"


class RealPesaje(ISistemaPesaje):
    """
    Implementação robusta usando MSCL para hardware MicroStrain real.
    
    Características:
    - Suporte a conexão TCP/IP e Serial
    - Reconexão automática em caso de falha
    - Cache de últimos valores para tolerância a perdas
    - Validação de dados recebidos
    - Estatísticas de conexão por nó
    - Thread-safe
    """

    # Constantes de configuração
    DEFAULT_TIMEOUT_MS = 100  # Timeout para getData()
    RECONNECT_DELAY_S = 2.0   # Delay entre tentativas de reconexão
    MAX_RECONNECT_ATTEMPTS = 3
    NODE_TIMEOUT_S = 5.0      # Tempo para considerar nó offline
    DATA_VALIDATION_MIN = -1000.0  # Valor mínimo aceitável
    DATA_VALIDATION_MAX = 10000.0  # Valor máximo aceitável

    def __init__(self, nodos_config: Optional[Dict] = None):
        """
        Inicializa o sistema de pesagem real.
        
        Args:
            nodos_config: Configuração dos nós esperados (opcional)
        """
        if not MSCL_AVAILABLE:
            raise ImportError("A biblioteca MSCL é necessária para RealPesaje. "
                            "Certifique-se de que está no PATH do sistema.")
        
        self.nodos_config = nodos_config or {}
        
        # Objetos MSCL
        self.connection: Optional[mscl.Connection] = None
        self.base_station: Optional[mscl.BaseStation] = None
        
        # Estado
        self._state = ConnectionState.DISCONNECTED
        self._state_lock = threading.Lock()
        
        # Taras por software
        self._tares: Dict[int, float] = {}
        
        # Status dos nós
        self._node_status: Dict[int, NodeStatus] = {}
        
        # Cache de últimos valores (útil para interpolação em caso de perda)
        self._last_values: Dict[int, deque] = {}
        self._cache_size = 5
        
        # Estatísticas
        self._stats = {
            'total_packets': 0,
            'valid_packets': 0,
            'invalid_packets': 0,
            'reconnect_count': 0,
            'last_error': None
        }
        
        # Configuração de conexão atual
        self._current_connection_string: str = ""
        
        # Inicializar estruturas para nós configurados
        self._initialize_node_structures()

    def _initialize_node_structures(self) -> None:
        """Inicializa estruturas de dados para nós configurados."""
        for key, cfg in self.nodos_config.items():
            node_id = cfg['id']
            self._node_status[node_id] = NodeStatus(node_id)
            self._node_status[node_id].channel = cfg.get('ch', 'ch1')
            self._tares[node_id] = 0.0
            self._last_values[node_id] = deque(maxlen=self._cache_size)

    def _log(self, level: str, message: str) -> None:
        """Log interno com timestamp."""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] [MSCL-REAL] {message}")

    def _set_state(self, new_state: ConnectionState) -> None:
        """Atualiza estado de forma thread-safe."""
        with self._state_lock:
            old_state = self._state
            self._state = new_state
            if old_state != new_state:
                self._log("INFO", f"Estado: {old_state.value} → {new_state.value}")

    @property
    def state(self) -> ConnectionState:
        """Retorna estado atual da conexão."""
        with self._state_lock:
            return self._state

    def conectar(self, puerto: str) -> bool:
        """
        Estabelece conexão com a BaseStation.
        
        Args:
            puerto: String de conexão. Formatos aceitos:
                   - "COM3" ou "/dev/ttyUSB0" para Serial
                   - "192.168.1.100:5000" para TCP/IP
                   
        Returns:
            True se conexão bem-sucedida, False caso contrário
        """
        self._current_connection_string = puerto
        self._set_state(ConnectionState.CONNECTING)
        
        try:
            self._log("INFO", f"Iniciando conexão: {puerto}")
            
            # Determinar tipo de conexão
            if self._is_tcp_connection(puerto):
                success = self._connect_tcp(puerto)
            else:
                success = self._connect_serial(puerto)
            
            if success:
                self._set_state(ConnectionState.CONNECTED)
                return True
            else:
                self._set_state(ConnectionState.ERROR)
                return False
                
        except mscl.Error as e:
            self._log("ERROR", f"Erro MSCL ao conectar: {e}")
            self._stats['last_error'] = str(e)
            self._set_state(ConnectionState.ERROR)
            return False
        except Exception as e:
            self._log("ERROR", f"Erro inesperado ao conectar: {e}")
            self._stats['last_error'] = str(e)
            self._set_state(ConnectionState.ERROR)
            return False

    def _is_tcp_connection(self, puerto: str) -> bool:
        """Determina se a string de conexão é TCP/IP."""
        return ":" in puerto and "COM" not in puerto.upper()

    def _connect_tcp(self, puerto: str) -> bool:
        """Estabelece conexão TCP/IP."""
        try:
            parts = puerto.split(":")
            ip = parts[0].strip()
            port = int(parts[1].strip())
            
            self._log("INFO", f"Conectando via TCP/IP: {ip}:{port}")
            self.connection = mscl.Connection.TcpIp(ip, port)
            
            return self._initialize_base_station()
            
        except ValueError as e:
            self._log("ERROR", f"Formato de endereço TCP inválido: {e}")
            return False

    def _connect_serial(self, puerto: str) -> bool:
        """Estabelece conexão Serial."""
        try:
            self._log("INFO", f"Conectando via Serial: {puerto}")
            
            # MSCL detecta baud rate automaticamente, mas podemos especificar
            self.connection = mscl.Connection.Serial(puerto)
            
            return self._initialize_base_station()
            
        except Exception as e:
            self._log("ERROR", f"Erro ao conectar Serial: {e}")
            return False

    def _initialize_base_station(self) -> bool:
        """Inicializa e valida a BaseStation."""
        try:
            self.base_station = mscl.BaseStation(self.connection)
            
            # Verificar comunicação
            self._log("INFO", "Enviando ping à BaseStation...")
            if not self.base_station.ping():
                self._log("WARNING", "Ping falhou, mas continuando...")
                # Alguns modelos não respondem ao ping
            
            # Habilitar beacon para sincronização de nós
            try:
                self.base_station.enableBeacon()
                self._log("INFO", "Beacon habilitado.")
            except mscl.Error as e:
                self._log("WARNING", f"Não foi possível habilitar beacon: {e}")
            
            # Limpar buffer de dados antigos
            try:
                self.base_station.getData(50)  # Descartar dados antigos
            except:
                pass
            
            self._log("INFO", "BaseStation inicializada com sucesso!")
            return True
            
        except mscl.Error as e:
            self._log("ERROR", f"Falha ao inicializar BaseStation: {e}")
            return False

    def desconectar(self) -> None:
        """Fecha a conexão de forma segura."""
        self._log("INFO", "Iniciando desconexão...")
        
        try:
            if self.base_station:
                try:
                    self.base_station.disableBeacon()
                except:
                    pass
            
            if self.connection:
                self.connection.disconnect()
                
        except Exception as e:
            self._log("WARNING", f"Erro ao desconectar: {e}")
        finally:
            self.connection = None
            self.base_station = None
            self._set_state(ConnectionState.DISCONNECTED)
            self._log("INFO", "Desconectado.")

    def obtener_datos(self) -> List[Dict[str, Any]]:
        """
        Obtém dados dos nós wireless.
        
        Returns:
            Lista de dicionários com dados de cada nó
        """
        if self.state != ConnectionState.CONNECTED or not self.base_station:
            return []

        datos = []
        current_time = time.time()

        try:
            # Obter sweeps disponíveis
            sweeps = self.base_station.getData(self.DEFAULT_TIMEOUT_MS)
            
            for sweep in sweeps:
                self._stats['total_packets'] += 1
                
                try:
                    processed = self._process_sweep(sweep, current_time)
                    if processed:
                        datos.extend(processed)
                        self._stats['valid_packets'] += 1
                except Exception as e:
                    self._stats['invalid_packets'] += 1
                    self._log("WARNING", f"Erro processando sweep: {e}")

        except mscl.Error_Connection as e:
            self._log("ERROR", f"Erro de conexão: {e}")
            self._handle_connection_error()
        except mscl.Error as e:
            self._log("WARNING", f"Erro MSCL lendo dados: {e}")
        except Exception as e:
            self._log("ERROR", f"Erro inesperado: {e}")

        # Verificar timeout de nós
        self._check_node_timeouts(current_time)

        return datos

    def _process_sweep(self, sweep: 'mscl.DataSweep', current_time: float) -> List[Dict[str, Any]]:
        """Processa um sweep de dados."""
        datos = []
        
        node_id = sweep.nodeAddress()
        rssi = sweep.nodeRssi()
        timestamp = sweep.timestamp().nanoseconds() / 1e9
        
        # Atualizar status do nó
        if node_id not in self._node_status:
            self._node_status[node_id] = NodeStatus(node_id)
            self._last_values[node_id] = deque(maxlen=self._cache_size)
            self._tares[node_id] = 0.0
            self._log("INFO", f"Novo nó detectado: {node_id}")
        
        status = self._node_status[node_id]
        status.last_seen = current_time
        status.last_rssi = rssi
        status.packet_count += 1
        status.is_online = True
        
        # Processar cada ponto de dados no sweep
        for data_point in sweep.data():
            if not data_point.valid():
                status.error_count += 1
                continue
            
            ch_name = data_point.channelName()
            valor_bruto = data_point.as_float()
            
            # Validar dados
            if not self._validate_value(valor_bruto):
                self._log("WARNING", f"Valor inválido do nó {node_id}: {valor_bruto}")
                status.error_count += 1
                continue
            
            # Armazenar em cache
            self._last_values[node_id].append(valor_bruto)
            status.last_value = valor_bruto
            
            # Aplicar tara
            valor_neto = valor_bruto - self._tares.get(node_id, 0.0)
            
            datos.append({
                'node_id': node_id,
                'ch_name': ch_name,
                'value': valor_neto,
                'value_raw': valor_bruto,
                'rssi': rssi,
                'timestamp': timestamp,
                'tick': sweep.tick()
            })
        
        return datos

    def _validate_value(self, value: float) -> bool:
        """Valida se um valor está dentro dos limites aceitáveis."""
        if value is None:
            return False
        if not isinstance(value, (int, float)):
            return False
        if value < self.DATA_VALIDATION_MIN or value > self.DATA_VALIDATION_MAX:
            return False
        return True

    def _check_node_timeouts(self, current_time: float) -> None:
        """Verifica e marca nós que estão em timeout."""
        for node_id, status in self._node_status.items():
            if status.is_online:
                if current_time - status.last_seen > self.NODE_TIMEOUT_S:
                    status.is_online = False
                    self._log("WARNING", f"Nó {node_id} em timeout (sem dados há {self.NODE_TIMEOUT_S}s)")

    def _handle_connection_error(self) -> None:
        """Trata erros de conexão e tenta reconectar."""
        self._set_state(ConnectionState.RECONNECTING)
        self._stats['reconnect_count'] += 1
        
        for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
            self._log("INFO", f"Tentativa de reconexão {attempt + 1}/{self.MAX_RECONNECT_ATTEMPTS}")
            time.sleep(self.RECONNECT_DELAY_S)
            
            try:
                self.desconectar()
                if self.conectar(self._current_connection_string):
                    self._log("INFO", "Reconexão bem-sucedida!")
                    return
            except Exception as e:
                self._log("ERROR", f"Falha na tentativa {attempt + 1}: {e}")
        
        self._log("ERROR", "Todas as tentativas de reconexão falharam.")
        self._set_state(ConnectionState.ERROR)

    def tarar(self, node_id: int = None) -> None:
        """
        Aplica tara (zero) aos nós.
        
        Args:
            node_id: ID específico do nó, ou None para todos
        """
        if node_id is not None:
            if node_id in self._last_values and self._last_values[node_id]:
                avg = sum(self._last_values[node_id]) / len(self._last_values[node_id])
                self._tares[node_id] = avg
                self._log("INFO", f"Tara aplicada ao nó {node_id}: {avg:.4f}")
        else:
            for nid, values in self._last_values.items():
                if values:
                    avg = sum(values) / len(values)
                    self._tares[nid] = avg
                    self._log("INFO", f"Tara aplicada ao nó {nid}: {avg:.4f}")

    def reset_tarar(self) -> None:
        """Reseta todas as taras para zero."""
        self._tares = {nid: 0.0 for nid in self._tares}
        self._log("INFO", "Todas as taras resetadas.")

    def esta_conectado(self) -> bool:
        """Retorna True se conectado."""
        return self.state == ConnectionState.CONNECTED

    def descubrir_nodos(self, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        """
        Descobre nós wireless na rede.
        
        Args:
            timeout_ms: Timeout para descoberta em milissegundos
            
        Returns:
            Lista de nós encontrados com suas informações
        """
        if not self.esta_conectado() or not self.base_station:
            self._log("WARNING", "Sem conexão ativa para descobrir nós.")
            return []

        self._log("INFO", f"Iniciando descoberta de nós (timeout: {timeout_ms}ms)...")
        nodos_encontrados = []
        node_ids_seen = set()
        
        try:
            start_time = time.time()
            
            while (time.time() - start_time) * 1000 < timeout_ms:
                sweeps = self.base_station.getData(200)
                
                for sweep in sweeps:
                    node_id = sweep.nodeAddress()
                    
                    if node_id not in node_ids_seen:
                        node_ids_seen.add(node_id)
                        
                        info = {
                            'id': node_id,
                            'rssi': sweep.nodeRssi(),
                            'status': 'active',
                            'sample_rate': sweep.sampleRate().prettyStr() if hasattr(sweep.sampleRate(), 'prettyStr') else str(sweep.sampleRate())
                        }
                        
                        nodos_encontrados.append(info)
                        self._log("INFO", f"Nó encontrado: ID={node_id}, RSSI={info['rssi']}")
                
                time.sleep(0.1)
                
        except mscl.Error as e:
            self._log("ERROR", f"Erro durante descoberta: {e}")
        except Exception as e:
            self._log("ERROR", f"Erro inesperado: {e}")

        self._log("INFO", f"Descoberta completa: {len(nodos_encontrados)} nó(s) encontrado(s)")
        return nodos_encontrados

    def get_node_status(self, node_id: int) -> Optional[Dict[str, Any]]:
        """Retorna status detalhado de um nó específico."""
        if node_id not in self._node_status:
            return None
        
        status = self._node_status[node_id]
        return {
            'node_id': status.node_id,
            'is_online': status.is_online,
            'last_seen': status.last_seen,
            'last_value': status.last_value,
            'last_rssi': status.last_rssi,
            'packet_count': status.packet_count,
            'error_count': status.error_count,
            'tare': self._tares.get(node_id, 0.0)
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Retorna estatísticas gerais do sistema."""
        return {
            **self._stats,
            'connection_state': self.state.value,
            'nodes_online': sum(1 for s in self._node_status.values() if s.is_online),
            'nodes_total': len(self._node_status)
        }

    def get_last_cached_value(self, node_id: int) -> Optional[float]:
        """
        Retorna último valor em cache para um nó.
        Útil quando há perda temporária de dados.
        """
        if node_id in self._last_values and self._last_values[node_id]:
            return self._last_values[node_id][-1]
        return None
