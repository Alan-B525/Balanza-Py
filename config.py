# Configuración del Sistema de Pesaje

# Modo de ejecución: "MOCK" (Simulación) o "REAL" (Hardware MSCL)
MODO_EJECUCION = "MOCK" 

# Configuración Serial (Solo para modo REAL)
PUERTO_COM = "COM3" # Ajustar según el puerto real
BAUDRATE = 921600

# Mapeo de Nodos Físicos a Posiciones Lógicas
# ID: Identificador único del nodo SG-Link-200
# CH: Canal de datos (usualmente "ch1" para strain gauge)
NODOS_CONFIG = {
    "celda_sup_izq": {"id": 11111, "ch": "ch1"},
    "celda_sup_der": {"id": 22222, "ch": "ch1"},
    "celda_inf_izq": {"id": 67890, "ch": "ch1"},
    "celda_inf_der": {"id": 12345, "ch": "ch1"},
}

# Configuración de la Interfaz
APP_TITLE = "Sistema de Pesaje Industrial (Balanza-Py)"
APP_SIZE = "1280x800"
THEME_NAME = "litera"
