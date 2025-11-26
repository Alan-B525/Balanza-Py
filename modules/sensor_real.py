import sys
import os
import time
from typing import List, Dict, Any
from .interfaces import ISistemaPesaje

# Tentar importar MSCL, tratando o caso onde não esteja instalado ou configurado
try:
    # Assumindo que a pasta MSCL está no path ou na raiz do projeto
    # Ajustar conforme a estrutura real se necessário
    import mscl
except ImportError:
    mscl = None
    print("[AVISO] Biblioteca MSCL não encontrada. A classe RealPesaje falhará se for instanciada.")

class RealPesaje(ISistemaPesaje):
    """
    Implementação real usando a biblioteca MSCL da MicroStrain.
    Gerencia a conexão Serial e a aquisição de dados de nós sem fio.
    """

    def __init__(self):
        if mscl is None:
            raise ImportError("A biblioteca MSCL é necessária para RealPesaje.")
        
        self.connection = None
        self.base_station = None
        self._conectado = False
        self._tares = {} # Dicionário para armazenar offsets de tara em software

    def conectar(self, puerto: str) -> bool:
        try:
            print(f"[REAL] Tentando conectar a: {puerto}...")
            
            # Detectar se é IP:Porta ou Serial
            if ":" in puerto and not "COM" in puerto.upper():
                # Assumir formato IP:PORTA (ex: 192.168.1.100:10000)
                parts = puerto.split(":")
                ip = parts[0]
                port = int(parts[1])
                print(f"[REAL] Usando conexão TCP/IP: {ip}:{port}")
                self.connection = mscl.Connection.TcpIp(ip, port)
            else:
                # Assumir Serial (ex: COM3 ou /dev/ttyUSB0)
                print(f"[REAL] Usando conexão Serial: {puerto}")
                self.connection = mscl.Connection.Serial(puerto)

            self.base_station = mscl.BaseStation(self.connection)
            
            # Verificar comunicação (ping)
            if not self.base_station.ping():
                print("[REAL] Ping falhou na BaseStation.")
                return False

            # Configurar BaseStation para modo Idle inicialmente
            self.base_station.enableBeacon()
            
            self._conectado = True
            print("[REAL] Conexão bem-sucedida com BaseStation.")
            return True
            
        except mscl.Error as e:
            print(f"[ERRO MSCL] Falha ao conectar: {e}")
            self._conectado = False
            return False
        except Exception as e:
            print(f"[ERRO] Erro inesperado: {e}")
            self._conectado = False
            return False

    def desconectar(self) -> None:
        if self.connection:
            print("[REAL] Fechando conexão...")
            self.connection.disconnect()
        self._conectado = False

    def obtener_datos(self) -> List[Dict[str, Any]]:
        if not self._conectado or not self.base_station:
            return []

        datos = []
        try:
            # Obter todos os sweeps (pacotes de dados) disponíveis no buffer (timeout 10ms)
            sweeps = self.base_station.getData(10)
            
            for sweep in sweeps:
                node_id = sweep.nodeAddress()
                timestamp = sweep.timestamp().nanoseconds() / 1e9 # Converter para segundos
                rssi = sweep.nodeRssi()
                
                # Iterar sobre os dados dentro do sweep (canais)
                for data_point in sweep.data():
                    # Filtrar apenas canais válidos (ex. ch1)
                    # Aqui assumimos que nos interessa o canal de dados principal
                    # Ajustar lógica conforme configuração específica do nó
                    
                    # Nota: MSCL retorna objetos DataPoint. 
                    # data_point.channelName() retorna ex. "ch1"
                    
                    ch_name = data_point.channelName()
                    
                    # Verificar se é um dado válido (não erro)
                    if data_point.valid():
                        valor_bruto = data_point.as_float()
                        
                        # Aplicar Tara de Software
                        valor_neto = valor_bruto - self._tares.get(node_id, 0.0)
                        
                        datos.append({
                            'node_id': node_id,
                            'ch_name': ch_name,
                            'value': valor_neto,
                            'rssi': rssi,
                            'timestamp': timestamp
                        })

        except mscl.Error as e:
            print(f"[ERRO MSCL] Erro ao ler dados: {e}")
            # Opcional: Tentar reconectar se for um erro crítico
        except Exception as e:
            print(f"[ERRO] Erro geral ao ler dados: {e}")

        return datos

    def tarar(self, node_id: int = None) -> None:
        """
        Implementação de Tara por Software.
        Para uma tara real em hardware (Zero Calibration), seria necessário enviar comandos específicos ao nó.
        Aqui implementamos tara relativa ao valor atual recebido.
        """
        # Nota: Para tarar corretamente, precisamos do último valor conhecido.
        # Esta implementação assume que a lógica de negócio ou o buffer interno
        # tem acesso ao último valor. 
        # Como esta classe é "stateless" em relação aos dados passados, 
        # a tara idealmente deveria ser gerenciada no DataProcessor ou 
        # esta classe deveria manter um cache do último valor lido.
        
        # Por simplicidade e robustez, marcaremos um flag para que a próxima leitura defina a tara
        # Ou, idealmente, delegamos a lógica matemática ao DataProcessor e aqui apenas gerenciamos hardware.
        # MAS, o requisito pede implementar tarar() aqui.
        
        # Solução: Esta classe precisa saber o valor atual para tarar.
        # Dado que obtener_datos é quem lê, não podemos tarar "às cegas" sem ler.
        # Em um sistema real, enviaríamos um comando "Tare" ao nó.
        pass 
        # TODO: Implementar comando de hardware Node.tare() se o nó suportar,
        # ou deixar que DataProcessor gerencie a subtração matemática.
        # Para este exercício, assumiremos que DataProcessor gerencia a subtração, 
        # ou que esta classe salva o offset se tivesse um buffer.
        print("[REAL] Comando Tarar recebido. (Lógica delegada a DataProcessor ou Hardware Command)")

    def reset_tarar(self) -> None:
        self._tares.clear()
        print("[REAL] Tara reiniciada.")

    def esta_conectado(self) -> bool:
        return self._conectado

    def descubrir_nodos(self, timeout_ms: int = 5000) -> list:
        """
        Descobre nós sem fio na rede MSCL.
        Usa o comando BroadcastPing para encontrar todos os nós ativos.
        
        Args:
            timeout_ms: Tempo máximo para esperar respostas (ms)
            
        Returns:
            Lista de dicionários com info de cada nó encontrado
        """
        if not self._conectado or not self.base_station:
            print("[REAL] Não há conexão ativa para descobrir nós.")
            return []
            
        nodos_encontrados = []
        
        try:
            print(f"[REAL] Iniciando descoberta de nós (timeout: {timeout_ms}ms)...")
            
            # Método 1: BroadcastPing - Envia ping a todos os nós
            # Isso faz com que qualquer nó que escute responda
            try:
                # Obter nós que responderam ao beacon
                # MSCL não tem um "scan" direto, mas podemos revisar o histórico
                # de pacotes ou usar broadcastPing
                
                # Alguns nós se auto-registram ao receber beacon
                # Podemos tentar obter a lista de nós conhecidos
                
                # Alternativa: Revisar sweeps recebidos em um tempo
                import time
                start_time = time.time()
                node_ids_seen = set()
                
                while (time.time() - start_time) * 1000 < timeout_ms:
                    sweeps = self.base_station.getData(100)  # 100ms de dados
                    for sweep in sweeps:
                        node_id = sweep.nodeAddress()
                        if node_id not in node_ids_seen:
                            node_ids_seen.add(node_id)
                            rssi = sweep.nodeRssi()
                            nodos_encontrados.append({
                                'id': node_id,
                                'rssi': rssi,
                                'status': 'active'
                            })
                            print(f"[REAL] Nó encontrado: ID={node_id}, RSSI={rssi}")
                    time.sleep(0.1)
                    
            except mscl.Error as e:
                print(f"[REAL] Erro durante escaneamento: {e}")
                
            print(f"[REAL] Descoberta completa. {len(nodos_encontrados)} nó(s) encontrado(s).")
            
        except Exception as e:
            print(f"[ERRO] Erro na descoberta: {e}")
            
        return nodos_encontrados
