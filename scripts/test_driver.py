"""
test_driver_v8.py
-----------------
DRIVER FINAL DE RECUPERACIÓN Y PRODUCCIÓN
- Estrategia: "Silencio largo" + "Stop Ciego" + "Ping".
- Solución al crash de lectura (as_string).
- Solución al error de configuración (bypass).
"""

import sys
import os
import time
import logging
import traceback

# --- CONFIGURACIÓN ---
COM_PORT = "COM3"
BAUD_RATE = 3000000
NODE_IDS = [4248, 4249]
TIMEOUT_RECUPERACION_SEG = 60  # Espera larga para nodos dormidos

# --- LOGGING ---
logger = logging.getLogger("DriverV8")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)
logger.addHandler(ch)
fh = logging.FileHandler("test_driver.log", mode='w', encoding='utf-8')
fh.setFormatter(formatter)
logger.addHandler(fh)

# --- CARGA MSCL ---
def load_mscl():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths = ["MSCL/x64/Release", "../MSCL/x64/Release", "../../MSCL/x64/Release"]
    mscl_path = None
    for p in paths:
        full = os.path.abspath(os.path.join(script_dir, p))
        if os.path.exists(os.path.join(full, "mscl.py")):
            mscl_path = full
            break
    if not mscl_path: return False
    if mscl_path not in sys.path: sys.path.insert(0, mscl_path)
    if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
        try: os.add_dll_directory(mscl_path)
        except: pass
    return True

if not load_mscl():
    print("FATAL: No se encontro MSCL.")
    sys.exit(1)

import mscl

def esperar_y_detener_nodo(base_station, node_id):
    logger.info(f"[{node_id}] Intentando recuperar control... (Max {TIMEOUT_RECUPERACION_SEG}s)")
    node = mscl.WirelessNode(node_id, base_station)
    start_time = time.time()
    attempts = 0
    
    while (time.time() - start_time) < TIMEOUT_RECUPERACION_SEG:
        attempts += 1
        
        # ESTRATEGIA: "Stop Ciego". 
        # Intentamos parar el nodo aunque no sepamos si está ahí.
        try:
            node.setToIdle()
        except: 
            pass 

        # Ahora probamos si responde
        try:
            res = node.ping()
            if res.success():
                logger.info(f"[{node_id}] >>> CONTACTO EXITOSO <<<")
                # Asegurar una vez más
                node.setToIdle()
                return node
        except:
            pass
        
        # Feedback visual cada 5 intentos
        if attempts % 5 == 0:
            print(f"   ... buscando [{node_id}] ...")
            
        time.sleep(0.5)

    logger.error(f"[{node_id}] FALLO: No se pudo contactar.")
    return None

def run_system():
    logger.info(f"=== INICIANDO DRIVER V8 (RECUPERACION) ===")
    connection = None
    base_station = None
    
    try:
        # 1. CONEXIÓN
        logger.info(f"Abriendo {COM_PORT} @ {BAUD_RATE}...")
        connection = mscl.Connection.Serial(COM_PORT, BAUD_RATE)
        base_station = mscl.BaseStation(connection)
        
        # 2. SILENCIO RADIAL (CRÍTICO)
        logger.info("Apagando Beacon...")
        try:
            base_station.disableBeacon()
        except: pass
        
        # Esperamos 6 segundos para garantizar que los nodos detecten la pérdida del beacon
        # y salgan del modo de muestreo sincronizado.
        logger.info("Esperando 6 segundos para limpiar la red...")
        time.sleep(6)

        # 3. GESTIÓN DE NODOS
        network = mscl.SyncSamplingNetwork(base_station)
        nodos_ok = 0

        for nid in NODE_IDS:
            node_obj = esperar_y_detener_nodo(base_station, nid)
            
            if node_obj:
                # CONFIGURACIÓN (Bypass si falla librería)
                try:
                    logger.info(f"[{nid}] Validando config...")
                    config = mscl.WirelessNodeConfig(node_obj)
                    target = mscl.SampleRate.Seconds(2) # 0.5 Hz
                    
                    if config.sampleRate().prettyStr() != target.prettyStr():
                        logger.info(f"[{nid}] Ajustando a 0.5Hz...")
                        config.sampleRate(target)
                        config.apply()
                except TypeError:
                    logger.warning(f"[{nid}] Libreria MSCL bug config. Saltando.")
                except Exception as e:
                    logger.error(f"[{nid}] Error menor config: {e}")
                
                # AÑADIR A RED
                network.addNode(node_obj)
                nodos_ok += 1

        if nodos_ok == 0:
            logger.error("SIN NODOS. Intente desconectar/conectar el Gateway USB.")
            return

        # 4. APLICAR Y ARRANCAR
        logger.info("Aplicando config de red al Gateway...")
        try:
            network.applyConfiguration()
            logger.info("Iniciando Muestreo...")
            network.startSampling()
            logger.info(">>> RED OPERATIVA (Beacon ON) <<<")
        except Exception as e:
            logger.critical(f"Fallo al iniciar red: {e}")
            return

        # 5. BUCLE DE DATOS SEGURO
        logger.info("Esperando datos (0.5 Hz)... CTRL+C para salir.")
        last_t = time.time()
        
        while True:
            sweeps = base_station.getData(500)
            
            for sweep in sweeps:
                last_t = time.time()
                nid = sweep.nodeAddress()
                
                data_str = ""
                # Iteramos sobre los puntos
                for d in sweep.data():
                    # Usamos .as_string() para MAXIMA seguridad contra crashes
                    try:
                        channel = d.channelName()
                        # Solo mostrar canales útiles (evitar mostrar timestamps internos si molestan)
                        if "ch" in channel.lower() or "val" in channel.lower():
                            val = d.as_string() 
                            data_str += f"[{channel}: {val}] "
                    except:
                        pass
                
                if data_str:
                    print(f"RX [{nid}] | {data_str}")

            if time.time() - last_t > 10:
                print("... Esperando datos ...")
                last_t = time.time()

    except KeyboardInterrupt:
        print("\nDetenido.")
    except Exception as e:
        logger.critical(f"Error General: {e}")
        traceback.print_exc()
    finally:
        logger.info("Cerrando...")
        if base_station:
            try: base_station.disableBeacon()
            except: pass
        if connection:
            try: connection.disconnect()
            except: pass
        input("Presiona ENTER para salir.")

if __name__ == "__main__":
    run_system()