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
    Directorio base de recursos SOLO LECTURA (imágenes, DLLs, etc).
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller: Carpeta temporal donde se extraen los recursos
        return sys._MEIPASS
    # Desarrollo o EXE: Carpeta del script o ejecutable
    return os.path.dirname(os.path.abspath(__file__))

def get_writable_dir():
    """
    Directorio de datos del usuario (LECTURA Y ESCRITURA).
    Aquí guardaremos logs, json y configuraciones.
    """
    if getattr(sys, 'frozen', False):
        # MODO EXE: SIEMPRE junto al ejecutable
        path = os.path.dirname(sys.executable)
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

BASE_DIR = get_base_dir()      # Usar para recursos SOLO LECTURA (imágenes, DLLs)
DATA_DIR = get_writable_dir()  # Usar para guardar JSONs, settings, calibraciones

# Función para obtener la ruta real de recursos (soporta PyInstaller)
def resource_path(relative_path):
    """
    Devuelve la ruta absoluta al recurso, compatible con PyInstaller (EXE) y desarrollo.
    """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(BASE_DIR, relative_path)

# Rutas específicas para archivos (lectura y escritura JUNTO AL EJECUTABLE o script)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
CALIBRATIONS_DIR = os.path.join(DATA_DIR, "calibrations")

# Asegurar que la subcarpeta 'calibrations' exista
try:
    os.makedirs(CALIBRATIONS_DIR, exist_ok=True)
except Exception as e:
    print(f"[ERROR CRÍTICO] No se pudo crear directorio de calibraciones: {e}")

# Copiar calibraciones por defecto embebidas (si existen en recursos) al directorio de datos
try:
    embedded_calib = resource_path('calibrations')
    # Solo copiar si la carpeta destino está vacía
    if os.path.exists(embedded_calib):
        # Verificar si destino está vacío
        if not any(os.scandir(CALIBRATIONS_DIR)):
            import shutil
            for fname in os.listdir(embedded_calib):
                src = os.path.join(embedded_calib, fname)
                dst = os.path.join(CALIBRATIONS_DIR, fname)
                try:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                except Exception:
                    # No crítico: seguir si falla copiar algún archivo
                    pass
except Exception:
    pass

print(f"[CONFIG] Directorio de Datos (Escritura): {DATA_DIR}")
print(f"[CONFIG] Directorio Base (Recursos): {BASE_DIR}")
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
BAUDRATE = 3000000

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