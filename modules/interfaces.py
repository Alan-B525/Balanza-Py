from abc import ABC, abstractmethod
from typing import Dict, Any, List

class ISistemaPesaje(ABC):
    """
    Interface abstrata para o sistema de pesagem.
    Define o contrato que devem cumprir tanto a implementação real (MSCL)
    quanto a simulada (Mock).
    """

    @abstractmethod
    def conectar(self, puerto: str) -> bool:
        """Estabelece a conexão com a estação base."""
        pass

    @abstractmethod
    def desconectar(self) -> None:
        """Fecha a conexão e libera recursos."""
        pass

    @abstractmethod
    def obtener_datos(self) -> List[Dict[str, Any]]:
        """
        Recupera os dados mais recentes dos sensores.
        Retorna uma lista de dicionários com formato:
        {'node_id': int, 'ch_name': str, 'value': float, 'timestamp': float}
        """
        pass

    @abstractmethod
    def tarar(self, node_id: int = None) -> None:
        """
        Define o valor atual como zero (Tara).
        Se node_id é None, tara todos os sensores.
        """
        pass

    @abstractmethod
    def reset_tarar(self) -> None:
        """Remove a tara e volta a mostrar valores brutos."""
        pass

    @abstractmethod
    def esta_conectado(self) -> bool:
        """Retorna o estado da conexão."""
        pass
