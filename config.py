# -*- coding: utf-8 -*-
import sys
import os
import platform

# =============================================================================
# 1. GESTIÓN DE RUTAS Y PERMISOS (CRÍTICO PARA EL EXE)
# =============================================================================

APP_NAME = "SistemaDePesagem"  # Nombre de la carpeta en AppData

def get_base_dir():
    """
    Directorio base de la aplicación (SOLO LECTURA).
    Aquí están los scripts, imágenes y librerías (MSCL).
    """
    if getattr(sys, 'frozen', False):
        # Si es un EXE (PyInstaller)
        return os.path.dirname(sys.executable)
    # Si es modo desarrollo (Python script)
    return os.path.dirname(os.path.abspath(__file__))

def get_writable_dir():
    """
    Directorio de datos del usuario (LECTURA Y ESCRITURA).
    Aquí guardaremos logs, json y configuraciones.
    """
    if getattr(sys, 'frozen', False):
        # MODO EXE: Usamos %APPDATA% en Windows
        # Ruta típica: C:\Users\Usuario\AppData\Roaming\SistemaDePesagem
        if platform.system() == "Windows":
            base_path = os.environ.get('APPDATA')
        else:
            base_path = os.path.join(os.path.expanduser("~"), ".local", "share")
        
        path = os.path.join(base_path, APP_NAME)
    else:
        # MODO DESARROLLO: Usamos la carpeta del proyecto
        path = os.path.dirname(os.path.abspath(__file__))
    
    # ¡IMPORTANTE! Crear el directorio inmediatamente si no existe
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        print(f"[ERROR CRÍTICO] No se pudo crear directorio de datos: {e}")
    
    return path

# --- DEFINICIÓN DE RUTAS EXPORTABLES ---

BASE_DIR = get_base_dir()      # Usar para cargar DLLs, Iconos
DATA_DIR = get_writable_dir()  # Usar para guardar JSONs

# Rutas específicas para archivos
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
CALIBRATIONS_DIR = os.path.join(DATA_DIR, "calibrations")

# Asegurar que la subcarpeta 'calibrations' exista
os.makedirs(CALIBRATIONS_DIR, exist_ok=True)

print(f"[CONFIG] Directorio de Datos (Escritura): {DATA_DIR}")
print(f"[CONFIG] Directorio de Calibraciones: {CALIBRATIONS_DIR}")

# =============================================================================
# 2. CONFIGURACIÓN DE LIBRERÍA MSCL
# =============================================================================

# La librería MSCL suele estar junto al ejecutable o en la carpeta del script
MSCL_PATH = os.path.join(BASE_DIR, "MSCL", "x64", "Release")

if os.path.exists(MSCL_PATH) and MSCL_PATH not in sys.path:
    sys.path.insert(0, MSCL_PATH)
    print(f"[CONFIG] MSCL path cargado: {MSCL_PATH}")
else:
    print(f"[WARNING] No se encontró MSCL en: {MSCL_PATH}")

# =============================================================================
# 3. CONSTANTES DEL NEGOCIO
# =============================================================================

MODO_EJECUCION = "REAL"
PUERTO_COM = "COM3"
BAUDRATE = 921600

NODOS_CONFIG = {
    "celda_1": {"id": 0, "ch": "ch1", "nombre": "Célula 1", "posicion": "1", "serial": ""},
    "celda_2": {"id": 0, "ch": "ch2", "nombre": "Célula 2", "posicion": "2", "serial": ""},
    "celda_3": {"id": 0, "ch": "ch1", "nombre": "Célula 3", "posicion": "3", "serial": ""},
    "celda_4": {"id": 0, "ch": "ch2", "nombre": "Célula 4", "posicion": "4", "serial": ""},
}

RECONNECT_ATTEMPTS = 3
NODE_TIMEOUT_SECONDS = 5.0
DATA_TIMEOUT_MS = 100

# Especificaciones del Display
APP_TITLE = "Sistema de Pesagem Industrial"
APP_SIZE = "1280x800"
THEME_NAME = "litera"

# Especificaciones del Sensor
SENSOR_MV_PER_V = 1.2      
SENSOR_MAX_VOLTAGE = 2.5   
DISPLAY_DECIMALS = 0