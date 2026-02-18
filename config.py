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
PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")
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
    "celda_1": {
        "id": 0,
        "ch": "ch1",
        "ch_load": "ch1",
        "ch_angle": "ch2",
        "nombre": "Célula 1",
        "posicion": "1",
        "serial": "",
        "com_port": ""
    },
}

# =============================================================================
# 4. TRANSMISIÓN Y ADQUISICIÓN (Configuración por Defecto)
# =============================================================================

# Configuración del Gateway (Adquisición de sensores)
GATEWAY = {
    "porta": PUERTO_COM,
    "velocidade": BAUDRATE,
    "timeout": 0.05,
}

# Configuración de Transmisión (Modbus RTU)
TRANSMISSAO = {
    "porta": "COM10",
    "velocidade": 115200,
    "paridade": "Nenhuma",
    "stopbits": 1,
    "bytesize": 8,
    "timeout": 0.005,
    "id_escravo_pc": 1,
    "swap_words": False,
}

# Estructura completa de settings.json por defecto
DEFAULT_SETTINGS = {
    "execution_mode": MODO_EJECUCION,
    "use_sensor_config": True,
    "mock_sample_rate_hz": 300,
    "gateway": GATEWAY,
    "transmissao": TRANSMISSAO,
    "nodes": NODOS_CONFIG,
    "profiles_data": {
        "profiles": {
            f"slot_{i}": {"name": f"Perfil {i}", "min": 0.0, "max": 1000.0}
            for i in range(1, 6)
        },
        "active_profile": "slot_1"
    }
}

def load_settings():
    """Carga settings desde `SETTINGS_FILE`. Devuelve dict con defaults si no existe o falla."""
    try:
        if os.path.exists(SETTINGS_FILE):
            import json
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Merge with defaults to ensure keys exist
                merged = DEFAULT_SETTINGS.copy()
                merged.update(data)
                
                # Migración/Limpieza: Si ya tenemos bloques nuevos, quitar basura del nivel superior
                if "gateway" in merged:
                    obsolete = ["serial_port", "baudrate", "connection_type", "paridade", "id_escravo_pc", "swap_words", "stopbits", "bytesize", "timeout", "tcp_ip", "tcp_port"]
                    for k in obsolete:
                        if k in merged:
                            del merged[k]

                # Ensure nodes key exists
                if 'nodes' not in merged or not isinstance(merged['nodes'], dict):
                    merged['nodes'] = DEFAULT_SETTINGS['nodes']
                return merged
    except Exception:
        pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings_dict):
    """Guarda el dict `settings_dict` en `SETTINGS_FILE` (JSON, UTF-8)."""
    try:
        import json
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False

RECONNECT_ATTEMPTS = 3
NODE_TIMEOUT_SECONDS = 5.0
DATA_TIMEOUT_MS = 100
# Tiempo (segundos) por intento mostrado en el diálogo de conexión
CONNECTION_ATTEMPT_TIMEOUT_S = 12

# Especificaciones del Display
APP_TITLE = "Control de Carga ARBRA"
APP_SIZE = "1360x768"
THEME_NAME = "litera"

# Especificaciones del Sensor
SENSOR_MV_PER_V = 1.2      
SENSOR_MAX_VOLTAGE = 2.5   
DISPLAY_DECIMALS = 0