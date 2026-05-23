# -*- coding: utf-8 -*-
"""
Logger simple y centralizado para la aplicación, integrado con el sistema de logging estándar.

Escribe en DATA_DIR/log.log con rotación y expone funciones para compatibilidad:
- info(message)
- warning(message)
- error(message)
- debug(message)
- step(stage_name, message)
"""
import os
import logging
from logging.handlers import RotatingFileHandler
import threading

_lock = threading.Lock()
_initialized = False
_logger = logging.getLogger("BalanzaApp")

def _setup_logging_once() -> None:
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        
        # Obtener ruta de logs
        try:
            from config import DATA_DIR
            path = os.path.join(DATA_DIR, 'log.log')
        except Exception:
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'log.log')
            
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            # Configurar el root logger para escribir en RotatingFileHandler
            root_logger = logging.getLogger()
            
            # Solo configurar si no se ha configurado antes
            if not root_logger.handlers:
                # Rotación: 5 MB de tamaño máximo, hasta 3 archivos de respaldo
                handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
                formatter = logging.Formatter(
                    '%(asctime)s.%(msecs)03d [%(threadName)s] %(levelname)s %(module)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                handler.setFormatter(formatter)
                root_logger.addHandler(handler)
                
                # Establecer nivel root en INFO por defecto (puede ser DEBUG si se requiere)
                root_logger.setLevel(logging.INFO)
            
            _initialized = True
        except Exception:
            # No fallar la aplicación por fallas de configuración del logger
            pass

def info(message: str) -> None:
    _setup_logging_once()
    _logger.info(str(message))

def warning(message: str) -> None:
    _setup_logging_once()
    _logger.warning(str(message))

def error(message: str) -> None:
    _setup_logging_once()
    _logger.error(str(message))

def debug(message: str) -> None:
    _setup_logging_once()
    _logger.debug(str(message))

def step(stage: str, message: str = '') -> None:
    """Marca una etapa importante del flujo de la app.

    Ejemplo: step('startup', 'Configuracion cargada')
    """
    _setup_logging_once()
    _logger.log(logging.INFO, f"STEP | {stage}: {message}")
