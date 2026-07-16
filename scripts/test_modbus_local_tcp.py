import time
import threading
import struct
import logging
from pymodbus.server import ModbusTcpServer
from pymodbus.client import ModbusTcpClient
from pymodbus.datastore import ModbusServerContext, ModbusSequentialDataBlock
from pymodbus.framer import FramerType

try:
    from pymodbus.datastore import ModbusSlaveContext as _DeviceContext
except ImportError:
    from pymodbus.datastore import ModbusDeviceContext as _DeviceContext

# Configuración de logs básica para ver la actividad
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ModbusTest")

def encode_float32(value: float, swap_words: bool = False) -> list:
    """Codifica un float a dos registros de 16 bits (Float32 IEEE 754) de la misma forma que backend_controller.py."""
    try:
        packed = struct.pack('>f', float(value))
    except Exception:
        packed = struct.pack('>f', 0.0)
    hi = (packed[0] << 8) | packed[1]
    lo = (packed[2] << 8) | packed[3]
    if swap_words:
        return [lo, hi]
    return [hi, lo]

def decode_float32(hi: int, lo: int, swap_words: bool = False) -> float:
    """Decodifica dos registros de 16 bits a float de la misma forma que modbus_client.py."""
    if swap_words:
        hi, lo = lo, hi
    try:
        raw_bytes = struct.pack('>HH', hi & 0xFFFF, lo & 0xFFFF)
        return struct.unpack('>f', raw_bytes)[0]
    except Exception:
        return 0.0

def run_server(context, host="127.0.0.1", port=5020):
    """Función para correr el servidor TCP en un hilo secundario."""
    server = ModbusTcpServer(
        context,
        address=(host, port),
        framer=FramerType.SOCKET
    )
    log.info(f"Servidor Modbus TCP iniciado en {host}:{port}")
    try:
        server.serve_forever()
    except Exception as e:
        log.error(f"Servidor detenido: {e}")

def main():
    # 1. Configurar el Datastore local del servidor
    # Simulamos holding registers (hr) y coils (co)
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

    # 2. Iniciar el servidor Modbus TCP local en un hilo
    server_thread = threading.Thread(target=run_server, args=(context,), daemon=True)
    server_thread.start()
    time.sleep(1) # Esperar a que el servidor levante

    # 3. Conectar el cliente Modbus TCP local
    client = ModbusTcpClient("127.0.0.1", port=5020, framer=FramerType.SOCKET)
    if not client.connect():
        log.error("No se pudo conectar el cliente al servidor local")
        return
    log.info("Cliente Modbus TCP conectado exitosamente a localhost:5020")

    # 4. Probar envío y recepción de datos
    holding_start = 1000
    valores_prueba = [124.50, 456.78, 1000.0, 0.0, -12.34]

    log.info("\n--- Iniciando ciclo de prueba de envío/recepción ---")
    for val in valores_prueba:
        # A. Codificar en 2 registros de 16 bits (Float32)
        regs = encode_float32(val)
        
        # B. Servidor publica los datos en el context (Holding registers desde address 1000)
        context[0x00].setValues(3, holding_start, regs)
        log.info(f"[Server] Publicado Peso: {val} kg (Registros codificados: {regs})")

        # C. Cliente lee los 2 holding registers desde address 1000
        try:
            response = client.read_holding_registers(holding_start, count=2)
            if response and hasattr(response, "registers") and len(response.registers) >= 2:
                # D. Cliente decodifica
                val_recibido = decode_float32(response.registers[0], response.registers[1])
                log.info(f"[Client] Leído y Decodificado: {val_recibido} kg")
                
                # E. Validar exactitud
                assert abs(val_recibido - val) < 1e-4, "¡Error! El valor recibido difiere significativamente."
                log.info("✔ ¡Coincidencia exacta!")
            else:
                log.error("✗ Error al leer los registros: respuesta inválida o vacía.")
        except Exception as e:
            log.error(f"✗ Excepción durante la lectura: {e}")

        time.sleep(1)
        print("-" * 50)

    # Limpieza
    client.close()
    log.info("Prueba finalizada con éxito. Todos los datos se enviaron y decodificaron correctamente.")

if __name__ == "__main__":
    main()
