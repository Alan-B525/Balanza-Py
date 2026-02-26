# -*- coding: utf-8 -*-
import sys
import os
import platform

# =============================================================================
# 1. GESTIÓN DE RUTAS Y PERMISOS (CRÍTICO PARA EL EXE)
# =============================================================================

APP_NAME = "ControleDeCarga"  # Nombre de la carpeta en AppData

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
    En modo EXE usa %LOCALAPPDATA%\\<APP_NAME> (C:\\Users\\<usuario>\\AppData\\Local\\ControleDeCarga),
    que es escribible para el usuario actual sin requerir permisos especiales
    en Program Files.
    """
    if getattr(sys, 'frozen', False):
        # MODO EXE: Usar AppData\Local del usuario actual
        localappdata = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        if localappdata:
            path = os.path.join(localappdata, APP_NAME)
        else:
            # Fallback: junto al ejecutable (no debería ocurrir en Windows)
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
    "celda_1": {
        "id": 5454,
        "ch_load": "ch1",
        "ch_angle": "ch2",
        "ch": "ch1",
        "serial": "1232",
        "com_port": "COM4"
    },
}

# =============================================================================
# 4. TRANSMISIÓN Y ADQUISICIÓN (Configuración por Defecto)
# =============================================================================

# Configuración del Gateway (Adquisición de sensores)
GATEWAY = {
    "porta": PUERTO_COM,
    "velocidade": 115200,
    "timeout": 0.05,
}

# Configuración de Transmisión (Modbus RTU)
TRANSMISSAO = {
    "porta": "COM4",
    "velocidade": 115200,
    "paridade": "Nenhuma",
    "id_escravo_pc": 1,
    "swap_words": False,
    "stopbits": 1,
    "bytesize": 8,
    "timeout": 0.005,
}

# Tuning centralizado de tiempos/cadencias del backend.
# Ajustar aquí evita modificar múltiples archivos.
RUNTIME_TUNING = {
    # MSCL / Gateway
    "gateway_getdata_timeout_ms": 30,          # Timeout (ms) de getData(): cuánto espera el gateway por datos antes de devolver.
    "gateway_frame_timeout_s": 0.05,           # Tiempo máximo (s) para cerrar/publicar un frame parcial en el agregador.
    "gateway_timestamp_tolerance_ns": 20_000_000,  # Tolerancia (ns) para considerar dos sweeps como el mismo instante de muestreo.

    # Loop backend
    "backend_sleep_connected_s": 0.003,        # Pausa (s) del loop cuando el sistema está conectado/adquiriendo.
    "backend_sleep_idle_s": 0.05,              # Pausa (s) del loop cuando está desconectado o adquisición pausada.

    # Publicación GUI
    "gui_publish_interval_s": 0.05,            # Intervalo mínimo (s) entre envíos de DATA a la GUI (rate limit).
    "gui_keepalive_s": 0.5,                    # Intervalo máximo (s) sin publicar a GUI aunque no haya muestra nueva.

    # Modbus
    "modbus_retry_interval_s": 2.0,            # Cada cuánto (s) reintentar iniciar/reconectar el servidor Modbus.
    "modbus_start_grace_s": 1.5,               # Ventana de gracia (s) tras iniciar Modbus para no contar fallos transitorios.
    "modbus_fail_threshold": 3,                # Cantidad de fallos consecutivos de push_data antes de marcar error y reiniciar Modbus.
    "modbus_net_window_size": 30,              # Tamaño de bloque N (muestras procesadas): se promedia el bloque completo, se publica y se limpia.

    # Diagnóstico
    "debug_print_getdata_calls": False,        # True: imprime timestamps y delta_ms de llamadas a obtener_datos() en consola.
}

# Estructura completa de settings.json por defecto
DEFAULT_SETTINGS = {
    "execution_mode": MODO_EJECUCION,
    "use_sensor_config": True,
    "mock_sample_rate_hz": 50,
    "gateway": GATEWAY,
    "transmissao": TRANSMISSAO,
    "nodes": NODOS_CONFIG,
    "profiles_data": {
        "profiles": {
            "slot_1": {
                "name": "Perfil 1",
                "min": 200.0,
                "max": 1000.0
            },
            "slot_2": {
                "name": "Perfil 2",
                "min": 300.0,
                "max": 900.0
            },
            "slot_3": {
                "name": "Perfil 3",
                "min": 400.0,
                "max": 800.0
            },
            "slot_4": {
                "name": "Perfil 4",
                "min": 500.0,
                "max": 700.0
            },
            "slot_5": {
                "name": "Perfil 5",
                "min": 550.0,
                "max": 650.0
            }
        },
        "active_profile": "slot_2"
    }
}

def load_settings():
    """Carga settings desde `SETTINGS_FILE`. Devuelve dict con defaults si no existe o falla."""
    try:
        # Asegurar estructura de datos en cada lectura
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            os.makedirs(CALIBRATIONS_DIR, exist_ok=True)
        except Exception:
            pass

        # Si no existe, crear settings con defaults para evitar estados ambiguos
        if not os.path.exists(SETTINGS_FILE):
            try:
                save_settings(DEFAULT_SETTINGS.copy())
            except Exception:
                pass
            return DEFAULT_SETTINGS.copy()

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
        # Garantizar que la carpeta de datos exista antes de escribir
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            os.makedirs(CALIBRATIONS_DIR, exist_ok=True)
        except Exception:
            pass
        import json
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False

def ensure_runtime_data_files():
    """Crea carpeta/archivos mínimos de runtime si faltan, sin romper el arranque."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(CALIBRATIONS_DIR, exist_ok=True)
    except Exception:
        pass

    try:
        if not os.path.exists(SETTINGS_FILE):
            save_settings(DEFAULT_SETTINGS.copy())
    except Exception:
        pass

# Inicialización robusta al importar configuración (no bloqueante)
ensure_runtime_data_files()

RECONNECT_ATTEMPTS = 3
NODE_TIMEOUT_SECONDS = 5.0
DATA_TIMEOUT_MS = 100
# Tiempo (segundos) por intento mostrado en el diálogo de conexión
CONNECTION_ATTEMPT_TIMEOUT_S = 12

# Especificaciones del Display
APP_TITLE = "Controle de Carga"
APP_SIZE = "1360x768"
THEME_NAME = "litera"

# Especificaciones del Sensor
SENSOR_MV_PER_V = 1.2      
SENSOR_MAX_VOLTAGE = 2.5   
DISPLAY_DECIMALS = 0