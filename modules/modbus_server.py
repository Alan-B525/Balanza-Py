"""
Modbus data server helper – pymodbus 3.12+

Servidor Modbus RTU orientado a baja latencia: publica siempre el último valor
directamente en los holding registers.  Soporta shutdown() limpio para
desconexión / reconexión desde la GUI.
"""
from __future__ import annotations

import asyncio
import threading
import logging
from typing import List, Optional

log = logging.getLogger(__name__)

# ---------- pymodbus 3.12 imports ----------
from pymodbus.server import ModbusSerialServer
from pymodbus.framer import FramerType
from pymodbus.datastore import (
    ModbusServerContext,
    ModbusSequentialDataBlock,
)
try:
    from pymodbus.datastore import ModbusSlaveContext as _DeviceContext
except ImportError:
    from pymodbus.datastore import ModbusDeviceContext as _DeviceContext


class ModbusDataServer:
    """Servidor Modbus RTU serial con publicación directa de holding registers."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5020,
        serial_port: str | None = None,
        baudrate: int = 3000000,
        parity: str = 'N',
        stopbits: int = 1,
        bytesize: int = 8,
        timeout: float = 0.005,
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
        self.holding_start = holding_start

        # Modbus context / server references
        self._context: Optional[ModbusServerContext] = None
        self._server: Optional[ModbusSerialServer] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server_thread: Optional[threading.Thread] = None

        # Legacy coil addresses (compatibilidad con clientes que revisan coils)
        self.COIL_DATA_AVAILABLE = 0

        self.is_running = False
        self.last_error_msg: Optional[str] = None

    # ------------------------------------------------------------------ #
    #  Start / Stop
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Inicia el servidor Modbus RTU serial en un thread dedicado."""
        if not self.serial_port:
            raise RuntimeError("serial_port es obligatorio para Modbus RTU")

        # Preparar datastore
        hr_block = ModbusSequentialDataBlock(0, [0] * 2000)
        co_block = ModbusSequentialDataBlock(0, [0] * 100)
        store = _DeviceContext(
            di=ModbusSequentialDataBlock(0, [0] * 100),
            co=co_block,
            hr=hr_block,
            ir=ModbusSequentialDataBlock(0, [0] * 100),
        )

        try:
            context = ModbusServerContext(slaves=store, single=True)
        except TypeError:
            context = ModbusServerContext(devices=store, single=True)

        self._context = context

        def _run_server():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def _async_serve():
                """Crear y ejecutar el server dentro del loop activo."""
                self.last_error_msg = None
                self._server = ModbusSerialServer(
                    context,
                    framer=FramerType.RTU,
                    port=self.serial_port,
                    baudrate=self.baudrate,
                    parity=self.parity,
                    stopbits=self.stopbits,
                    bytesize=self.bytesize,
                    timeout=self.timeout,
                )
                log.info(
                    "Modbus RTU server started on %s @%s,%s",
                    self.serial_port, self.baudrate, self.parity,
                )
                self.is_running = True
                await self._server.serve_forever()

            try:
                self._loop.run_until_complete(_async_serve())
            except Exception as exc:
                self.is_running = False
                self.last_error_msg = str(exc)
                log.error("Failed to start server %s", exc)
            finally:
                self.is_running = False
                try:
                    self._loop.close()
                except Exception:
                    pass

        self._server_thread = threading.Thread(target=_run_server, daemon=True)
        self._server_thread.start()

    def stop(self) -> None:
        """Detiene el servidor Modbus de forma limpia."""
        if self._server and self._loop and not self._loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._server.shutdown(), self._loop
                )
                future.result(timeout=3.0)
            except Exception as exc:
                log.warning("Error al detener Modbus server: %s", exc)
        self._server = None
        self._context = None
        self.is_running = False

    def get_last_error(self) -> str:
        try:
            return str(self.last_error_msg or "")
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    #  Data publishing
    # ------------------------------------------------------------------ #
    def push_data(self, regs: List[int]) -> bool:
        """Publica inmediatamente una lista de enteros (0..65535) en los holding registers."""
        if not self.is_running:
            return False
        if not self._context:
            return False
        try:
            safe = [int(x) & 0xFFFF for x in regs]
            self._context[0x00].setValues(3, self.holding_start, safe)
            # Mantener coil data_available=1 para clientes legacy
            self._context[0x00].setValues(1, self.COIL_DATA_AVAILABLE, [1])
            return True
        except Exception:
            log.exception("Error publicando registros Modbus")
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    s = ModbusDataServer(serial_port="COM10", baudrate=3000000)
    try:
        s.start()
        import time
        i = 0
        while True:
            s.push_data([i, i + 1, i + 2, i + 3])
            i += 10
            time.sleep(5)
    except KeyboardInterrupt:
        s.stop()
