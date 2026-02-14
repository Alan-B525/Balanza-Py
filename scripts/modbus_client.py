import argparse
import json
import os
import time
import statistics
from collections import deque
from typing import List, Tuple

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


def _read_once(client: ModbusSerialClient, holding_start: int, unit_id: int, scale: int) -> Tuple[bool, float, int, float]:
    t0 = time.perf_counter()
    regs = _call_with_device_id(client.read_holding_registers, holding_start, count=2, unit_id=unit_id)
    t1 = time.perf_counter()
    rtt_ms = (t1 - t0) * 1000.0

    if regs and hasattr(regs, "registers") and len(regs.registers) >= 2:
        hi, lo = regs.registers[0], regs.registers[1]
        raw = _decode_int32(hi, lo)
        value = raw / float(scale)
        return True, value, raw, rtt_ms

    return False, 0.0, 0, rtt_ms


def _parse_float_list(text: str) -> List[float]:
    vals = []
    for chunk in str(text or "").split(','):
        c = chunk.strip()
        if not c:
            continue
        vals.append(float(c))
    return vals


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = int(round(0.95 * (len(ordered) - 1)))
    return ordered[max(0, min(idx, len(ordered) - 1))]


def _print_sweep_table(rows: List[dict]) -> None:
    print("\n=== Comparación de latencia por intervalo/frecuencia ===")
    print("interval(s) | freq(Hz) | samples | ok(%) | mean_rtt(ms) | p95_rtt(ms) | max_rtt(ms) | update_rate(Hz)")
    print("-" * 102)
    for row in rows:
        print(
            f"{row['interval']:10.4f} | "
            f"{row['freq_hz']:8.1f} | "
            f"{row['samples']:7d} | "
            f"{row['ok_pct']:5.1f}% | "
            f"{row['mean_rtt']:12.3f} | "
            f"{row['p95_rtt']:11.3f} | "
            f"{row['max_rtt']:11.3f} | "
            f"{row['update_hz']:14.2f}"
        )


def read_loop(
    port: str,
    baudrate: int,
    parity: str,
    unit_id: int,
    scale: int,
    holding_start: int,
    interval: float,
    timeout: float,
    mode: str,
    plot_mode: str,
    plot_enabled: bool,
    window_size: int,
    print_every: int,
    sweep_intervals: List[float],
    sweep_seconds: float,
) -> None:
    client = ModbusSerialClient(
        port=port,
        baudrate=baudrate,
        parity=parity,
        stopbits=1,
        bytesize=8,
        timeout=max(0.001, float(timeout)),
    )
    if not client.connect():
        raise RuntimeError(f"Não foi possível abrir a porta {port}")

    try:
        if mode == "sweep":
            rows = []
            intervals = sweep_intervals or [interval]
            for current_interval in intervals:
                t_start = time.perf_counter()
                t_end = t_start + max(0.2, float(sweep_seconds))

                count_total = 0
                count_ok = 0
                last_raw = None
                count_updates = 0
                rtts = []

                while time.perf_counter() < t_end:
                    ok, _value, raw, rtt_ms = _read_once(client, holding_start, unit_id, scale)
                    count_total += 1
                    rtts.append(rtt_ms)

                    if ok:
                        count_ok += 1
                        if last_raw is None or raw != last_raw:
                            count_updates += 1
                        last_raw = raw

                    if current_interval > 0:
                        time.sleep(current_interval)

                elapsed = max(1e-6, time.perf_counter() - t_start)
                mean_rtt = statistics.fmean(rtts) if rtts else 0.0
                max_rtt = max(rtts) if rtts else 0.0
                row = {
                    'interval': float(current_interval),
                    'freq_hz': (1.0 / current_interval) if current_interval > 0 else 0.0,
                    'samples': int(count_total),
                    'ok_pct': (100.0 * count_ok / count_total) if count_total else 0.0,
                    'mean_rtt': mean_rtt,
                    'p95_rtt': _p95(rtts),
                    'max_rtt': max_rtt,
                    'update_hz': count_updates / elapsed,
                }
                rows.append(row)

            _print_sweep_table(rows)

            if plot_enabled and rows:
                xs = [r['freq_hz'] for r in rows]
                ys_mean = [r['mean_rtt'] for r in rows]
                ys_p95 = [r['p95_rtt'] for r in rows]
                plt.figure(figsize=(10, 5))
                plt.plot(xs, ys_mean, marker='o', label='RTT medio (ms)')
                plt.plot(xs, ys_p95, marker='s', label='RTT p95 (ms)')
                plt.xlabel('Frecuencia de polling (Hz)')
                plt.ylabel('Latencia Modbus RTT (ms)')
                plt.title('Comparación de latencia por frecuencia')
                plt.grid(True, alpha=0.3)
                plt.legend()
                plt.tight_layout()
                plt.show()
            return

        samples = deque(maxlen=max(10, window_size))
        rtt_samples = deque(maxlen=max(10, window_size))
        sample_idx = deque(maxlen=max(10, window_size))
        idx = 0

        fig = ax_value = ax_rtt = line_value = line_rtt = None
        if plot_enabled:
            plt.ion()
            if plot_mode == 'latency':
                fig, ax_rtt = plt.subplots(figsize=(9, 4))
            elif plot_mode == 'both':
                fig, (ax_value, ax_rtt) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
            else:
                fig, ax_value = plt.subplots(figsize=(9, 4))

            if ax_value is not None:
                (line_value,) = ax_value.plot([], [], lw=2)
                ax_value.set_title("Sinal recebido via Modbus RTU")
                ax_value.set_ylabel("Carga (kg)")
                ax_value.grid(True, alpha=0.3)

            if ax_rtt is not None:
                (line_rtt,) = ax_rtt.plot([], [], lw=1.6)
                ax_rtt.set_title("Latência de leitura (RTT)")
                ax_rtt.set_xlabel("Amostra")
                ax_rtt.set_ylabel("RTT (ms)")
                ax_rtt.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.show(block=False)

        count = 0
        while True:
            ok, value, raw, rtt_ms = _read_once(client, holding_start, unit_id, scale)
            count += 1

            if ok:
                if print_every <= 1 or (count % print_every) == 0:
                    print(f"Carga={value:.3f} kg (raw={raw}) | RTT={rtt_ms:.3f} ms")

                if plot_enabled and fig is not None and plt.fignum_exists(fig.number):
                    idx += 1
                    samples.append(value)
                    rtt_samples.append(rtt_ms)
                    sample_idx.append(idx)

                    if line_value is not None and ax_value is not None:
                        line_value.set_data(sample_idx, samples)
                        ax_value.relim()
                        ax_value.autoscale_view()

                    if line_rtt is not None and ax_rtt is not None:
                        line_rtt.set_data(sample_idx, rtt_samples)
                        ax_rtt.relim()
                        ax_rtt.autoscale_view()

                    plt.pause(0.001)
            else:
                if print_every <= 1 or (count % print_every) == 0:
                    print(f"Leitura inválida de holding registers | RTT={rtt_ms:.3f} ms")

            if interval > 0:
                time.sleep(interval)
    finally:
        try:
            client.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Cliente Modbus RTU para leer carga y medir latencia")
    parser.add_argument("--settings", default="settings.json", help="Caminho para settings.json")
    parser.add_argument("--port", help="Porta serial (override)")
    parser.add_argument("--baud", type=int, help="Baudrate (override)")
    parser.add_argument("--parity", choices=["N", "E", "O"], help="Paridade (override)")
    parser.add_argument("--unit", type=int, help="ID escravo (override)")
    parser.add_argument("--scale", type=int, default=1000, help="Fator de escala")
    parser.add_argument("--holding-start", type=int, default=1000, help="Holding start")
    parser.add_argument("--mode", choices=["live", "sweep"], default="live", help="live: lectura continua, sweep: compara intervalos")
    parser.add_argument("--interval", type=float, default=0.0, help="Intervalo de leitura (s)")
    parser.add_argument("--timeout", type=float, default=0.1, help="Timeout serial por requisição (s)")
    parser.add_argument("--plot-mode", choices=["value", "latency", "both"], default="both", help="Tipo de gráfico en modo live")
    parser.add_argument("--no-plot", action="store_true", help="Desabilitar gráfico")
    parser.add_argument("--window", type=int, default=300, help="Janela de amostras no gráfico")
    parser.add_argument("--print-every", type=int, default=10, help="Imprimir una de cada N lecturas")
    parser.add_argument("--sweep", type=str, default="0,0.001,0.002,0.005,0.01,0.02,0.05", help="Lista de intervalos (s) separada por coma para modo sweep")
    parser.add_argument("--sweep-seconds", type=float, default=8.0, help="Duración por intervalo en modo sweep")
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
        interval=args.interval,
        timeout=args.timeout,
        mode=args.mode,
        plot_mode=args.plot_mode,
        plot_enabled=not args.no_plot,
        window_size=args.window,
        print_every=max(1, int(args.print_every)),
        sweep_intervals=_parse_float_list(args.sweep),
        sweep_seconds=args.sweep_seconds,
    )


if __name__ == "__main__":
    main()
