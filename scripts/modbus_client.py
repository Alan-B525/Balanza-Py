"""
Cliente Modbus RTU – visualizador en tiempo real.
Abre una ventana de configuración simple y luego grafica la señal
en una ventana deslizante de 2 minutos.
"""
import json, os, sys, time, statistics
from collections import deque
from typing import List, Tuple
from pymodbus.client import ModbusSerialClient
from pymodbus.framer import FramerType


# ── Helpers ──────────────────────────────────────────────────────────────

def _list_ports() -> List[str]:
    try:
        import serial.tools.list_ports
        return sorted([p.device for p in serial.tools.list_ports.comports()])
    except Exception:
        return []

def _load_settings(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

import struct

def _decode_float32(hi: int, lo: int, swap_words: bool = False) -> float:
    if swap_words:
        hi, lo = lo, hi
    try:
        raw_bytes = struct.pack('>HH', hi & 0xFFFF, lo & 0xFFFF)
        return struct.unpack('>f', raw_bytes)[0]
    except Exception:
        return 0.0

_first_error_printed = False

from typing import List

def _read_once(client, address, unit_id, scale) -> Tuple[bool, float, List[float], float]:
    global _first_error_printed
    t0 = time.perf_counter()
    try:
        r = client.read_holding_registers(address, count=12, device_id=unit_id)
    except Exception as e:
        rtt_ms = (time.perf_counter() - t0) * 1000
        if not _first_error_printed:
            print(f"  [DIAG] Excepção: {type(e).__name__}: {e}")
            _first_error_printed = True
        return False, 0.0, [0.0] * 5, rtt_ms
    rtt_ms = (time.perf_counter() - t0) * 1000
    if r and hasattr(r, "registers") and len(r.registers) >= 12:
        _first_error_printed = False
        val_peso = _decode_float32(r.registers[0], r.registers[1], swap_words=False)
        angles = []
        for i in range(5):
            idx = 2 + i * 2
            ang_val = _decode_float32(r.registers[idx], r.registers[idx + 1], swap_words=False)
            angles.append(ang_val)
        return True, val_peso, angles, rtt_ms
    # La respuesta existe pero no tiene registros -> error Modbus
    if not _first_error_printed:
        is_err = getattr(r, 'isError', lambda: False)()
        print(f"  [DIAG] Resposta inválida: type={type(r).__name__}  isError={is_err}  obj={r}")
        _first_error_printed = True
    return False, 0.0, [0.0] * 5, rtt_ms


# ── Ventana de configuración simple ──────────────────────────────────────

def show_config(default_port="COM9", default_baud="115200",
                default_unit="1", default_print_ev="10") -> dict | None:
    import tkinter as tk
    from tkinter import ttk

    ports = _list_ports()
    if default_port not in ports:
        ports = [default_port] + ports

    result = {}

    root = tk.Tk()
    root.title("Modbus RTU – Configuração")
    root.resizable(False, False)

    BG, CARD    = "#1e293b", "#263348"
    FG, FG2     = "#f1f5f9", "#94a3b8"
    ACCENT      = "#3b82f6"
    SUCCESS     = "#22c55e"
    DANGER      = "#ef4444"
    fnt         = ("Segoe UI", 10)
    fnt_bold    = ("Segoe UI", 10, "bold")
    fnt_title   = ("Segoe UI", 14, "bold")
    fnt_btn     = ("Segoe UI", 11, "bold")

    root.configure(bg=BG)

    # Header
    hdr = tk.Frame(root, bg="#0f172a", pady=20)
    hdr.pack(fill="x")
    tk.Label(hdr, text="📡  Modbus RTU Live", bg="#0f172a", fg=FG, font=fnt_title).pack()
    tk.Label(hdr, text="Configure a conexão e inicie a leitura contínua",
             bg="#0f172a", fg=FG2, font=("Segoe UI", 9)).pack(pady=(2,0))

    # Card de parámetros
    card = tk.Frame(root, bg=CARD, padx=24, pady=20)
    card.pack(fill="x", padx=20, pady=16)

    def field(label_text, var, widget_fn):
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=5)
        tk.Label(row, text=label_text, bg=CARD, fg=FG2, font=fnt,
                 width=18, anchor="w").pack(side="left")
        w = widget_fn(row)
        w.pack(side="left")
        return w

    def entry(parent, var, w=14):
        return tk.Entry(parent, textvariable=var, width=w,
                        bg="#334155", fg=FG, insertbackground=FG,
                        relief="flat", bd=4, font=("Consolas", 10))

    def combo(parent, var, values, w=14):
        style = ttk.Style(); style.theme_use("default")
        style.configure("D.TCombobox", fieldbackground="#334155",
                        background="#334155", foreground=FG,
                        selectbackground=ACCENT, selectforeground=FG)
        cb = ttk.Combobox(parent, textvariable=var, values=values,
                          width=w, style="D.TCombobox", state="readonly")
        return cb

    v_port  = tk.StringVar(value=default_port)
    v_baud  = tk.StringVar(value=default_baud)
    v_unit  = tk.StringVar(value=default_unit)
    v_print = tk.StringVar(value=default_print_ev)

    field("Porta COM",           v_port,  lambda p: combo(p, v_port, ports, w=10))
    field("Baudrate",            v_baud,  lambda p: combo(p, v_baud,
          ["9600","19200","57600","115200","230400","460800","921600",
           "1500000","3000000"], w=12))
    field("Unit ID (escravo)",   v_unit,  lambda p: entry(p, v_unit, w=6))
    field("Imprimir 1 de cada N", v_print, lambda p: entry(p, v_print, w=6))

    tk.Label(card, text="Paridade: N  |  Stop bits: 1  |  Modo: Live  |  Registro: 1000  |  Formato: Float32",
             bg=CARD, fg=FG2, font=("Segoe UI", 8)).pack(anchor="w", pady=(10, 0))

    # Error label
    lbl_err = tk.Label(root, text="", bg=BG, fg=DANGER, font=("Segoe UI", 9))
    lbl_err.pack()

    # Botones
    btn_row = tk.Frame(root, bg=BG, pady=14)
    btn_row.pack(fill="x", padx=20)

    def on_cancel():
        root.destroy()

    def on_start():
        try:
            result.update({
                "port":        v_port.get().strip(),
                "baud":        int(v_baud.get()),
                "unit":        int(v_unit.get()),
                "print_every": max(1, int(v_print.get())),
            })
            root.destroy()
        except ValueError as e:
            lbl_err.config(text=f"⚠  {e}")

    tk.Button(btn_row, text="Cancelar", command=on_cancel,
              bg="#475569", fg=FG, font=fnt_btn, relief="flat",
              padx=16, pady=8, cursor="hand2",
              activebackground="#64748b", activeforeground=FG).pack(side="left")

    tk.Button(btn_row, text="▶  INICIAR LEITURA", command=on_start,
              bg=SUCCESS, fg="#fff", font=fnt_btn, relief="flat",
              padx=22, pady=8, cursor="hand2",
              activebackground="#16a34a", activeforeground="#fff").pack(side="right")

    # Centrar ventana
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h   = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    root.mainloop()
    return result if result else None


# ── Modo live con ventana deslizante 2 minutos ────────────────────────────

SLIDE_WINDOW_S = 120.0   # 2 minutos
CONSOLE_LINES  = 10      # líneas visibles en el panel consola

def run_live(client, address, unit_id, scale, print_every):
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec

    print(f"\n  Leitura contínua | janela={SLIDE_WINDOW_S:.0f}s | Ctrl+C para parar\n")

    ts_vals: deque = deque()          # (t, peso, angles_list)
    console: deque = deque(maxlen=CONSOLE_LINES)  # líneas de log

    def log(line: str):
        console.append(line)
        print(f"  {line}")

    # ── Layout ──────────────────────────────────────────────────────────
    plt.ion()
    fig = plt.figure(figsize=(13, 8))
    fig.patch.set_facecolor("#0f172a")
    # Tres filas: Carga (3), Ángulos (2.5), Consola (1)
    gs  = gridspec.GridSpec(3, 1, height_ratios=[3.0, 2.5, 1.2], hspace=0.35)
    gs.update(left=0.07, right=0.97, top=0.95, bottom=0.04)

    ax_val = fig.add_subplot(gs[0])
    ax_ang = fig.add_subplot(gs[1])
    ax_con = fig.add_subplot(gs[2])

    # Estilo gráfico principal (Carga)
    ax_val.set_facecolor("#1e293b")
    ax_val.tick_params(colors="#94a3b8", labelsize=8)
    ax_val.spines[:].set_color("#334155")
    ax_val.xaxis.label.set_color("#64748b")
    ax_val.yaxis.label.set_color("#64748b")
    ax_val.title.set_color("#e2e8f0")
    ax_val.grid(True, alpha=0.15, color="#334155")

    (line_val,) = ax_val.plot([], [], lw=2, color="#3b82f6")
    ax_val.set_title("Carga (janela deslizante: 2 min)", pad=6)
    ax_val.set_ylabel("Carga (kg)")
    ax_val.set_xlabel("")

    # Estilo gráfico secundario (Ángulos)
    ax_ang.set_facecolor("#1e293b")
    ax_ang.tick_params(colors="#94a3b8", labelsize=8)
    ax_ang.spines[:].set_color("#334155")
    ax_ang.xaxis.label.set_color("#64748b")
    ax_ang.yaxis.label.set_color("#64748b")
    ax_ang.title.set_color("#e2e8f0")
    ax_ang.grid(True, alpha=0.15, color="#334155")
    ax_ang.set_title("Ángulos de inclinación", pad=6)
    ax_ang.set_ylabel("Ángulos (°)")
    ax_ang.set_xlabel("")

    # 5 líneas para los 5 ángulos
    colors_ang = ["#ef4444", "#eab308", "#22c55e", "#a855f7", "#ec4899"] # Rojo, Amarillo, Verde, Púrpura, Rosa
    lines_ang = []
    for idx in range(5):
        line, = ax_ang.plot([], [], lw=1.5, color=colors_ang[idx], label=f"Ang {idx+1}")
        lines_ang.append(line)
    ax_ang.legend(loc="upper left", facecolor="#0f172a", edgecolor="#334155", labelcolor="#e2e8f0", fontsize=7)

    # Panel consola – sin ejes, fondo muy oscuro
    ax_con.set_facecolor("#020617")
    ax_con.set_xlim(0, 1); ax_con.set_ylim(0, 1)
    ax_con.tick_params(left=False, bottom=False,
                       labelleft=False, labelbottom=False)
    for sp in ax_con.spines.values():
        sp.set_color("#1e293b")

    txt_console = ax_con.text(
        0.01, 0.97, "",
        transform=ax_con.transAxes,
        va="top", ha="left",
        fontsize=8, fontfamily="monospace",
        color="#4ade80",          # verde terminal
        linespacing=1.5,
    )
    # Título del panel consola
    ax_con.text(0.005, 1.0, " EVENTOS",
                transform=ax_con.transAxes, va="bottom",
                fontsize=7, fontfamily="monospace",
                color="#334155")

    # ── Estado ──────────────────────────────────────────────────────────
    t_start       = time.perf_counter()
    t_last_stats  = t_start
    t_last_change = None
    last_raw      = None
    count         = 0
    stats_count   = 0
    errors_consec = 0
    n_changes     = 0
    intervals: list = []
    MAX_INTERVALS   = 60

    def _refresh_console():
        txt_console.set_text("\n".join(console))

    while True:
        now_s = time.perf_counter() - t_start
        ok, value, angles, rtt_ms = _read_once(client, address, unit_id, scale)
        count += 1; stats_count += 1

        if ok:
            errors_consec = 0
            ts_vals.append((now_s, value, angles))

            if value != last_raw:
                if last_raw is not None:
                    interval_s = now_s - t_last_change if t_last_change else 0.0
                    delta      = value - last_raw
                    n_changes += 1
                    intervals.append(interval_s)
                    if len(intervals) > MAX_INTERVALS:
                        intervals.pop(0)
                    freq = 1.0 / interval_s if interval_s > 0 else 0
                    ang_str = ", ".join([f"{a:.1f}°" for a in angles])
                    log(f"t={now_s:6.1f}s  ★  {value:>10.3f} kg"
                        f"  Δ={delta:>+8.3f}  int={interval_s*1000:5.0f}ms"
                        f"  {freq:.1f}Hz  #{n_changes} | Angs: [{ang_str}]")
                t_last_change = now_s
                last_raw      = value
            elif print_every <= 1 or (count % print_every) == 0:
                ang_str = ", ".join([f"{a:.1f}°" for a in angles])
                log(f"t={now_s:6.1f}s     {value:>10.3f} kg"
                    f"  RTT={rtt_ms:.1f}ms | Angs: [{ang_str}]")
        else:
            errors_consec += 1
            if print_every <= 1 or (count % print_every) == 0:
                log(f"t={now_s:6.1f}s  ✗  err  RTT={rtt_ms:.2f}ms  ({errors_consec})")

        # ── Actualizar figura ────────────────────────────────────────────
        if plt.fignum_exists(fig.number):
            x_right = max(SLIDE_WINDOW_S, now_s)
            x_left  = x_right - SLIDE_WINDOW_S
            while ts_vals and ts_vals[0][0] < x_left - 2.0:
                ts_vals.popleft()

            if ts_vals:
                xs = [p[0] for p in ts_vals]
                line_val.set_data(xs, [p[1] for p in ts_vals])
                ax_val.set_xlim(x_left, x_right)
                ax_val.relim(); ax_val.autoscale_view(scalex=False)

                # Actualizar las 5 líneas de ángulos
                for idx in range(5):
                    ys_ang = [p[2][idx] for p in ts_vals]
                    lines_ang[idx].set_data(xs, ys_ang)
                ax_ang.set_xlim(x_left, x_right)
                ax_ang.relim(); ax_ang.autoscale_view(scalex=False)

            _refresh_console()
            plt.pause(0.001)
        else:
            print("  Gráfico fechado. Encerrando...")
            break

        # Stats periódicas cada 5s
        now_wall = time.perf_counter()
        if now_wall - t_last_stats >= 5.0:
            rate  = stats_count / max(0.001, now_wall - t_last_stats)
            avg_i = (sum(intervals) / len(intervals)) if intervals else 0
            freq_s = f"{1/avg_i:.1f}Hz" if avg_i > 0 else "---"
            log(f"{'─'*12}  poll={rate:.0f}/s  "
                f"cambios={n_changes}  servidor≈{freq_s}  {'─'*8}")
            t_last_stats = now_wall
            stats_count  = 0




# ── Main ─────────────────────────────────────────────────────────────────

def main():
    # Buscar settings.json
    script_dir = os.path.dirname(os.path.abspath(__file__))
    settings_path = next(
        (p for p in [
            os.path.join(script_dir, "settings.json"),
            os.path.join(script_dir, "..", "settings.json"),
        ] if os.path.exists(p)),
        ""
    )
    settings = _load_settings(settings_path)

    # Permitir bypass de la ventana de configuración si se pasan parámetros por consola
    # Formato: python modbus_client.py [puerto] [baudrate] [unit_id] [print_every]
    if len(sys.argv) >= 3:
        port = sys.argv[1]
        try:
            baudrate = int(sys.argv[2])
        except ValueError:
            baudrate = 115200
        try:
            unit_id = int(sys.argv[3]) if len(sys.argv) >= 4 else 1
        except ValueError:
            unit_id = 1
        try:
            print_every = int(sys.argv[4]) if len(sys.argv) >= 5 else 10
        except ValueError:
            print_every = 10
            
        cfg = {
            "port": port,
            "baud": baudrate,
            "unit": unit_id,
            "print_every": print_every
        }
    else:
        cfg = show_config(
            default_port     = "COM9",
            default_baud     = "115200",
            default_unit     = "1",
            default_print_ev = "10",
        )
        if cfg is None:
            sys.exit(0)

    port      = cfg["port"]
    baudrate  = cfg["baud"]
    unit_id   = cfg["unit"]
    ADDRESS   = 1000
    SCALE     = 1000

    print(f"\n  Porta={port}  Baud={baudrate:,}  Unit={unit_id}  Reg={ADDRESS}  Escala={SCALE}")

    client = ModbusSerialClient(
        port=port, baudrate=baudrate, parity="N",
        stopbits=1, bytesize=8, timeout=0.1,
        framer=FramerType.RTU,
    )
    if not client.connect():
        print(f"  ✗ Não foi possível abrir {port}")
        sys.exit(1)
    print(f"  ✓ Conectado a {port}\n")

    try:
        run_live(client, ADDRESS, unit_id, SCALE, cfg["print_every"])
    except KeyboardInterrupt:
        print("\n  Interrompido.")
    finally:
        try:
            client.close()
        except Exception:
            pass
        print("  Conexão encerrada.\n")


if __name__ == "__main__":
    main()
