import json
import os
import struct
import sys
import time
from typing import List
import argparse

from pymodbus.client import ModbusSerialClient
from pymodbus.framer import FramerType


ADDRESS = 1000
REGISTER_COUNT = 12
DEFAULT_PORT = "COM10"
DEFAULT_BAUD = 115200
DEFAULT_UNIT = 1
DEFAULT_SWAP_WORDS = False


def _load_settings() -> dict:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "settings.json"),
        os.path.join(script_dir, "..", "settings.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                return {}
    return {}


def _decode_float32(hi: int, lo: int, swap_words: bool = False) -> float:
    if swap_words:
        hi, lo = lo, hi
    try:
        raw_bytes = struct.pack(">HH", hi & 0xFFFF, lo & 0xFFFF)
        return struct.unpack(">f", raw_bytes)[0]
    except Exception:
        return 0.0


def _available_ports() -> List[str]:
    try:
        import serial.tools.list_ports

        return sorted(p.device for p in serial.tools.list_ports.comports())
    except Exception:
        return []


def _decode_payload(registers: List[int], swap_words: bool = False) -> List[float]:
    values = []
    for index in range(0, len(registers), 2):
        values.append(_decode_float32(registers[index], registers[index + 1], swap_words))
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Modbus RTU de carga + 5 angulos")
    parser.add_argument("--port", default=DEFAULT_PORT, help="Puerto serie del cliente (por defecto COM10)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baudrate")
    parser.add_argument("--unit", type=int, default=DEFAULT_UNIT, help="Unit ID / device id")
    parser.add_argument("--swap-words", action="store_true", help="Invertir palabras de float32")
    args = parser.parse_args()

    settings = _load_settings()
    modbus_cfg = settings.get("transmissao", {}) if isinstance(settings, dict) else {}

    port = str(args.port or DEFAULT_PORT)
    baudrate = int(args.baud or modbus_cfg.get("velocidade", DEFAULT_BAUD) or DEFAULT_BAUD)
    unit_id = int(args.unit or modbus_cfg.get("id_escravo_pc", DEFAULT_UNIT) or DEFAULT_UNIT)
    swap_words = bool(args.swap_words or modbus_cfg.get("swap_words", DEFAULT_SWAP_WORDS))
    parity_cfg = str(modbus_cfg.get("paridade", "Nenhuma") or "Nenhuma").lower()
    parity = "N"
    if "par" in parity_cfg and "impar" not in parity_cfg:
        parity = "E"
    elif "impar" in parity_cfg or "ímpar" in parity_cfg:
        parity = "O"
    stopbits = int(modbus_cfg.get("stopbits", 1) or 1)
    bytesize = int(modbus_cfg.get("bytesize", 8) or 8)
    timeout = float(modbus_cfg.get("timeout", 0.1) or 0.1)

    ports = _available_ports()
    if ports and port not in ports:
        print(f"[INFO] Puerto por defecto: {port}")
        print(f"[INFO] Puertos detectados: {', '.join(ports)}")

    client = ModbusSerialClient(
        port=port,
        baudrate=baudrate,
        parity=parity,
        stopbits=stopbits,
        bytesize=bytesize,
        timeout=timeout,
        framer=FramerType.RTU,
    )

    if not client.connect():
        print(f"No se pudo abrir {port}")
        return 1

    print(f"Conectado a {port} | baud={baudrate} | unit={unit_id} | address={ADDRESS}")
    print("Leyendo carga + 5 angulos. Ctrl+C para salir.\n")

    try:
        while True:
            response = client.read_holding_registers(ADDRESS, count=REGISTER_COUNT, device_id=unit_id)
            if response and hasattr(response, "registers") and len(response.registers) >= REGISTER_COUNT:
                values = _decode_payload(response.registers[:REGISTER_COUNT], swap_words=swap_words)
                load = values[0]
                angles = values[1:]
                angle_text = ", ".join(f"a{i + 1}={angle:.3f}" for i, angle in enumerate(angles))
                print(f"carga={load:.3f} | {angle_text}")
            else:
                is_error = getattr(response, "isError", lambda: False)()
                print(f"respuesta invalida: type={type(response).__name__} isError={is_error} obj={response}")

            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    finally:
        try:
            client.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
