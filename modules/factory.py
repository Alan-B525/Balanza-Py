"""
Factory para criar o sistema de pesagem.

Versao de Producao - Apenas modo REAL com hardware MicroStrain.
"""

from typing import Dict, Any
from .interfaces import ISistemaPesaje


def criar_sistema_pesaje(modo: str, nodos_config: Dict[str, Any]) -> ISistemaPesaje:
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
    print("[FACTORY] Iniciando MSCLDriver (modo producao)")
    return MSCLDriver(nodos_config)


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
