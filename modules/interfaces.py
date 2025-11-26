from abc import ABC, abstractmethod
from typing import Dict, Any, List

class ISistemaPesaje(ABC):
    """
    Interfaz abstracta para el sistema de pesaje.
    Define el contrato que deben cumplir tanto la implementación real (MSCL)
    como la simulada (Mock).
    """

    @abstractmethod
    def conectar(self, puerto: str) -> bool:
        """Establece la conexión con la estación base."""
        pass

    @abstractmethod
    def desconectar(self) -> None:
        """Cierra la conexión y libera recursos."""
        pass

    @abstractmethod
    def obtener_datos(self) -> List[Dict[str, Any]]:
        """
        Recupera los datos más recientes de los sensores.
        Retorna una lista de diccionarios con formato:
        {'node_id': int, 'ch_name': str, 'value': float, 'timestamp': float}
        """
        pass

    @abstractmethod
    def tarar(self, node_id: int = None) -> None:
        """
        Establece el valor actual como cero (Tara).
        Si node_id es None, tara todos los sensores.
        """
        pass

    @abstractmethod
    def reset_tarar(self) -> None:
        """Elimina la tara y vuelve a mostrar valores brutos."""
        pass

    @abstractmethod
    def esta_conectado(self) -> bool:
        """Retorna el estado de la conexión."""
        pass
