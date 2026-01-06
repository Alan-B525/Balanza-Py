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
# WSDA-USB-200 Gateway se conecta via USB (porta COM virtual)
PUERTO_COM = "COM3"  # Ajustar conforme a porta do WSDA-USB-200
BAUDRATE = 921600

# =============================================================================
# CONFIGURAÇÃO DE CELDAS DE CARGA
# =============================================================================
# Estructura: 2 nodos SG-Link-200, cada uno con 2 canales (ch1, ch2)
# Total: 4 celdas de carga
#
# Nodo 1: ch1 = Celda 1, ch2 = Celda 2
# Nodo 2: ch1 = Celda 3, ch2 = Celda 4
#
# El usuario puede renumerar las celdas según su disposición física

NODOS_CONFIG = {
    # Celda 1 - Nodo 1, Canal 1
    "celda_1": {"id": 11111, "ch": "ch1", "nombre": "Celda 1", "posicion": "1"},
    # Celda 2 - Nodo 1, Canal 2  
    "celda_2": {"id": 11111, "ch": "ch2", "nombre": "Celda 2", "posicion": "2"},
    # Celda 3 - Nodo 2, Canal 1
    "celda_3": {"id": 22222, "ch": "ch1", "nombre": "Celda 3", "posicion": "3"},
    # Celda 4 - Nodo 2, Canal 2
    "celda_4": {"id": 22222, "ch": "ch2", "nombre": "Celda 4", "posicion": "4"},
}

# Lista de canales activos por nodo (para referencia)
# Cada nodo SG-Link-200 puede tener hasta 4 canales diferenciales
CANALES_POR_NODO = ["ch1", "ch2", "ch3", "ch4"]

# Configuração de robustez (para modo REAL)
RECONNECT_ATTEMPTS = 3
NODE_TIMEOUT_SECONDS = 5.0
DATA_TIMEOUT_MS = 100

# Configuração da Interface
APP_TITLE = "Sistema de Pesagem Industrial (Balanza-Py)"
APP_SIZE = "1280x800"
THEME_NAME = "litera"
