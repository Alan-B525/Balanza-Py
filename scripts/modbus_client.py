import argparse
import json
import os
import time
from collections import deque
from typing import Optional

from pymodbus.client import ModbusSerialClient
import matplotlib.pyplot as plt


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


def _call_with_device_id(func, *args, unit_id: int, **kwargs):
    """Compatibilidade entre pymodbus 2.x/3.x para identificação de escravo."""
    try:
        return func(*args, device_id=unit_id, **kwargs)
    except TypeError:
        try:
            return func(*args, slave=unit_id, **kwargs)
        except TypeError:
            return func(*args, unit=unit_id, **kwargs)


def read_loop(
    port: str,
    baudrate: int,
    parity: str,
    unit_id: int,
    scale: int,
    holding_start: int,
    ack_enabled: bool,
    interval: float,
    plot_enabled: bool,
    window_size: int,
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
        raise RuntimeError(f"Não foi possível abrir a porta {port}")

    samples = deque(maxlen=max(10, window_size))
    sample_idx = deque(maxlen=max(10, window_size))
    idx = 0

    fig = ax = line = None
    if plot_enabled:
        plt.ion()
        fig, ax = plt.subplots(figsize=(9, 4))
        (line,) = ax.plot([], [], lw=2)
        ax.set_title("Sinal recebido via Modbus RTU")
        ax.set_xlabel("Amostra")
        ax.set_ylabel("Carga (kg)")
        ax.grid(True, alpha=0.3)
        plt.show(block=False)

    try:
        while True:
            coils = _call_with_device_id(client.read_coils, 0, count=1, unit_id=unit_id)
            data_available = bool(coils.bits[0]) if coils and hasattr(coils, "bits") else False

            if data_available:
                regs = _call_with_device_id(client.read_holding_registers, holding_start, count=2, unit_id=unit_id)
                if regs and hasattr(regs, "registers") and len(regs.registers) >= 2:
                    hi, lo = regs.registers[0], regs.registers[1]
                    raw = _decode_int32(hi, lo)
                    value = raw / float(scale)
                    print(f"Carga={value:.3f} kg (raw={raw})")

                    if plot_enabled and fig is not None and plt.fignum_exists(fig.number):
                        idx += 1
                        samples.append(value)
                        sample_idx.append(idx)
                        line.set_data(sample_idx, samples)
                        ax.relim()
                        ax.autoscale_view()
                        plt.pause(0.001)
                else:
                    print("Leitura inválida de holding registers")

                if ack_enabled:
                    _call_with_device_id(client.write_coil, 1, True, unit_id=unit_id)

            time.sleep(interval)
    finally:
        try:
            client.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Cliente Modbus RTU para ler carga")
    parser.add_argument("--settings", default="settings.json", help="Caminho para settings.json")
    parser.add_argument("--port", help="Porta serial (override)")
    parser.add_argument("--baud", type=int, help="Baudrate (override)")
    parser.add_argument("--parity", choices=["N", "E", "O"], help="Paridade (override)")
    parser.add_argument("--unit", type=int, help="ID escravo (override)")
    parser.add_argument("--scale", type=int, default=1000, help="Fator de escala")
    parser.add_argument("--holding-start", type=int, default=1000, help="Holding start")
    parser.add_argument("--no-ack", action="store_true", help="Não escrever coil ACK")
    parser.add_argument("--interval", type=float, default=0.05, help="Intervalo de leitura (s)")
    parser.add_argument("--no-plot", action="store_true", help="Desabilitar gráfico")
    parser.add_argument("--window", type=int, default=300, help="Janela de amostras no gráfico")
    args = parser.parse_args()

    settings_path = os.path.abspath(args.settings)
    settings = _load_settings(settings_path)
    t = settings.get("transmissao", {}) if isinstance(settings, dict) else {}

    port = args.port or t.get("porta") or settings.get("serial_port") or "COM9"
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
        plot_enabled=not args.no_plot,
        window_size=args.window,
    )


if __name__ == "__main__":
    main()
