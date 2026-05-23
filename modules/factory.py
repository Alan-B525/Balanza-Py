"""
Factory para criar o sistema de pesagem.

Versao de Producao - Suporta tanto modo REAL (MicroStrain) como MOCK (Simulacao).
"""

from typing import Dict, Any
from .interfaces import ISistemaPesaje
from modules import logger


def criar_sistema_pesaje(modo: str, nodos_config: Dict[str, Any], use_sensor_config: bool = False, avoid_eeprom: bool = False) -> ISistemaPesaje:
    """
    Factory function para criar o sistema de pesagem.
    
    Args:
        modo: Modo de execucao ("REAL" o "MOCK")
        nodos_config: Configuracao dos nos
        use_sensor_config: Se debe ler/escrever eeprom del sensor
        avoid_eeprom: Evitar ler a eeprom do sensor para acelerar a conexao
        
    Returns:
        Instancia de ISistemaPesaje
    """
    from .sensor_driver import MSCLDriver
    from .sensor_mock import MockDriver

    logger.info(f"[FACTORY] Solicitud de driver - modo={modo}")

    if modo and modo.upper() == 'MOCK':
        logger.info("[FACTORY] Iniciando MockDriver (modo MOCK)")
        return MockDriver(nodos_config, use_sensor_config=use_sensor_config)

    logger.info("[FACTORY] Iniciando MSCLDriver (modo REAL)")
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
        },
        "MOCK": {
            "name": "Simulação",
            "description": "Driver simulado de hardware para testes sem sensores físicos",
            "requires_mscl": False,
            "available": True
        }
    }


def check_mscl_installation() -> Dict[str, Any]:
    """Verifica a instalacao del MSCL y retorna informaciones."""
    result = {
        "installed": False,
        "version": None,
        "path": None,
        "error": None
    }
    
    import os
    import sys
    from config import MSCL_PATH
    
    if os.path.exists(MSCL_PATH) and MSCL_PATH not in sys.path:
        sys.path.insert(0, MSCL_PATH)
    
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
