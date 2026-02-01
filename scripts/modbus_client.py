import argparse
import json
import os
import time
from typing import Optional

from pymodbus.client import ModbusSerialClient


def _load_settings(settings_path: str) -> dict:
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _parity_from_text(text: str) -> str:
    t = (text or "").lower()
    if "par" in t and "impar" not in t:
        return "E"
    if "impar" in t or "ímpar" in t:
        return "O"
    return "N"


def _decode_int32(hi: int, lo: int) -> int:
    val = ((hi & 0xFFFF) << 16) | (lo & 0xFFFF)
    if val & 0x80000000:
        val -= 0x100000000
    return val


def read_loop(
    port: str,
    baudrate: int,
    parity: str,
    unit_id: int,
    scale: int,
    holding_start: int,
    ack_enabled: bool,
    interval: float,
) -> None:
    client = ModbusSerialClient(
        port=port,
        baudrate=baudrate,
        parity=parity,
        stopbits=1,
        bytesize=8,
        timeout=1.0,
    )
    if not client.connect():
        raise RuntimeError(f"No se pudo abrir el puerto {port}")

    try:
        while True:
            coils = client.read_coils(0, count=1, unit=unit_id)
            data_available = bool(coils.bits[0]) if coils and hasattr(coils, "bits") else False

            if data_available:
                regs = client.read_holding_registers(holding_start, count=2, unit=unit_id)
                if regs and hasattr(regs, "registers") and len(regs.registers) >= 2:
                    hi, lo = regs.registers[0], regs.registers[1]
                    raw = _decode_int32(hi, lo)
                    value = raw / float(scale)
                    print(f"Peso={value:.3f} kg (raw={raw})")
                else:
                    print("Lectura inválida de holding registers")

                if ack_enabled:
                    client.write_coil(1, True, unit=unit_id)

            time.sleep(interval)
    finally:
        try:
            client.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Cliente Modbus RTU para leer peso")
    parser.add_argument("--settings", default="settings.json", help="Ruta a settings.json")
    parser.add_argument("--port", help="Puerto serie (override)")
    parser.add_argument("--baud", type=int, help="Baudrate (override)")
    parser.add_argument("--parity", choices=["N", "E", "O"], help="Paridad (override)")
    parser.add_argument("--unit", type=int, help="ID esclavo (override)")
    parser.add_argument("--scale", type=int, default=1000, help="Factor de escala")
    parser.add_argument("--holding-start", type=int, default=1000, help="Holding start")
    parser.add_argument("--no-ack", action="store_true", help="No escribir coil ACK")
    parser.add_argument("--interval", type=float, default=0.2, help="Intervalo de lectura (s)")
    args = parser.parse_args()

    settings_path = os.path.abspath(args.settings)
    settings = _load_settings(settings_path)
    t = settings.get("transmissao", {}) if isinstance(settings, dict) else {}

    port = args.port or t.get("porta") or settings.get("serial_port") or "COM4"
    baudrate = int(args.baud or t.get("velocidade") or settings.get("baudrate") or 115200)
    parity = args.parity or _parity_from_text(t.get("paridade") or settings.get("paridade"))
    unit_id = int(args.unit or t.get("id_escravo_pc") or settings.get("id_escravo_pc") or 1)

    read_loop(
        port=port,
        baudrate=baudrate,
        parity=parity,
        unit_id=unit_id,
        scale=args.scale,
        holding_start=args.holding_start,
        ack_enabled=not args.no_ack,
        interval=args.interval,
    )


if __name__ == "__main__":
    main()
