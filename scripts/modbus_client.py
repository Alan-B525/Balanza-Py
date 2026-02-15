"""
Cliente Modbus RTU – benchmark de velocidad de adquisición.

Modos de operación:
  live:  lectura continua con gráfico en tiempo real
  sweep: compara latencia en distintos intervalos de polling
  bench: benchmark puro de velocidad máxima (sin gráfico, máxima eficiencia)
"""
import argparse
import json
import os
import sys
import time
import statistics
from collections import deque
from typing import List, Tuple

from pymodbus.client import ModbusSerialClient


# ── Helpers ──────────────────────────────────────────────────────────────

def _load_settings(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
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


def _percentile(values: List[float], pct: float) -> float:
    """Percentile simple (nearest rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round(pct / 100.0 * (len(ordered) - 1)))
    return ordered[max(0, min(idx, len(ordered) - 1))]


def _call_read(client: ModbusSerialClient, address: int, count: int, unit_id: int):
    """Read holding registers, compatible con pymodbus 2.x / 3.x."""
    try:
        return client.read_holding_registers(address, count=count, slave=unit_id)
    except TypeError:
        try:
            return client.read_holding_registers(address, count=count, device_id=unit_id)
        except TypeError:
            return client.read_holding_registers(address, count=count, unit=unit_id)


def _read_once(client, address, unit_id, scale) -> Tuple[bool, float, int, float]:
    """Lee 2 registros, decodifica int32, retorna (ok, value, raw, rtt_ms)."""
    t0 = time.perf_counter()
    try:
        result = _call_read(client, address, 2, unit_id)
    except Exception:
        rtt_ms = (time.perf_counter() - t0) * 1000.0
        return False, 0.0, 0, rtt_ms
    rtt_ms = (time.perf_counter() - t0) * 1000.0

    if result and hasattr(result, "registers") and len(result.registers) >= 2:
        raw = _decode_int32(result.registers[0], result.registers[1])
        return True, raw / float(scale), raw, rtt_ms
    return False, 0.0, 0, rtt_ms


def _parse_float_list(text: str) -> List[float]:
    vals = []
    for chunk in str(text or "").split(','):
        c = chunk.strip()
        if c:
            vals.append(float(c))
    return vals


# ── Benchmark mode ───────────────────────────────────────────────────────

def run_bench(client, address, unit_id, scale, duration_s, warmup_s=1.0):
    """
    Benchmark puro: lectura sin pausa lo más rápido posible.
    Mide throughput real y latencia.
    """
    print(f"\n{'='*60}")
    print(f"  BENCHMARK DE VELOCIDAD MÁXIMA")
    print(f"  Duración: {duration_s}s  |  Warmup: {warmup_s}s")
    print(f"{'='*60}\n")

    # Warmup
    print(f"  Warmup ({warmup_s}s)...", end="", flush=True)
    t_warm = time.perf_counter() + warmup_s
    while time.perf_counter() < t_warm:
        _read_once(client, address, unit_id, scale)
    print(" OK")

    # Benchmark
    print(f"  Midiendo ({duration_s}s)...", end="", flush=True)
    rtts = []
    errors = 0
    values_changed = 0
    last_raw = None

    t_start = time.perf_counter()
    t_end = t_start + duration_s

    while time.perf_counter() < t_end:
        ok, _val, raw, rtt_ms = _read_once(client, address, unit_id, scale)
        rtts.append(rtt_ms)
        if ok:
            if last_raw is not None and raw != last_raw:
                values_changed += 1
            last_raw = raw
        else:
            errors += 1

    elapsed = time.perf_counter() - t_start
    total = len(rtts)
    ok_count = total - errors
    print(" OK\n")

    # Resultados
    throughput = total / elapsed
    mean_rtt = statistics.fmean(rtts) if rtts else 0
    median_rtt = statistics.median(rtts) if rtts else 0
    min_rtt = min(rtts) if rtts else 0
    max_rtt = max(rtts) if rtts else 0
    stdev_rtt = statistics.stdev(rtts) if len(rtts) > 1 else 0
    p95 = _percentile(rtts, 95)
    p99 = _percentile(rtts, 99)

    print(f"  ┌─────────────────────────────────────────────┐")
    print(f"  │  RESULTADOS                                 │")
    print(f"  ├─────────────────────────────────────────────┤")
    print(f"  │  Lecturas totales:  {total:>8d}                │")
    print(f"  │  Exitosas:          {ok_count:>8d} ({100*ok_count/total:.1f}%)        │")
    print(f"  │  Errores:           {errors:>8d}                │")
    print(f"  │  Valores cambiaron: {values_changed:>8d}                │")
    print(f"  │  Elapsed:           {elapsed:>8.2f} s              │")
    print(f"  │                                             │")
    print(f"  │  THROUGHPUT:        {throughput:>8.1f} reads/s       │")
    print(f"  │  Update rate:       {values_changed/elapsed:>8.1f} Hz            │")
    print(f"  │                                             │")
    print(f"  │  RTT medio:         {mean_rtt:>8.3f} ms            │")
    print(f"  │  RTT mediana:       {median_rtt:>8.3f} ms            │")
    print(f"  │  RTT min:           {min_rtt:>8.3f} ms            │")
    print(f"  │  RTT max:           {max_rtt:>8.3f} ms            │")
    print(f"  │  RTT stdev:         {stdev_rtt:>8.3f} ms            │")
    print(f"  │  RTT P95:           {p95:>8.3f} ms            │")
    print(f"  │  RTT P99:           {p99:>8.3f} ms            │")
    print(f"  └─────────────────────────────────────────────┘")

    # Veredicto
    print(f"\n  ➤ Velocidad máxima sostenible: ~{throughput:.0f} lecturas/s")
    if errors > 0:
        print(f"  ⚠ {errors} errores detectados — puede haber problemas de estabilidad")
    else:
        print(f"  ✓ Sin errores — la conexión es estable a esta velocidad")

    return throughput, mean_rtt


# ── Sweep mode ───────────────────────────────────────────────────────────

def run_sweep(client, address, unit_id, scale, intervals, sweep_seconds, plot_enabled):
    """Compara latencia para distintos intervalos de polling."""
    rows = []

    print(f"\n{'='*60}")
    print(f"  SWEEP DE INTERVALOS")
    print(f"  {len(intervals)} intervalos  |  {sweep_seconds}s por intervalo")
    print(f"{'='*60}\n")

    for i, interval in enumerate(intervals):
        freq_label = f"{1.0/interval:.0f} Hz" if interval > 0 else "MAX"
        print(f"  [{i+1}/{len(intervals)}] interval={interval:.4f}s ({freq_label})...", end="", flush=True)

        rtts = []
        errors = 0
        last_raw = None
        values_changed = 0

        t_start = time.perf_counter()
        t_end = t_start + max(0.5, sweep_seconds)

        while time.perf_counter() < t_end:
            ok, _val, raw, rtt_ms = _read_once(client, address, unit_id, scale)
            rtts.append(rtt_ms)
            if ok:
                if last_raw is not None and raw != last_raw:
                    values_changed += 1
                last_raw = raw
            else:
                errors += 1
            if interval > 0:
                time.sleep(interval)

        elapsed = max(1e-6, time.perf_counter() - t_start)
        total = len(rtts)
        ok_count = total - errors

        row = {
            'interval': interval,
            'freq_hz': (1.0 / interval) if interval > 0 else 0.0,
            'samples': total,
            'ok_pct': (100.0 * ok_count / total) if total else 0.0,
            'errors': errors,
            'mean_rtt': statistics.fmean(rtts) if rtts else 0.0,
            'median_rtt': statistics.median(rtts) if rtts else 0.0,
            'p95_rtt': _percentile(rtts, 95),
            'p99_rtt': _percentile(rtts, 99),
            'max_rtt': max(rtts) if rtts else 0.0,
            'min_rtt': min(rtts) if rtts else 0.0,
            'throughput': total / elapsed,
            'update_hz': values_changed / elapsed,
        }
        rows.append(row)
        print(f" {total} lecturas, RTT={row['mean_rtt']:.1f}ms, throughput={row['throughput']:.0f}/s")

    # Tabla de resultados
    print(f"\n{'='*120}")
    print(f"  {'interval':>10s} | {'target':>8s} | {'samples':>7s} | {'ok%':>6s} | {'errors':>6s} | "
          f"{'mean_rtt':>9s} | {'p95_rtt':>9s} | {'p99_rtt':>9s} | {'max_rtt':>9s} | {'throughput':>10s} | {'updates':>10s}")
    print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*7}-+-{'-'*6}-+-{'-'*6}-+-"
          f"{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*10}-+-{'-'*10}")
    for r in rows:
        freq_str = f"{r['freq_hz']:.0f} Hz" if r['freq_hz'] > 0 else "MAX"
        err_str = f"{r['errors']}" if r['errors'] == 0 else f"⚠{r['errors']}"
        print(f"  {r['interval']:>10.4f} | {freq_str:>8s} | {r['samples']:>7d} | {r['ok_pct']:>5.1f}% | {err_str:>6s} | "
              f"{r['mean_rtt']:>8.2f}ms | {r['p95_rtt']:>8.2f}ms | {r['p99_rtt']:>8.2f}ms | {r['max_rtt']:>8.2f}ms | "
              f"{r['throughput']:>9.1f}/s | {r['update_hz']:>9.1f} Hz")
    print(f"  {'='*118}\n")

    # Recomendación
    best = max(rows, key=lambda r: r['throughput'])
    print(f"  ➤ Mejor throughput: {best['throughput']:.0f} lecturas/s (interval={best['interval']:.4f}s)")
    stable = [r for r in rows if r['ok_pct'] >= 99.9 and r['errors'] == 0]
    if stable:
        fastest_stable = max(stable, key=lambda r: r['throughput'])
        print(f"  ➤ Mejor estable (0 errores): {fastest_stable['throughput']:.0f} lecturas/s (interval={fastest_stable['interval']:.4f}s)")

    # Plot
    if plot_enabled and rows:
        try:
            import matplotlib.pyplot as plt
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

            throughputs = [r['throughput'] for r in rows]
            means = [r['mean_rtt'] for r in rows]
            p95s = [r['p95_rtt'] for r in rows]
            labels = [f"{r['interval']:.3f}s" for r in rows]

            # Throughput bar chart
            colors = ['#22c55e' if r['errors'] == 0 else '#ef4444' for r in rows]
            bars = ax1.bar(range(len(rows)), throughputs, color=colors, alpha=0.85)
            ax1.set_xlabel('Intervalo')
            ax1.set_ylabel('Throughput (lecturas/s)')
            ax1.set_title('Throughput por intervalo')
            ax1.set_xticks(range(len(rows)))
            ax1.set_xticklabels(labels, rotation=45, ha='right')
            ax1.grid(axis='y', alpha=0.3)
            for bar, val in zip(bars, throughputs):
                ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                         f'{val:.0f}', ha='center', va='bottom', fontsize=8)

            # RTT line chart
            ax2.plot(range(len(rows)), means, 'o-', label='RTT medio', color='#3b82f6')
            ax2.plot(range(len(rows)), p95s, 's--', label='RTT P95', color='#f59e0b')
            ax2.set_xlabel('Intervalo')
            ax2.set_ylabel('RTT (ms)')
            ax2.set_title('Latencia Modbus por intervalo')
            ax2.set_xticks(range(len(rows)))
            ax2.set_xticklabels(labels, rotation=45, ha='right')
            ax2.grid(alpha=0.3)
            ax2.legend()

            plt.tight_layout()
            plt.show()
        except Exception as e:
            print(f"  (Gráfico no disponible: {e})")


# ── Live mode ────────────────────────────────────────────────────────────

def run_live(client, address, unit_id, scale, interval, plot_mode, plot_enabled,
             window_size, print_every):
    """Lectura continua con gráfico en tiempo real."""
    print(f"\n  Modo live | intervalo={interval}s | Ctrl+C para parar\n")

    samples = deque(maxlen=max(10, window_size))
    rtt_samples = deque(maxlen=max(10, window_size))
    sample_idx = deque(maxlen=max(10, window_size))
    idx = 0

    fig = ax_value = ax_rtt = line_value = line_rtt = None
    if plot_enabled:
        try:
            import matplotlib.pyplot as plt
            plt.ion()
            if plot_mode == 'latency':
                fig, ax_rtt = plt.subplots(figsize=(9, 4))
            elif plot_mode == 'both':
                fig, (ax_value, ax_rtt) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
            else:
                fig, ax_value = plt.subplots(figsize=(9, 4))

            if ax_value is not None:
                (line_value,) = ax_value.plot([], [], lw=2, color='#3b82f6')
                ax_value.set_title("Señal recibida vía Modbus RTU")
                ax_value.set_ylabel("Carga (kg)")
                ax_value.grid(True, alpha=0.3)

            if ax_rtt is not None:
                (line_rtt,) = ax_rtt.plot([], [], lw=1.6, color='#f59e0b')
                ax_rtt.set_title("Latencia RTT")
                ax_rtt.set_xlabel("Muestra")
                ax_rtt.set_ylabel("RTT (ms)")
                ax_rtt.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.show(block=False)
        except Exception as e:
            print(f"  (Gráfico no disponible: {e})")
            plot_enabled = False

    count = 0
    errors_consecutive = 0
    t_stats = time.perf_counter()
    stats_count = 0

    while True:
        ok, value, raw, rtt_ms = _read_once(client, address, unit_id, scale)
        count += 1
        stats_count += 1

        if ok:
            errors_consecutive = 0
            if print_every <= 1 or (count % print_every) == 0:
                print(f"  Carga={value:.3f} kg (raw={raw}) | RTT={rtt_ms:.3f} ms")

            if plot_enabled and fig is not None:
                try:
                    import matplotlib.pyplot as plt
                    if plt.fignum_exists(fig.number):
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
                except Exception:
                    pass
        else:
            errors_consecutive += 1
            if print_every <= 1 or (count % print_every) == 0:
                print(f"  ⚠ Lectura inválida | RTT={rtt_ms:.3f} ms (errores consecutivos: {errors_consecutive})")

        # Stats periódicas
        now = time.perf_counter()
        if now - t_stats >= 5.0:
            rate = stats_count / (now - t_stats)
            print(f"  ── Rate: {rate:.1f} lecturas/s (últimos {now-t_stats:.1f}s) ──")
            t_stats = now
            stats_count = 0

        if interval > 0:
            time.sleep(interval)


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cliente Modbus RTU – benchmark de velocidad",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Lectura continua con gráfico
  python modbus_client.py --port COM9 --baud 3000000

  # Benchmark de velocidad máxima (10 segundos)
  python modbus_client.py --port COM9 --baud 3000000 --mode bench --duration 10

  # Sweep de intervalos para encontrar velocidad óptima
  python modbus_client.py --port COM9 --baud 3000000 --mode sweep --sweep "0,0.001,0.002,0.005,0.01"

  # Lectura rápida sin gráfico para máxima velocidad
  python modbus_client.py --port COM9 --baud 3000000 --interval 0 --no-plot --print-every 50
""")

    # Conexión
    parser.add_argument("--settings", default="../settings.json", help="Path a settings.json")
    parser.add_argument("--port", help="Puerto serial (override)")
    parser.add_argument("--baud", type=int, help="Baudrate (override)")
    parser.add_argument("--parity", choices=["N", "E", "O"], help="Paridad (override)")
    parser.add_argument("--unit", type=int, help="ID esclavo Modbus (override)")
    parser.add_argument("--timeout", type=float, default=0.1, help="Timeout serial por request (s)")

    # Modbus
    parser.add_argument("--holding-start", type=int, default=1000, help="Dirección del primer holding register")
    parser.add_argument("--scale", type=int, default=1000, help="Factor de escala (valor_real = raw / scale)")

    # Modo de operación
    parser.add_argument("--mode", choices=["live", "sweep", "bench"], default="live",
                        help="live: lectura continua | sweep: comparar intervalos | bench: velocidad máxima")
    parser.add_argument("--interval", type=float, default=0.0, help="Intervalo entre lecturas (s), 0=sin pausa")

    # Live mode
    parser.add_argument("--plot-mode", choices=["value", "latency", "both"], default="value",
                        help="Tipo de gráfico en modo live")
    parser.add_argument("--no-plot", action="store_true", help="Desactivar gráfico")
    parser.add_argument("--window", type=int, default=300, help="Ventana de muestras en el gráfico")
    parser.add_argument("--print-every", type=int, default=10, help="Imprimir 1 de cada N lecturas")

    # Sweep mode
    parser.add_argument("--sweep", type=str, default="0,0.001,0.002,0.005,0.01,0.02,0.05",
                        help="Intervalos (s) separados por coma para sweep")
    parser.add_argument("--sweep-seconds", type=float, default=8.0, help="Duración por intervalo en sweep (s)")

    # Bench mode
    parser.add_argument("--duration", type=float, default=10.0, help="Duración del benchmark (s)")
    parser.add_argument("--warmup", type=float, default=1.0, help="Warmup antes del benchmark (s)")

    args = parser.parse_args()

    # Cargar settings
    settings_path = os.path.abspath(args.settings)
    settings = _load_settings(settings_path)
    t = settings.get("transmissao", {}) if isinstance(settings, dict) else {}

    port = args.port or t.get("porta") or settings.get("serial_port") or "COM9"
    baudrate = int(args.baud or t.get("velocidade") or settings.get("baudrate") or 115200)
    parity = args.parity or _parity_from_text(t.get("paridade") or settings.get("paridade"))
    unit_id = int(args.unit or t.get("id_escravo_pc") or settings.get("id_escravo_pc") or 1)

    # Banner
    print(f"\n  ╔═══════════════════════════════════════════════╗")
    print(f"  ║  Modbus RTU Client – Speed Tester             ║")
    print(f"  ╠═══════════════════════════════════════════════╣")
    print(f"  ║  Puerto:    {port:<36s}║")
    print(f"  ║  Baudrate:  {baudrate:<36,d}║")
    print(f"  ║  Paridad:   {parity:<36s}║")
    print(f"  ║  Unit ID:   {unit_id:<36d}║")
    print(f"  ║  Registro:  {args.holding_start:<36d}║")
    print(f"  ║  Modo:      {args.mode:<36s}║")
    print(f"  ╚═══════════════════════════════════════════════╝\n")

    # Conectar
    client = ModbusSerialClient(
        port=port,
        baudrate=baudrate,
        parity=parity,
        stopbits=1,
        bytesize=8,
        timeout=max(0.001, args.timeout),
    )

    if not client.connect():
        print(f"  ✗ No se pudo abrir el puerto {port}")
        sys.exit(1)
    print(f"  ✓ Conectado a {port}")

    try:
        # Test inicial de comunicación
        ok, val, _raw, rtt = _read_once(client, args.holding_start, unit_id, args.scale)
        if ok:
            print(f"  ✓ Comunicación OK — primera lectura: {val:.3f} kg, RTT={rtt:.1f}ms\n")
        else:
            print(f"  ⚠ Primera lectura falló (RTT={rtt:.1f}ms) — verificar configuración\n")

        if args.mode == "bench":
            run_bench(client, args.holding_start, unit_id, args.scale,
                      args.duration, args.warmup)

        elif args.mode == "sweep":
            run_sweep(client, args.holding_start, unit_id, args.scale,
                      _parse_float_list(args.sweep), args.sweep_seconds,
                      not args.no_plot)

        else:  # live
            run_live(client, args.holding_start, unit_id, args.scale,
                     args.interval, args.plot_mode, not args.no_plot,
                     args.window, max(1, args.print_every))

    except KeyboardInterrupt:
        print("\n\n  Interrumpido por el usuario.")
    finally:
        try:
            client.close()
        except Exception:
            pass
        print("  Conexión cerrada.\n")


if __name__ == "__main__":
    main()
