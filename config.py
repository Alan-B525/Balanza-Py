# Configuração do Sistema de Pesagem
import sys
import os

# Configurar path do MSCL antes de qualquer import
# O MSCL está em: D:\Carpeta Becario 19\Nueva carpeta (2)\Balanza\MSCL\x64\Release
_MSCL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MSCL", "x64", "Release")
if os.path.exists(_MSCL_PATH) and _MSCL_PATH not in sys.path:
    sys.path.insert(0, _MSCL_PATH)
    print(f"[CONFIG] MSCL path adicionado: {_MSCL_PATH}")

# Modo de execução - Versão de Produção
# Apenas modo REAL disponível
MODO_EJECUCION = "REAL" 

# Configuração Serial (Somente para modo REAL)
PUERTO_COM = "COM3" # Ajustar conforme a porta real
BAUDRATE = 921600

# Mapeamento de Nós Físicos para Posições Lógicas
# ID: Identificador único do nó SG-Link-200
# CH: Canal de dados (geralmente "ch1" para strain gauge)
NODOS_CONFIG = {
    "celda_sup_izq": {"id": 11111, "ch": "ch1"},
    "celda_sup_der": {"id": 22222, "ch": "ch1"},
    "celda_inf_izq": {"id": 67890, "ch": "ch1"},
    "celda_inf_der": {"id": 12345, "ch": "ch1"},
}

# Configuração de robustez (para modo REAL)
RECONNECT_ATTEMPTS = 3
NODE_TIMEOUT_SECONDS = 5.0
DATA_TIMEOUT_MS = 100

# Configuração da Interface
APP_TITLE = "Sistema de Pesagem Industrial (Balanza-Py)"
APP_SIZE = "1280x800"
THEME_NAME = "litera"
