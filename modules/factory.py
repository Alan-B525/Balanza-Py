"""
Factory para criar o sistema de pesagem apropriado baseado no modo de execução.

Modos disponíveis:
- MOCK: Simulação simples sem dependência MSCL
- MSCL_MOCK: Simulação usando estruturas similares ao MSCL
- REAL: Hardware real usando biblioteca MSCL
"""

from typing import Dict, Any
from .interfaces import ISistemaPesaje


def criar_sistema_pesaje(modo: str, nodos_config: Dict[str, Any]) -> ISistemaPesaje:
    """
    Factory function para criar o sistema de pesagem apropriado.
    
    Args:
        modo: Modo de execução ("MOCK", "MSCL_MOCK", "REAL")
        nodos_config: Configuração dos nós
        
    Returns:
        Instância de ISistemaPesaje apropriada para o modo
        
    Raises:
        ValueError: Se o modo não for reconhecido
        ImportError: Se as dependências do modo não estiverem disponíveis
    """
    modo = modo.upper().strip()
    
    if modo == "MOCK":
        return _create_mock(nodos_config)
    elif modo == "MSCL_MOCK":
        return _create_mscl_mock(nodos_config)
    elif modo == "REAL":
        return _create_real(nodos_config)
    else:
        raise ValueError(f"Modo de execução não reconhecido: '{modo}'. "
                        f"Use 'MOCK', 'MSCL_MOCK' ou 'REAL'.")


def _create_mock(nodos_config: Dict) -> ISistemaPesaje:
    """Cria sistema Mock simples."""
    from .sensor_mock import MockPesaje
    print("[FACTORY] Criando sistema MockPesaje (simulação simples)")
    return MockPesaje(nodos_config)


def _create_mscl_mock(nodos_config: Dict) -> ISistemaPesaje:
    """Cria sistema MSCL Mock para testes de integração."""
    try:
        from .sensor_mscl_mock import MSCLMockPesaje
        print("[FACTORY] Criando sistema MSCLMockPesaje (simulação MSCL)")
        return MSCLMockPesaje(nodos_config)
    except ImportError as e:
        print(f"[FACTORY] AVISO: MSCL Mock não disponível ({e}). Usando Mock simples.")
        return _create_mock(nodos_config)


def _create_real(nodos_config: Dict) -> ISistemaPesaje:
    """Cria sistema Real com MSCL usando o driver unificado."""
    try:
        # Usar o novo driver unificado (sensor_driver.py)
        from .sensor_driver import MSCLDriver
        print("[FACTORY] Criando sistema MSCLDriver (driver unificado)")
        return MSCLDriver(nodos_config)
            
    except ImportError as e:
        print(f"[FACTORY] ERRO: Não foi possível criar sistema Real: {e}")
        print("[FACTORY] Verifique se a biblioteca MSCL está instalada e no PATH.")
        raise


def get_available_modes() -> Dict[str, Dict[str, Any]]:
    """
    Retorna informações sobre os modos disponíveis.
    
    Returns:
        Dicionário com informações de cada modo
    """
    modes = {
        "MOCK": {
            "name": "Simulação Simples",
            "description": "Mock básico para desenvolvimento rápido",
            "requires_mscl": False,
            "available": True
        },
        "MSCL_MOCK": {
            "name": "Simulação MSCL",
            "description": "Mock usando estruturas MSCL para teste de integração",
            "requires_mscl": True,
            "available": False
        },
        "REAL": {
            "name": "Hardware Real",
            "description": "Conexão real com BaseStation MicroStrain",
            "requires_mscl": True,
            "available": False
        }
    }
    
    # Verificar disponibilidade de MSCL
    try:
        import mscl
        modes["MSCL_MOCK"]["available"] = True
        modes["REAL"]["available"] = True
    except ImportError:
        pass
    
    return modes


def check_mscl_installation() -> Dict[str, Any]:
    """
    Verifica a instalação do MSCL e retorna informações.
    
    Returns:
        Dicionário com status da instalação
    """
    result = {
        "installed": False,
        "version": None,
        "path": None,
        "error": None
    }
    
    try:
        import mscl
        result["installed"] = True
        
        # Tentar obter versão
        if hasattr(mscl, 'MSCL_VERSION'):
            result["version"] = mscl.MSCL_VERSION
        
        # Obter path
        result["path"] = getattr(mscl, '__file__', 'Desconhecido')
        
    except ImportError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = f"Erro inesperado: {e}"
    
    return result
