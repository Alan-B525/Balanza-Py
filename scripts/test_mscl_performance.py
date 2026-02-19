# -*- coding: utf-8 -*-
"""
test_mscl_performance.py - Test de Rendimiento de Adquisición MSCL
Optimizado para evaluar puntos por sweep en diferentes intervalos de polling.
"""

import sys
import os
import time
import argparse
import traceback

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

def run_performance_test(port, node_id, duration_s=30):
    if not MSCL_AVAILABLE: return

    polling_intervals = [30, 20, 10, 5, 2, 1]
    
    print(f"\n{'='*50}")
    print(f"TEST DE RENDIMIENTO MSCL (CONSOLA)")
    print(f"Puerto: {port} | Nodo: {node_id}")
    print(f"Intervalos a probar: {polling_intervals} ms")
    print(f"Duración por test: {duration_s} s")
    print(f"{'='*50}\n")

    try:
        # Conexión sin baudrate fijo (MSCL auto-detecta o usa default el gateway)
        connection = mscl.Connection.Serial(port)
        base_station = mscl.BaseStation(connection)
        node = mscl.WirelessNode(node_id, base_station)

        print(f"[*] Conectado a {port}")
        
        # Iniciar red (Asumimos frecuencia ya configurada en SensorConnect)
        print("[*] Sincronizando red...")
        network = mscl.SyncSamplingNetwork(base_station)
        network.addNode(node)
        network.applyConfiguration()
        network.startSampling()
        
        for poll_ms in polling_intervals:
            print(f"\n>>> Probando polling de {poll_ms}ms...")
            poll_interval_s = poll_ms / 1000.0
            
            total_sweeps = 0
            total_points = 0
            sweeps_counts = [] # Puntos por sweep
            polls_data = []    # Puntos por consulta (poll)
            
            start_test = time.time()
            end_test = start_test + duration_s
            last_poll = time.time()

            while time.time() < end_test:
                if (time.time() - last_poll) >= poll_interval_s:
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
            avg_pts_per_sweep = sum(sweeps_counts) / len(sweeps_counts) if sweeps_counts else 0
            
            # --- NUEVAS ESTADÍSTICAS POR CONSULTA ---
            total_polls = len(polls_data) # Necesitamos guardar los counts por poll
            avg_sweeps_per_poll = total_sweeps / total_polls if total_polls else 0
            avg_points_per_poll = total_points / total_polls if total_polls else 0
            max_points_per_poll = max(polls_data) if polls_data else 0
            # ----------------------------------------

            hz_real = total_points / actual_duration
            
            print(f"\n--- RESULTADO {poll_ms}ms ---")
            print(f"  Frecuencia Real: {hz_real:.2f} Hz")
            print(f"  Total Sweeps: {total_sweeps} | Total Puntos: {total_points}")
            print(f"  Promedio Sweeps por Poll: {avg_sweeps_per_poll:.2f}")
            print(f"  Promedio Puntos por Poll: {avg_points_per_poll:.2f}")
            print(f"  Max Puntos en un solo Poll: {max_points_per_poll}")
            print(f"  (Promedio puntos/sweep: {avg_pts_per_sweep:.2f})")

        # Limpieza final
        print(f"\n{'='*50}")
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
    
    default_node = 0
    if settings.get('nodes'):
        try:
            # Buscamos el primer nodo configurado
            first_node_key = next(iter(settings['nodes']))
            default_node = settings['nodes'][first_node_key].get('id', 0)
        except Exception:
            pass

    parser = argparse.ArgumentParser(description='Test de Performance MSCL')
    parser.add_argument('--port', type=str, default=default_port, help=f'Puerto COM (default: {default_port})')
    parser.add_argument('--node', type=int, default=default_node, help=f'ID del Nodo (default: {default_node})')
    parser.add_argument('--duration', type=int, default=15, help='Segundos por cada intervalo de polling')

    args = parser.parse_args()

    # Informar al usuario si estamos usando valores por defecto de settings.json
    if args.port == default_port:
        print(f"[*] Usando puerto por defecto de settings.json: {args.port}")
    if args.node == default_node and args.node != 0:
        print(f"[*] Usando Nodo ID por defecto de settings.json: {args.node}")

    if args.node == 0:
        print("\nERROR: No se encontró ID de nodo. Use --node <ID>")
        print("Ejemplo: python scripts/test_mscl_performance.py --node 4248 --port COM4")
        sys.exit(1)

    run_performance_test(args.port, args.node, args.duration)
    input("\nPresione Enter para salir...")
