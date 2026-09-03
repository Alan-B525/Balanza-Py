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
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def get_writable_dir():
    """
    Directorio de datos del usuario (LECTURA Y ESCRITURA).
    """
    if getattr(sys, 'frozen', False):
        localappdata = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        if localappdata:
            path = os.path.join(localappdata, APP_NAME)
        else:
            path = os.path.dirname(sys.executable)
    else:
        path = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path

# --- DEFINICIÓN DE RUTAS EXPORTABLES ---
BASE_DIR = get_base_dir()      # Usar para recursos SOLO LECTURA (imágenes, DLLs)
DATA_DIR = get_writable_dir()  # Usar para guardar JSONs, settings, calibraciones

def resource_path(relative_path):
    """
    Devuelve la ruta absoluta al recurso, compatible con PyInstaller (EXE) y desarrollo.
    """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(BASE_DIR, relative_path)

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
CALIBRATIONS_DIR = os.path.join(DATA_DIR, "calibrations")

# =============================================================================
# 2. CONFIGURACIÓN DE LIBRERÍA MSCL
# =============================================================================

MSCL_PATH = os.path.join(BASE_DIR, "MSCL", "x64", "Release")
if os.path.exists(MSCL_PATH) and MSCL_PATH not in sys.path:
    sys.path.insert(0, MSCL_PATH)

# =============================================================================
# 3. CONSTANTES DEL NEGOCIO
# =============================================================================

MODO_EJECUCION = "REAL"
PUERTO_COM = "COM3"
BAUDRATE = 3000000

NODOS_CONFIG = {
    "celda_1": {
        "id": 19345,
        "ch_load": "ch1",
        "ch_angles": ["ch2", "ch3"],
        "load_enabled": True,
        "convert_rad_to_deg": False,
        "ch": "ch1",
        "serial": "3015",
        "com_port": "COM4"
    },
    "celda_2": {
        "id": 19344,
        "ch_load": "ch1",
        "ch_angles": ["ch1", "ch2", "ch3"],
        "load_enabled": False,
        "convert_rad_to_deg": False,
        "ch": "ch1",
        "serial": "",
        "com_port": "COM4"
    },
}

# =============================================================================
# 4. TRANSMISIÓN Y ADQUISICIÓN (Configuración por Defecto)
# =============================================================================

TRANSMISSAO = {
    "porta": "COM10",
    "velocidade": 115200,
    "paridade": "Nenhuma",
    "id_escravo_pc": 1,
    "swap_words": False,
    "stopbits": 1,
    "bytesize": 8,
    "timeout": 0.005,
}

RUNTIME_TUNING = {
    "gateway_getdata_timeout_ms": 5,
    "gateway_frame_timeout_s": 0.05,
    "gateway_timestamp_tolerance_ns": 20_000_000,
    "backend_sleep_connected_s": 0.010,
    "backend_sleep_idle_s": 0.05,
    "gui_publish_interval_s": 0.05,
    "gui_keepalive_s": 0.5,
    "modbus_retry_interval_s": 2.0,
    "modbus_start_grace_s": 1.5,
    "modbus_fail_threshold": 3,
    "modbus_net_window_size": 30,
    "debug_print_getdata_calls": False,
}

DEFAULT_SETTINGS = {
    "execution_mode": MODO_EJECUCION,
    "use_sensor_config": True,
    "serial_port": PUERTO_COM,
    "mock_sample_rate_hz": 50,
    "transmissao": TRANSMISSAO,
    "nodes": NODOS_CONFIG,
    "runtime_tuning": RUNTIME_TUNING,
    "decimals": 2,
    "angle_decimals": 1,
    "unit": "kgf",
    "profiles_data": {
        "profiles": {
            "slot_1": {"name": "Perfil 1", "min": 200.0, "max": 1000.0},
            "slot_2": {"name": "Perfil 2", "min": 300.0, "max": 900.0},
            "slot_3": {"name": "Perfil 3", "min": 400.0, "max": 800.0},
            "slot_4": {"name": "Perfil 4", "min": 500.0, "max": 700.0},
            "slot_5": {"name": "Perfil 5", "min": 550.0, "max": 650.0}
        },
        "active_profile": "slot_2"
    }
}

def deep_merge(defaults: dict, file_data: dict) -> dict:
    """
    Combina recursivamente el diccionario default y el del archivo.
    Los valores en file_data sobrescriben a los de defaults si tienen el tipo correcto.
    """
    result = defaults.copy()
    for key, value in file_data.items():
        if key in result:
            if isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                if value is not None and (result[key] is None or isinstance(value, type(result[key]))):
                    result[key] = value
        else:
            result[key] = value
    return result

def validate_settings(settings: dict) -> bool:
    """Valida los tipos y rangos de las configuraciones críticas en caliente."""
    try:
        if settings.get("execution_mode") not in ("REAL", "MOCK"):
            settings["execution_mode"] = "REAL"

        # Validar serial_port del sensor
        serial_p = settings.get("serial_port")
        if not serial_p or not isinstance(serial_p, str):
            # Intentar rescatar del primer nodo si existe
            if isinstance(settings.get("nodes"), dict):
                first_node = next(iter(settings["nodes"].values()), {})
                serial_p = first_node.get("com_port") if isinstance(first_node, dict) else None
            if not serial_p:
                serial_p = PUERTO_COM
        settings["serial_port"] = str(serial_p).strip()
            
        t = settings.setdefault("transmissao", {})
        if not isinstance(t, dict):
            settings["transmissao"] = DEFAULT_SETTINGS["transmissao"].copy()
            t = settings["transmissao"]
            
        try:
            t["velocidade"] = int(t.get("velocidade", 115200))
            t["id_escravo_pc"] = int(t.get("id_escravo_pc", 1))
            t["stopbits"] = int(t.get("stopbits", 1))
            t["bytesize"] = int(t.get("bytesize", 8))
            t["timeout"] = float(t.get("timeout", 0.05))
            t["swap_words"] = bool(t.get("swap_words", False))
        except (ValueError, TypeError):
            settings["transmissao"] = DEFAULT_SETTINGS["transmissao"].copy()
            
        nodes = settings.setdefault("nodes", {})
        if not isinstance(nodes, dict):
            settings["nodes"] = DEFAULT_SETTINGS["nodes"].copy()
        else:
            # Asegurar que cada nodo tenga sincronizado su com_port con serial_port
            for n_cfg in settings["nodes"].values():
                if isinstance(n_cfg, dict):
                    n_cfg["com_port"] = settings["serial_port"]
            
        try:
            decimals = int(settings.get("decimals", 2))
            if decimals < 0 or decimals > 3:
                decimals = 2
            settings["decimals"] = decimals
        except (ValueError, TypeError):
            settings["decimals"] = 2

        try:
            angle_decimals = int(settings.get("angle_decimals", 1))
            if angle_decimals < 0 or angle_decimals > 2:
                angle_decimals = 1
            settings["angle_decimals"] = angle_decimals
        except (ValueError, TypeError):
            settings["angle_decimals"] = 1

        try:
            unit = str(settings.get("unit", "kgf")).strip().lower()
            if unit not in ("kgf", "kg", "ton", "kn"):
                unit = "kgf"
            settings["unit"] = unit
        except Exception:
            settings["unit"] = "kgf"

        return True
    except Exception:
        return False

def load_settings():
    """Carga settings desde `SETTINGS_FILE`. Devuelve dict con defaults si no existe o falla."""
    try:
        if not os.path.exists(SETTINGS_FILE):
            save_settings(DEFAULT_SETTINGS.copy())
            return DEFAULT_SETTINGS.copy()

        import json
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

            # Migración: rescatar porta de gateway legacy si serial_port no estaba definido
            had_legacy_gateway = "gateway" in data
            if had_legacy_gateway and isinstance(data.get("gateway"), dict):
                gw_port = data["gateway"].get("porta")
                if gw_port and not data.get("serial_port"):
                    data["serial_port"] = gw_port
                data.pop("gateway", None)

            # Rescatar serial_port desde el primer nodo si no existe a nivel superior
            if not data.get("serial_port") and isinstance(data.get("nodes"), dict):
                first_node = next(iter(data["nodes"].values()), {})
                if isinstance(first_node, dict) and first_node.get("com_port"):
                    data["serial_port"] = first_node.get("com_port")

            merged = deep_merge(DEFAULT_SETTINGS, data)

            # Eliminar siempre el bloque gateway legacy si quedó en merged
            merged.pop("gateway", None)

            # Eliminar claves obsoletas de versiones antiguas
            obsolete = ["baudrate", "connection_type", "paridade", "id_escravo_pc", "swap_words", "stopbits", "bytesize", "timeout", "tcp_ip", "tcp_port"]
            for k in obsolete:
                merged.pop(k, None)

            validate_settings(merged)

            # Si el archivo tenía formato legacy (ej: contenía "gateway"), reescribirlo limpio
            if had_legacy_gateway:
                try:
                    save_settings(merged)
                except Exception:
                    pass

            return merged
    except Exception:
        pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings_dict):
    """Guarda el dict `settings_dict` en `SETTINGS_FILE` (JSON, UTF-8)."""
    try:
        import json
        validate_settings(settings_dict)

        # Eliminar gateway legacy para asegurar que nunca se vuelva a escribir
        settings_dict.pop("gateway", None)

        # Asegurar sincronización del puerto COM a todos los nodos
        target_port = settings_dict.get("serial_port", PUERTO_COM)
        if isinstance(settings_dict.get("nodes"), dict):
            for n_cfg in settings_dict["nodes"].values():
                if isinstance(n_cfg, dict):
                    n_cfg["com_port"] = target_port

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
        # Copiar calibraciones por defecto embebidas (si existen en recursos) al directorio de datos
        embedded_calib = resource_path('calibrations')
        if os.path.exists(embedded_calib):
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
                        pass
    except Exception:
        pass

    try:
        if not os.path.exists(SETTINGS_FILE):
            save_settings(DEFAULT_SETTINGS.copy())
    except Exception:
        pass

RECONNECT_ATTEMPTS = 3
NODE_TIMEOUT_SECONDS = 5.0
DATA_TIMEOUT_MS = 100
CONNECTION_ATTEMPT_TIMEOUT_S = 12

# Especificaciones del Display
APP_TITLE = "Controle de Carga"
APP_SIZE = "1360x768"
THEME_NAME = "litera"

# Especificaciones del Sensor
SENSOR_MV_PER_V = 1.2      
SENSOR_MAX_VOLTAGE = 2.5   
DISPLAY_DECIMALS = 0