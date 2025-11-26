# Configuração do Sistema de Pesagem

# Modo de execução: "MOCK" (Simulação) ou "REAL" (Hardware MSCL)
MODO_EJECUCION = "MOCK" 

# Configuração Serial (Apenas para modo REAL)
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

# Configuração da Interface
APP_TITLE = "Sistema de Pesagem Industrial (Balança-Py)"
APP_SIZE = "1280x800"
THEME_NAME = "litera"
