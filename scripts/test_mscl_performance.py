# -*- coding: utf-8 -*-
"""
test_mscl_performance.py - Test de Rendimiento de Adquisición MSCL
Optimizado con baudrate configurable, período de warmup y estadísticas estadísticas avanzadas (desviación estándar, jitter de latencia).
"""

import sys
import os
import time
import argparse
import traceback
import statistics

# Configurar rutas para importar módulos locales
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

import config

# Cargar MSCL
MSCL_PATH = os.path.join(project_root, "MSCL", "x64", "Release")
if os.path.exists(MSCL_PATH) and MSCL_PATH not in sys.path:
    sys.path.insert(0, MSCL_PATH)

try:
    import mscl
    MSCL_AVAILABLE = True
except ImportError:
    MSCL_AVAILABLE = False
    print("ERROR: Librería MSCL no encontrada.")


def run_performance_test(port, node_id, baudrate=3000000, duration_s=15, warmup_s=0.5):
    if not MSCL_AVAILABLE:
        return

    polling_intervals = [30, 20, 10, 5, 2, 1]
    
    print(f"\n{'='*60}")
    print(f"TEST DE RENDIMIENTO MSCL AVANZADO")
    print(f"Puerto: {port} | Baudrate: {baudrate} bps | Nodo: {node_id}")
    print(f"Intervalos a probar: {polling_intervals} ms")
    print(f"Período de Warmup: {warmup_s} s | Duración por test: {duration_s} s")
    print(f"{'='*60}\n")

    try:
        # Conexión con baudrate explícito
        connection = mscl.Connection.Serial(port, baudrate)
        base_station = mscl.BaseStation(connection)
        node = mscl.WirelessNode(node_id, base_station)

        print(f"[*] Conectado a {port} a {baudrate} bps")
        
        # Iniciar red
        print("[*] Sincronizando red...")
        network = mscl.SyncSamplingNetwork(base_station)
        network.addNode(node)
        network.applyConfiguration()
        network.startSampling()
        
        for poll_ms in polling_intervals:
            print(f"\n>>> Probando polling de {poll_ms}ms...")
            poll_interval_s = poll_ms / 1000.0
            
            # Período de Warmup (descartar primeras muestras)
            warmup_end = time.time() + warmup_s
            print(f"  [*] Calentando red durante {warmup_s}s...")
            while time.time() < warmup_end:
                try:
                    base_station.getData(poll_ms)
                except Exception:
                    pass
                time.sleep(0.001)

            total_sweeps = 0
            total_points = 0
            sweeps_counts = []  # Puntos por sweep
            polls_data = []     # Puntos por consulta (poll)
            poll_deltas = []    # Tiempos reales entre polls (para jitter)
            
            start_test = time.time()
            end_test = start_test + duration_s
            last_poll = time.time()

            while time.time() < end_test:
                now = time.time()
                if (now - last_poll) >= poll_interval_s:
                    delta = now - last_poll
                    poll_deltas.append(delta)
                    try:
                        # Timeout igual al intervalo de polling
                        sweeps = base_station.getData(poll_ms)
                        
                        points_this_poll = 0
                        for sweep in sweeps:
                            total_sweeps += 1
                            data_points = sweep.data()
                            points_in_sweep = len(data_points)
                            
                            # Informar canales encontrados una sola vez
                            if not hasattr(run_performance_test, 'channels_reported'):
                                ch_names = [dp.channelName() for dp in data_points]
                                print(f"\n[*] Canales detectados: {ch_names}")
                                run_performance_test.channels_reported = True

                            points_this_poll += points_in_sweep
                            total_points += points_in_sweep
                            sweeps_counts.append(points_in_sweep)
                        
                        polls_data.append(points_this_poll)
                        print(f"  Total Puntos: {total_points} | Sweeps: {total_sweeps}", end='\r')
                        
                    except Exception:
                        pass
                    
                    last_poll = time.time()
                else:
                    time.sleep(0.0001) # Ultra-short sleep

            actual_duration = time.time() - start_test
            
            # --- Estadísticas de Sweeps ---
            avg_pts_per_sweep = statistics.mean(sweeps_counts) if sweeps_counts else 0
            std_pts_per_sweep = statistics.stdev(sweeps_counts) if len(sweeps_counts) > 1 else 0
            
            # --- Estadísticas por Consulta (Poll) ---
            total_polls = len(polls_data)
            avg_points_per_poll = statistics.mean(polls_data) if polls_data else 0
            std_points_per_poll = statistics.stdev(polls_data) if len(polls_data) > 1 else 0
            max_points_per_poll = max(polls_data) if polls_data else 0
            min_points_per_poll = min(polls_data) if polls_data else 0

            # --- Estadísticas de Jitter (Variación de Latencia de Polling) ---
            # En segundos, convertir a ms para legibilidad
            poll_deltas_ms = [d * 1000.0 for d in poll_deltas]
            avg_latency_ms = statistics.mean(poll_deltas_ms) if poll_deltas_ms else 0
            std_latency_ms = statistics.stdev(poll_deltas_ms) if len(poll_deltas_ms) > 1 else 0
            max_latency_ms = max(poll_deltas_ms) if poll_deltas_ms else 0
            min_latency_ms = min(poll_deltas_ms) if poll_deltas_ms else 0

            hz_real = total_points / actual_duration
            
            print(f"\n--- RESULTADO POLLING {poll_ms}ms ---")
            print(f"  Frecuencia Muestreo Real: {hz_real:.2f} Hz")
            print(f"  Total Sweeps: {total_sweeps} | Total Puntos: {total_points} | Consultas Totales: {total_polls}")
            print(f"  Puntos/Sweep  -> Promedio: {avg_pts_per_sweep:.2f} | Desv. Est: {std_pts_per_sweep:.2f}")
            print(f"  Puntos/Poll   -> Promedio: {avg_points_per_poll:.2f} | Desv. Est: {std_points_per_poll:.2f} | Min: {min_points_per_poll} | Max: {max_points_per_poll}")
            print(f"  Latencia/Poll -> Promedio: {avg_latency_ms:.2f} ms | Jitter (Desv. Est): {std_latency_ms:.2f} ms | Min: {min_latency_ms:.2f} ms | Max: {max_latency_ms:.2f} ms")

        # Limpieza final
        print(f"\n{'='*60}")
        print("[*] Finalizando muestreo...")
        base_station.disableBeacon()
        node.setToIdle()
        connection.disconnect()
        print("[*] Test finalizado con éxito.")

    except Exception:
        print(f"\n[ERROR] Falló el test:")
        print(traceback.format_exc())


if __name__ == "__main__":
    # Intentamos cargar settings para obtener defaults convenientes
    settings = config.load_settings()
    default_port = settings.get('gateway', {}).get('porta', 'COM3')
    default_baud = int(settings.get('transmissao', {}).get('velocidade', config.BAUDRATE))
    
    default_node = 0
    if settings.get('nodes'):
        try:
            first_node_key = next(iter(settings['nodes']))
            default_node = settings['nodes'][first_node_key].get('id', 0)
        except Exception:
            pass

    parser = argparse.ArgumentParser(description='Test de Performance MSCL')
    parser.add_argument('--port', type=str, default=default_port, help=f'Puerto COM (default: {default_port})')
    parser.add_argument('--baudrate', type=int, default=default_baud, help=f'Baudrate (default: {default_baud})')
    parser.add_argument('--node', type=int, default=default_node, help=f'ID del Nodo (default: {default_node})')
    parser.add_argument('--duration', type=int, default=10, help='Segundos por cada intervalo de polling (default: 10)')
    parser.add_argument('--warmup', type=float, default=0.5, help='Segundos de warmup antes del muestreo (default: 0.5)')

    args = parser.parse_args()

    # Informar al usuario si estamos usando valores por defecto de settings.json
    if args.port == default_port:
        print(f"[*] Usando puerto por defecto de settings.json: {args.port}")
    if args.baudrate == default_baud:
        print(f"[*] Usando baudrate por defecto de settings.json: {args.baudrate} bps")
    if args.node == default_node and args.node != 0:
        print(f"[*] Usando Nodo ID por defecto de settings.json: {args.node}")

    if args.node == 0:
        print("\nERROR: No se encontró ID de nodo. Use --node <ID>")
        print("Ejemplo: python scripts/test_mscl_performance.py --node 4248 --port COM4")
        sys.exit(1)

    run_performance_test(args.port, args.node, args.baudrate, args.duration, args.warmup)
    input("\nPresione Enter para salir...")
