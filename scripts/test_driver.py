"""
unified_test_driver.py
----------------------
Driver de Pruebas Robusto con Logging Completo y Manejo de Errores de API.
CORREGIDO: Manejo de fallo en NodeDiscovery en MSCL v67+.

USO:
    1. Asegúrate de que la carpeta 'MSCL' esté en la raíz.
    2. Ejecuta: python scripts/unified_test_driver.py
"""

import sys
import os
import time
import logging
import traceback

# --- 1. CONFIGURACIÓN DE LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler("test_driver.log", mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("TestDriver")

# --- 2. CARGA DE LIBRERÍA MSCL ---
def setup_mscl_environment():
    try:
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            base_path = os.path.abspath(os.path.join(current_dir, '..'))

        mscl_dir = os.path.join(base_path, 'MSCL', 'x64', 'Release')

        if mscl_dir not in sys.path:
            sys.path.insert(0, mscl_dir)
        
        if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
            if os.path.exists(mscl_dir):
                os.add_dll_directory(mscl_dir)

    except Exception as e:
        logger.critical(f"Error configurando entorno: {e}")

setup_mscl_environment()

try:
    import mscl
    # Convertimos a string explícitamente para evitar error en objeto Version
    logger.info(f"Librería MSCL cargada. Versión: {mscl.MSCL_VERSION}")
except ImportError as e:
    logger.critical(f"No se pudo importar 'mscl'. Detalle: {e}")
    sys.exit(1)
except Exception:
    logger.info("Librería MSCL cargada (Versión desconocida).")

# --- 3. PARÁMETROS ---
COM_PORT = "COM3"       # <--- CAMBIA ESTO SI ES NECESARIO
TARGET_RATE_HZ = 32     # Frecuencia deseada

def preparar_nodo(base_station, node_address):
    """
    Verifica conexión, asegura estado IDLE y verifica/aplica configuración.
    """
    logger.info(f"[{node_address}] Iniciando preparación del nodo...")
    
    try:
        node = mscl.WirelessNode(node_address, base_station)
        
        # A. PING
        logger.info(f"[{node_address}] Haciendo Ping...")
        ping_resp = node.ping()
        
        if not ping_resp.success():
            logger.error(f"[{node_address}] FALLO PING: El nodo no responde. Verifique batería/encendido.")
            return None
            
        logger.info(f"[{node_address}] Ping OK. RSSI Base: {ping_resp.baseRssi()} dBm")

        # B. FORZAR IDLE
        logger.info(f"[{node_address}] Forzando estado IDLE...")
        result = node.setToIdle()
        if not result.success():
             logger.warning(f"[{node_address}] SetToIdle devolvió fallo (puede que ya estuviera idle).")
        
        # C. VERIFICACIÓN CONFIGURACIÓN
        logger.info(f"[{node_address}] Leyendo config actual...")
        try:
            config = mscl.WirelessNodeConfig(node)
            current_rate = config.sampleRate()
            target_rate = mscl.SampleRate.Hertz(TARGET_RATE_HZ)
            
            logger.info(f"[{node_address}] Frecuencia actual: {current_rate.prettyStr()}")

            if current_rate.samples() != target_rate.samples():
                logger.warning(f"[{node_address}] Configurando a {target_rate.prettyStr()}...")
                config.sampleRate(target_rate)
                config.apply()
                logger.info(f"[{node_address}] Configuración aplicada.")
            else:
                logger.info(f"[{node_address}] Configuración correcta. Saltando escritura.")
                
        except Exception as e:
            logger.error(f"[{node_address}] Error leyendo/escribiendo config: {e}")
            
        return node

    except mscl.Error as e:
        logger.error(f"[{node_address}] Error MSCL Crítico: {e}")
        return None

def run_test():
    global COM_PORT
    connection = None
    base_station = None
    
    logger.info("="*50)
    logger.info("   TEST DRIVER MICROSTRAIN (UNIFICADO)")
    logger.info("="*50)

    user_port = input(f"Puerto COM [{COM_PORT}] (Enter para confirmar): ").strip()
    if user_port: COM_PORT = user_port

    try:
        # 1. CONEXIÓN BASE STATION
        logger.info(f"Conectando a BaseStation en {COM_PORT}...")
        connection = mscl.Connection.Serial(COM_PORT)
        base_station = mscl.BaseStation(connection)
        
        if not base_station.ping():
            logger.error("La BaseStation no responde (Ping fallido).")
            return

        # 2. LIMPIEZA
        logger.info("Desactivando Beacon previo...")
        try:
            base_station.disableBeacon()
        except:
            pass 

        # 3. DESCUBRIMIENTO (ROBUSTO)
        logger.info("Iniciando escaneo de nodos...")
        node_list = []
        
        try:
            # Intentamos usar el NodeDiscovery estándar
            discovery = mscl.NodeDiscovery(base_station)
            logger.info("Escuchando (5 segundos)... ENCIENDA LOS SENSORES.")
            discovery.start()
            time.sleep(5)
            discovery.stop()
            
            nodes_found = discovery.foundNodes()
            for n in nodes_found:
                addr = n.nodeAddress()
                rssi = n.radioStrength()
                logger.info(f"-> Detectado: {addr} [RSSI: {rssi}]")
                node_list.append(addr)
                
        except TypeError:
            logger.warning("ADVERTENCIA: La función de Auto-Descubrimiento falló (incompatibilidad de versión).")
            logger.warning("Pasando a modo manual.")
        except Exception as e:
            logger.error(f"Error en descubrimiento: {e}")

        # SI NO ENCONTRAMOS NODOS (O FALLÓ EL DISCOVERY), PEDIMOS MANUALMENTE
        if len(node_list) == 0:
            print("\n" + "!"*40)
            print(" No se detectaron nodos automáticamente.")
            print(" Por favor ingrese el ID del sensor (ej: 31849)")
            print("!"*40)
            manual = input(">> ID del Nodo: ").strip()
            if manual.isdigit():
                node_list.append(int(manual))
            else:
                logger.info("No se ingresó ID válido. Saliendo.")
                return

        # 4. PREPARACIÓN Y RED
        logger.info(f"Preparando red con {len(node_list)} nodos...")
        network = mscl.SyncSamplingNetwork(base_station)
        ready_count = 0

        for address in node_list:
            node_obj = preparar_nodo(base_station, address)
            if node_obj:
                logger.info(f"[{address}] Agregando a red...")
                network.addNode(node_obj)
                ready_count += 1
        
        if ready_count == 0:
            logger.error("Ningún nodo listo para iniciar.")
            return

        # 5. INICIO
        logger.info(f"Iniciando muestreo sincronizado...")
        try:
            network.startSampling()
            logger.info(">>> RED INICIADA. Beacon ACTIVO. <<<")
        except mscl.Error as e:
            logger.critical(f"Fallo al iniciar red: {e}")
            return

        # 6. BUCLE DE LECTURA
        logger.info("Leyendo datos... (CTRL+C para detener)")
        start_time = time.time()
        packet_count = 0
        
        while True:
            sweeps = base_station.getData(500)
            
            for sweep in sweeps:
                packet_count += 1
                nid = sweep.nodeAddress()
                
                vals = []
                for d in sweep.data():
                    if d.valid():
                        try:
                            v = d.as_float()
                            vals.append(f"{d.channelName()}:{v:.4f}")
                        except:
                            vals.append(f"{d.channelName()}:raw")
                
                print(f"RX [{nid}] | {', '.join(vals)}")

            if packet_count == 0 and (time.time() - start_time > 5):
                print("... Esperando datos (Verifique LED verde en nodo) ...")
                start_time = time.time()

    except KeyboardInterrupt:
        logger.info("\nDetenido por usuario.")
    except Exception as e:
        logger.critical(f"Error general: {e}")
        traceback.print_exc()
    finally:
        logger.info("Cerrando recursos...")
        if base_station:
            try:
                base_station.disableBeacon()
                logger.info("Beacon apagado.")
            except:
                pass
        if connection:
            connection.disconnect()
        input("Presiona ENTER para salir.")

if __name__ == "__main__":
    run_test()