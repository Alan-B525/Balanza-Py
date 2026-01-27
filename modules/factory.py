"""
Factory para criar o sistema de pesagem.

Versao de Producao - Apenas modo REAL com hardware MicroStrain.
"""

from typing import Dict, Any
from .interfaces import ISistemaPesaje


def criar_sistema_pesaje(modo: str, nodos_config: Dict[str, Any], use_sensor_config: bool = False, avoid_eeprom: bool = False) -> ISistemaPesaje:
    """
    Factory function para criar o sistema de pesagem.
    
    Args:
        modo: Modo de execucao (apenas "REAL" em producao)
        nodos_config: Configuracao dos nos
        
    Returns:
        Instancia de ISistemaPesaje (MSCLDriver)
        
    Raises:
        ImportError: Se MSCL nao estiver disponivel
    """
    from .sensor_driver import MSCLDriver
    from .sensor_mock import MockDriver
    import datetime, os
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'log.log')
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Log inicial indicando el modo solicitado
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] [FACTORY] Solicitud de driver - modo={modo}\n")
    except Exception:
        pass

    # Seleccionar driver según el modo
    if modo and modo.upper() == 'MOCK':
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] [FACTORY] Iniciando MockDriver (modo MOCK)\n")
        except Exception:
            pass
        return MockDriver(nodos_config, use_sensor_config=use_sensor_config)

    return MSCLDriver(nodos_config, use_sensor_config=use_sensor_config, avoid_eeprom=avoid_eeprom)


def get_available_modes() -> Dict[str, Dict[str, Any]]:
    """Retorna informacoes sobre os modos disponiveis."""
    mscl_info = check_mscl_installation()
    
    return {
        "REAL": {
            "name": "Hardware Real",
            "description": "Conexao real com BaseStation MicroStrain",
            "requires_mscl": True,
            "available": mscl_info["installed"]
        }
    }


def check_mscl_installation() -> Dict[str, Any]:
    """Verifica a instalacao do MSCL e retorna informacoes."""
    result = {
        "installed": False,
        "version": None,
        "path": None,
        "error": None
    }
    
    # Agregar ruta de MSCL al path del sistema
    import os
    import sys
    _mscl_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'MSCL', 'x64', 'Release')
    if _mscl_path not in sys.path:
        sys.path.insert(0, _mscl_path)
    
    try:
        import mscl
        result["installed"] = True
        if hasattr(mscl, 'MSCL_VERSION'):
            result["version"] = mscl.MSCL_VERSION
        result["path"] = getattr(mscl, '__file__', 'Desconhecido')
    except ImportError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = f"Erro inesperado: {e}"
    
    return result
