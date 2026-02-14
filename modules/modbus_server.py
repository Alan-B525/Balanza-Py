"""
Modbus data server helper

Servidor Modbus orientado a baja latencia: publica siempre el último valor
directamente en los holding registers (sin handshake ACK).
"""
from __future__ import annotations

import threading
import time
import logging
from collections import deque
from typing import List, Optional

log = logging.getLogger(__name__)

try:
    # pymodbus <=2.x (API legacy)
    from pymodbus.server.sync import StartTcpServer, StartSerialServer
    from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
    from pymodbus.datastore import ModbusSequentialDataBlock
    from pymodbus.device import ModbusDeviceIdentification
    from pymodbus.transaction import ModbusRtuFramer
except Exception:  # pragma: no cover - optional dependency
    try:
        # pymodbus >=3.x
        from pymodbus.server import StartTcpServer, StartSerialServer
        try:
            from pymodbus.datastore import ModbusSlaveContext
        except Exception:
            from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext
        from pymodbus.datastore import ModbusServerContext
        from pymodbus.datastore import ModbusSequentialDataBlock
        try:
            from pymodbus.device import ModbusDeviceIdentification
        except Exception:
            from pymodbus import ModbusDeviceIdentification
        try:
            from pymodbus.framer import ModbusRtuFramer
        except Exception:
            try:
                from pymodbus.framer import FramerRTU as ModbusRtuFramer
            except Exception:
                from pymodbus.transaction import ModbusRtuFramer
    except Exception:
        try:
            # pymodbus >=3.x (startstop module)
            from pymodbus.server.startstop import StartTcpServer, StartSerialServer
            try:
                from pymodbus.datastore import ModbusSlaveContext
            except Exception:
                from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext
            from pymodbus.datastore import ModbusServerContext
            from pymodbus.datastore import ModbusSequentialDataBlock
            try:
                from pymodbus.device import ModbusDeviceIdentification
            except Exception:
                from pymodbus import ModbusDeviceIdentification
            try:
                from pymodbus.framer import ModbusRtuFramer
            except Exception:
                try:
                    from pymodbus.framer import FramerRTU as ModbusRtuFramer
                except Exception:
                    from pymodbus.transaction import ModbusRtuFramer
        except Exception:
            StartTcpServer = None
            StartSerialServer = None
            ModbusSlaveContext = None
            ModbusServerContext = None
            ModbusSequentialDataBlock = None
            ModbusDeviceIdentification = None
            ModbusRtuFramer = None


class ModbusDataServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5020,
        serial_port: str = None,
        baudrate: int = 9600,
        parity: str = 'N',
        stopbits: int = 1,
        bytesize: int = 8,
        timeout: float = 0.05,
        max_queue: int = 2000,
        holding_start: int = 1000,
    ) -> None:
        self.host = host
        self.port = port
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.parity = parity
        self.stopbits = stopbits
        self.bytesize = bytesize
        self.timeout = timeout
        self.max_queue = max_queue
        self.holding_start = holding_start

        self._queue: deque[List[int]] = deque()
        self._lock = threading.Lock()

        # Modbus context placeholders
        self._context = None
        self._server_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = threading.Event()

        # coil addresses (compatibilidad)
        self.COIL_DATA_AVAILABLE = 0
        self.COIL_ACK = 1

    def start(self) -> None:
        if StartTcpServer is None and StartSerialServer is None:
            raise RuntimeError("pymodbus no está instalado; instale pymodbus en requirements.txt")

        # preparar datastore
        hr_block = ModbusSequentialDataBlock(0, [0] * 2000)
        co_block = ModbusSequentialDataBlock(0, [0] * 100)
        try:
            store = ModbusSlaveContext(di=ModbusSequentialDataBlock(0, [0] * 100),
                                      co=co_block,
                                      hr=hr_block,
                                      ir=ModbusSequentialDataBlock(0, [0] * 100),
                                      zero_mode=True)
        except TypeError:
            store = ModbusSlaveContext(di=ModbusSequentialDataBlock(0, [0] * 100),
                                      co=co_block,
                                      hr=hr_block,
                                      ir=ModbusSequentialDataBlock(0, [0] * 100))
        try:
            context = ModbusServerContext(slaves=store, single=True)
        except TypeError:
            context = ModbusServerContext(devices=store, single=True)
        identity = ModbusDeviceIdentification()
        identity.VendorName = "Balanza-Py"
        identity.ProductCode = "BP"
        identity.VendorUrl = ""
        identity.ProductName = "Balanza Modbus Server"
        identity.ModelName = "ModbusDataServer"

        self._context = context

        # start server in a thread (StartXServer blocks)
        def _serve_tcp():
            log.info("Arrancando servidor Modbus TCP en %s:%s", self.host, self.port)
            try:
                StartTcpServer(context, identity=identity, address=(self.host, self.port))
            except Exception as e:
                log.exception("Error en Modbus TCP server: %s", e)

        def _serve_serial():
            log.info("Arrancando servidor Modbus RTU en %s @%s,%s%s", self.serial_port, self.baudrate, self.parity, '')
            try:
                # StartSerialServer espera argumentos similares a pyserial: port, baudrate, parity, stopbits, bytesize, timeout
                try:
                    # pymodbus 3.12+: espera nombre de framer
                    StartSerialServer(context, framer="rtu", port=self.serial_port, baudrate=self.baudrate,
                                      parity=self.parity, stopbits=self.stopbits, bytesize=self.bytesize, timeout=self.timeout)
                except Exception:
                    if ModbusRtuFramer is not None:
                        # fallback para variantes legacy
                        StartSerialServer(context, framer=ModbusRtuFramer, port=self.serial_port, baudrate=self.baudrate,
                                          parity=self.parity, stopbits=self.stopbits, bytesize=self.bytesize, timeout=self.timeout)
                    else:
                        StartSerialServer(context, port=self.serial_port, baudrate=self.baudrate,
                                          parity=self.parity, stopbits=self.stopbits, bytesize=self.bytesize, timeout=self.timeout)
            except Exception as e:
                log.exception("Error en Modbus Serial server: %s", e)

        self._running.set()
        if self.serial_port:
            self._server_thread = threading.Thread(target=_serve_serial, daemon=True)
        else:
            self._server_thread = threading.Thread(target=_serve_tcp, daemon=True)
        self._server_thread.start()

        # Sin monitor ACK: modo low-latency con publicación directa

    def stop(self) -> None:
        # no hay API directa para detener StartTcpServer en todas las versiones;
        # se deja la flag _running a False para terminar monitor.
        self._running.clear()

    def push_data(self, regs: List[int]) -> bool:
        """Publica inmediatamente una lista de enteros (0..65535)."""
        with self._lock:
            safe = [int(x) & 0xFFFF for x in regs]
            self._publish_values(safe)
            return True

    def _publish_values(self, values: List[int]) -> None:
        if not self._context:
            return
        if not values:
            return
        try:
            self._context[0x00].setValues(3, self.holding_start, values)
            # Mantener coil data_available=1 para clientes legados que la revisan
            self._context[0x00].setValues(1, self.COIL_DATA_AVAILABLE, [1])
        except Exception:
            log.exception("Error publicando registros Modbus")

    def _publish_first(self) -> None:
        # Método legado (sin uso en modo low-latency)
        if not self._context:
            return
        if not self._queue:
            return
        first = self._queue[0]
        self._publish_values(first)

    def _monitor_loop(self) -> None:
        # Método legado (ACK deshabilitado)
        while self._running.is_set():
            time.sleep(0.1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    s = ModbusDataServer(host="0.0.0.0", port=5020)
    try:
        s.start()
        # demo: añadir datos cada 5s
        i = 0
        while True:
            s.push_data([i, i + 1, i + 2, i + 3])
            i += 10
            time.sleep(5)
    except KeyboardInterrupt:
        s.stop()
