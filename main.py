import sys
import os
import queue
import threading

# Usar la lógica de rutas de config.py para máxima compatibilidad (EXE/script)
import config
current_dir = config.get_writable_dir()
sys.path.append(current_dir)

from config import MODO_EJECUCION, PUERTO_COM as DEFAULT_COM, NODOS_CONFIG as DEFAULT_NODOS
from modules.data_processor import DataProcessor
from modules.gui import BalanzaGUI
from modules.factory import criar_sistema_pesaje, check_mscl_installation
from modules.backend_controller import BackendController

# Locks y variables de estado globales protegidas
_GLOBAL_STATE_LOCK = threading.Lock()
ACTIVE_COM = DEFAULT_COM
ACTIVE_NODOS = DEFAULT_NODOS
ACTIVE_MODE = MODO_EJECUCION
USE_SENSOR_CONFIG = True
_SINGLE_INSTANCE_MUTEX = None

RUNTIME_TUNING = getattr(config, 'RUNTIME_TUNING', {})
DEBUG_PRINT_GETDATA_CALLS = bool(RUNTIME_TUNING.get('debug_print_getdata_calls', False))


def _acquire_single_instance() -> bool:
    """Evita ejecutar más de una instancia simultánea en Windows."""
    global _SINGLE_INSTANCE_MUTEX
    if os.name != 'nt':
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Global\\BalanzaPyMainMutex"
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            return True
        already_exists = (kernel32.GetLastError() == 183)  # ERROR_ALREADY_EXISTS
        if already_exists:
            print("[ERRO] Ya existe una instancia activa de la aplicación.")
            return False
        _SINGLE_INSTANCE_MUTEX = handle
        return True
    except Exception:
        return True


def load_custom_settings():
    """Carga los parametros desde settings.json si existe."""
    global ACTIVE_COM, ACTIVE_NODOS, ACTIVE_MODE, USE_SENSOR_CONFIG, RUNTIME_TUNING
    import json
    
    settings_path = os.path.join(current_dir, "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            with _GLOBAL_STATE_LOCK:
                # Leer si se debe usar la configuración cargada en el nodo
                USE_SENSOR_CONFIG = settings.get("use_sensor_config", True)

                # Configurar Modo de Execucao
                if "execution_mode" in settings:
                    ACTIVE_MODE = settings["execution_mode"]

                # Leer el puerto COM del primer nodo (fuente de verdad)
                if "nodes" in settings and isinstance(settings["nodes"], dict):
                    first_node = next(iter(settings["nodes"].values()), {})
                    ACTIVE_COM = first_node.get("com_port", "") or DEFAULT_COM
                elif "gateway" in settings and isinstance(settings["gateway"], dict):
                    # Compatibilidad con settings.json anteriores
                    ACTIVE_COM = settings["gateway"].get("porta", DEFAULT_COM)
                else:
                    ACTIVE_COM = settings.get("serial_port", DEFAULT_COM)
                    
                # Configurar Nos
                if "nodes" in settings:
                    ACTIVE_NODOS = settings["nodes"]

                # Actualizar RUNTIME_TUNING con valores de settings.json (deep merge)
                if "runtime_tuning" in settings and isinstance(settings["runtime_tuning"], dict):
                    RUNTIME_TUNING = {**RUNTIME_TUNING, **settings["runtime_tuning"]}
                
            print(f"[INFO] Configuracao carregada de settings.json")
            print(f"       Modo: {ACTIVE_MODE}")
            print(f"       Porta: {ACTIVE_COM}")
            print(f"       Nos: {len(ACTIVE_NODOS)}")
            print(f"       modbus_net_window_size: {RUNTIME_TUNING.get('modbus_net_window_size', 30)}")
            
        except Exception as e:
            print(f"[ERRO] Erro carregando settings.json: {e}")


def show_startup_info():
    """Muestra la informacion de inicio."""
    try:
        from modules import logger
        logger.step('startup', f"Modo={ACTIVE_MODE} | use_sensor_config={USE_SENSOR_CONFIG}")
        mscl_info = check_mscl_installation()
        if mscl_info.get('installed'):
            logger.info(f"MSCL instalado | version={mscl_info.get('version')}")
        else:
            logger.warning("MSCL no encontrado")
    except Exception:
        pass


def main():
    """Funcao principal da aplicacao."""
    # Otimizar temporizador no Windows para mayor precisión de sleep (~1ms)
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass

    config.ensure_runtime_data_files()
    load_custom_settings()
    show_startup_info()
    
    data_queue = queue.Queue()
    command_queue = queue.Queue()
    
    with _GLOBAL_STATE_LOCK:
        mode = ACTIVE_MODE
        nodos = ACTIVE_NODOS
        use_sensor_cfg = USE_SENSOR_CONFIG

    procesador = DataProcessor(nodos)
    if procesador.load_tara_state():
        try:
            from modules import logger
            logger.info('Estado de tara cargado de settings.json')
        except Exception:
            pass
            
    try:
        from modules import logger
        logger.step('init', f'Creando sistema de pesaje | modo={mode}')
    except Exception:
        pass
        
    sistema_pesaje = criar_sistema_pesaje(mode, nodos, use_sensor_config=use_sensor_cfg, avoid_eeprom=False)
    
    try:
        from modules import logger
        mapping_lines = []
        for name, cfg in nodos.items():
            mapping_lines.append(f"{name} -> id={cfg.get('id')} ch={cfg.get('ch')} serial={cfg.get('serial')}")
        logger.info('Mapping lógico→físico: ' + '; '.join(mapping_lines))
    except Exception:
        pass

    # Preparar configuración Modbus (RTU) usando settings.json/config
    modbus_params = None
    try:
        settings = config.load_settings()

        serial_port = None
        modbus_enabled = False
        baudrate = 3000000
        parity = 'N'
        stopbits = 1
        bytesize = 8
        timeout = 0.05
        swap_words = False

        if settings and isinstance(settings.get('transmissao'), dict):
            t = settings.get('transmissao')
            if 'enabled' in t:
                modbus_enabled = bool(t.get('enabled'))
            else:
                modbus_enabled = True
            porta_conf = t.get('porta')
            if isinstance(porta_conf, str) and porta_conf.strip():
                serial_port = porta_conf.strip()
            swap_words = bool(t.get('swap_words', swap_words))
            try:
                baudrate = int(t.get('velocidade', t.get('baudrate', baudrate)))
            except Exception:
                pass
            p = t.get('paridade', t.get('parity', 'Nenhuma'))
            if isinstance(p, str):
                mp = p.lower()
                if 'par' in mp and 'impar' not in mp:
                    parity = 'E'
                elif 'impar' in mp or 'ímpar' in mp:
                    parity = 'O'
                else:
                    parity = 'N'
            try:
                stopbits = int(t.get('stopbits', stopbits))
            except Exception:
                pass
            try:
                bytesize = int(t.get('bytesize', bytesize))
            except Exception:
                pass
            try:
                timeout = float(t.get('timeout', timeout))
            except Exception:
                pass

        # Determinar fuente de datos Modbus: celda_1 ch_load por defecto
        data_source_key = None
        try:
            if isinstance(nodos, dict):
                cfg_c1 = nodos.get('celda_1', {})
                if isinstance(cfg_c1, dict):
                    node_id = cfg_c1.get('id')
                    ch_load = cfg_c1.get('ch_load') or cfg_c1.get('ch')
                    if node_id is not None:
                        data_source_key = f"{node_id}:{ch_load or 'ch1'}"
        except Exception:
            data_source_key = None

        modbus_params = {
            'enabled': bool(modbus_enabled and serial_port),
            'serial_port': serial_port,
            'baudrate': baudrate,
            'parity': parity,
            'stopbits': stopbits,
            'bytesize': bytesize,
            'timeout': timeout,
            'swap_words': swap_words,
            'data_source_key': data_source_key,
        }
    except Exception:
        modbus_params = None

    # Inicializar y arrancar el backend controller en segundo plano
    controller = BackendController(
        data_queue=data_queue,
        command_queue=command_queue,
        sistema_pesaje=sistema_pesaje,
        procesador=procesador,
        modbus_params=modbus_params,
        execution_mode=mode
    )
    controller.start()

    app = BalanzaGUI(data_queue, command_queue, procesador)
    
    # Establecer icono de la ventana usando assets/icon.ico (fallback a icon.png)
    try:
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        assets_dir = os.path.join(base_path, 'assets')
        ico_path = os.path.join(assets_dir, 'icon.ico')
        png_path = os.path.join(assets_dir, 'icon.png')
        if os.path.exists(ico_path):
            try:
                app.iconbitmap(ico_path)
            except Exception:
                try:
                    img = None
                    from PIL import Image, ImageTk
                    img = ImageTk.PhotoImage(Image.open(ico_path))
                    app.iconphoto(False, img)
                    app._icon_img = img
                except Exception:
                    pass
        elif os.path.exists(png_path):
            try:
                from PIL import Image, ImageTk
                img = ImageTk.PhotoImage(Image.open(png_path))
                app.iconphoto(False, img)
                app._icon_img = img
            except Exception:
                pass
    except Exception:
        pass
        
    try:
        app.mainloop()
    finally:
        # Asegurar apagado ordenado del controlador y liberación de puertos al salir
        controller.stop()


if __name__ == "__main__":
    if _acquire_single_instance():
        main()
