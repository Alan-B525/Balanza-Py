# -*- coding: utf-8 -*-
"""
Logger simple y centralizado para la aplicación.

Escribe en DATA_DIR/log.log y expone funciones:
- info(message)
- warning(message)
- error(message)
- debug(message)
- step(stage_name, message)

Diseñado para mensajes concisos de estado y errores.
"""
import os
import datetime
import threading

_lock = threading.RLock()

def _get_log_path():
    try:
        from config import DATA_DIR
        return os.path.join(DATA_DIR, 'log.log')
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'log.log')

def _write(level: str, message: str) -> None:
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] [{level}] {message}\n"
    path = _get_log_path()
    try:
        with _lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line)
    except Exception:
        # No fallar la aplicación por logging
        pass

def info(message: str) -> None:
    _write('INFO', str(message))

def warning(message: str) -> None:
    _write('WARNING', str(message))

def error(message: str) -> None:
    _write('ERROR', str(message))

def debug(message: str) -> None:
    _write('DEBUG', str(message))

def step(stage: str, message: str = '') -> None:
    """Marca una etapa importante del flujo de la app.

    Ejemplo: step('startup', 'Configuracion cargada')
    """
    _write('STEP', f"{stage}: {message}")
