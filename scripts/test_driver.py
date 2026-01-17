"""
unified_test_driver.py
----------------------
Script "todo en uno" para probar la conectividad y el muestreo sincronizado de MicroStrain.
CORREGIDO: Manejo de versión y robustez en desconexión.

USO:
    1. Asegúrate de que la carpeta 'MSCL' esté en la raíz del proyecto.
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
    """Configura las rutas para importar MSCL correctamente."""
    try:
        # Detectar si corre como script o ejecutable congelado
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            base_path = os.path.abspath(os.path.join(current_dir, '..'))

        mscl_dir = os.path.join(base_path, 'MSCL', 'x64', 'Release')

        if mscl_dir not in sys.path:
            sys.path.insert(0, mscl_dir)
        
        # Carga explícita de DLLs para Windows (Python 3.8+)
        if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
            if os.path.exists(mscl_dir):
                os.add_dll_directory(mscl_dir)
            else:
                logger.warning(f"No se encontró directorio MSCL en: {mscl_dir}")

    except Exception as e:
        logger.critical(f"Error configurando entorno: {e}")

# Ejecutar setup antes de importar
setup_mscl_environment()

try:
    import mscl
    # CORRECCIÓN: Convertir objeto Version a string implícitamente
    logger.info(f"Librería MSCL cargada. Versión: {mscl.MSCL_VERSION}")
except ImportError as e:
    logger.critical(f"No se pudo importar 'mscl'. Detalle: {e}")
    logger.info("Verifique que la carpeta MSCL/x64/Release exista y tenga permisos.")
    sys.exit(1)
except AttributeError:
    # Fallback si MSCL_VERSION no existe en versiones muy viejas
    logger.info("Librería MSCL cargada (Versión desconocida).")

# --- 3. PARÁMETROS GLOBALES ---
COM_PORT = "COM3"       # <--- PUERTO POR DEFECTO
TARGET_RATE_HZ = 0.5     # Frecuencia deseada

def preparar_nodo(base_station, node_address):
    """
    Verifica conexión, asegura estado IDLE y verifica/aplica configuración.
    """
    logger.info(f"[{node_address}] Iniciando preparación del nodo...")
    
    try:
        node = mscl.WirelessNode(node_address, base_station)
        
        # A. PING
        # MSCL intentará despertar al nodo si está en sleep
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
        
        # C. VERIFICACIÓN CONFIGURACIÓN (Optimización)
        logger.info(f"[{node_address}] Leyendo config actual...")
        try:
            config = mscl.WirelessNodeConfig(node)
            current_rate = config.sampleRate()
            target_rate = mscl.SampleRate.Hertz(TARGET_RATE_HZ)
            
            logger.info(f"[{node_address}] Frecuencia actual: {current_rate.prettyStr()}")

            if current_rate.samples() != target_rate.samples():
                logger.warning(f"[{node_address}] Configurando a {target_rate.prettyStr()}...")
                config.sampleRate(target_rate)
                # Opcional: configurar canales activos aquí
                config.apply()
                logger.info(f"[{node_address}] Configuración aplicada.")
            else:
                logger.info(f"[{node_address}] Configuración correcta. Saltando escritura.")
                
        except Exception as e:
            logger.error(f"[{node_address}] Error leyendo/escribiendo config: {e}")
            # Continuamos aunque falle config, quizás podamos medir igual
            
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

    # Selección de puerto (timeout simple o input)
    print(f"\nPuerto configurado: {COM_PORT}")
    sel = input(f"Presione ENTER para usar {COM_PORT} o escriba el nuevo (ej: COM4): ").strip()
    if sel: COM_PORT = sel

    try:
        # 1. CONEXIÓN BASE STATION
        logger.info(f"Conectando a BaseStation en {COM_PORT}...")
        connection = mscl.Connection.Serial(COM_PORT)
        base_station = mscl.BaseStation(connection)
        
        # Verificar comunicación con la base
        if not base_station.ping():
            logger.error("La BaseStation no responde (Ping fallido).")
            return

        # 2. LIMPIEZA DE ENTORNO
        logger.info("Desactivando Beacon previo...")
        try:
            base_station.disableBeacon()
        except:
            pass # Ignoramos si ya estaba apagado

        # 3. DESCUBRIMIENTO
        logger.info("Escaneando nodos (5 seg)... ENCIENDA LOS SENSORES.")
        discovery = mscl.NodeDiscovery(base_station)
        discovery.start()
        time.sleep(5)
        discovery.stop()
        
        nodes_found = discovery.foundNodes()
        node_list = []
        
        if len(nodes_found) == 0:
            logger.warning("No se encontraron nodos automáticamente.")
            manual = input(">> Ingrese ID manual (o ENTER para salir): ")
            if manual.isdigit():
                node_list.append(int(manual))
            else:
                logger.info("Abortando test.")
                return
        else:
            for n in nodes_found:
                addr = n.nodeAddress()
                rssi = n.radioStrength()
                logger.info(f"Detectado: {addr} [RSSI: {rssi}]")
                node_list.append(addr)

        # 4. PREPARACIÓN Y RED
        logger.info("Preparando Red Sincronizada...")
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
        logger.info(f"Iniciando muestreo con {ready_count} nodos...")
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
            sweeps = base_station.getData(500) # Timeout 500ms
            
            for sweep in sweeps:
                packet_count += 1
                nid = sweep.nodeAddress()
                ts = sweep.timestamp().nanoseconds()
                
                # Formatear datos
                vals = []
                for d in sweep.data():
                    if d.valid():
                        try:
                            # Intentamos obtener float, si no string
                            v = d.as_float()
                            vals.append(f"{d.channelName()}:{v:.4f}")
                        except:
                            vals.append(f"{d.channelName()}:raw")
                
                print(f"RX [{nid}] Ts:{ts} | {', '.join(vals)}")

            # Watchdog visual
            if packet_count == 0 and (time.time() - start_time > 5):
                print("... Esperando datos ...")
                start_time = time.time()

    except KeyboardInterrupt:
        logger.info("\nDetenido por usuario.")
    except Exception as e:
        logger.critical(f"Error general: {e}")
        traceback.print_exc()
    finally:
        # 7. CIERRE
        logger.info("Cerrando recursos...")
        if base_station:
            try:
                logger.info("Apagando Beacon...")
                base_station.disableBeacon()
            except:
                pass
        
        if connection:
            connection.disconnect()
            logger.info("Puerto cerrado.")
        
        input("Presiona ENTER para salir.")

if __name__ == "__main__":
    run_test()