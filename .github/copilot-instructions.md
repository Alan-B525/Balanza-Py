# Instrucciones para agentes AI (Copilot)

Breve: Aplicación de pesaje industrial con UI (Tkinter + ttkbootstrap), driver MSCL y servidor Modbus opcional.

- **Punto de entrada**: `main.py` — orquesta hilos, colas (`data_queue`, `command_queue`) y crea los componentes mediante `modules.factory.criar_sistema_pesaje`.
- **Arquitectura**: backend `hilo_adquisicion` (en `main.py`) llama a `sistema_pesaje.obtener_datos()` → `modules/data_processor.DataProcessor.procesar()` → envía mensajes a GUI vía `data_queue`.
- **GUI**: `modules/gui.py` consume `data_queue` y envía comandos a `command_queue`. Mensajes importantes: `DATA`, `STATUS`, `LOG`, `CONNECTION_PROGRESS`, `DISCOVERED_NODES`, `SENSOR_DISCONNECT`.
- **Drivers**: creado por `modules/factory.py`; implementaciones principales:
  - `modules/sensor_driver.py` (MSCLDriver) — usa MSCL en `MSCL/x64/Release`; agrega la carpeta al `sys.path` en tiempo de ejecución.
  - `modules/sensor_mock.py` — usar en modo de simulación.
- **Procesamiento**: `modules/data_processor.py`:
  - Forza modo "single-node" por compatibilidad (usa sólo la primera entrada del dict de nodos).
  - Llaves de sensor: formato `"<node_id>:ch1"` (carga) y `"<node_id>:ch2"` (ángulo).
  - Comportamientos específicos: sample-&-hold cuando faltan lecturas, filtros por defecto desactivados (`USE_FILTERS=False`), y tara por clave composite.

- **Protocolos / comandos entre GUI y backend** (ejemplos que el agente debe conocer):
  - `CONNECT`, `DISCONNECT`, `CANCEL_CONNECT`, `CONNECT_WITH_PROGRESS`
  - `TARE`, `RESET_TARE`
  - `DISCOVER_NODES` (usa `sistema_pesaje.descubrir_nodos()` si está disponible)
  - `APPLY_CONFIG` (payload: `serial_port`, `nodes`) — actualiza `ACTIVE_COM`, `ACTIVE_NODOS` y reconfigura procesador/driver
  - `MANUAL_RECONNECT`, `PAUSE_ACQUISITION`, `RESUME_ACQUISITION`, `EXIT`

- **Integraciones y dependencias**:
  - Dependencias Python en `requirements.txt` (p. ej. `ttkbootstrap`, `pymodbus`, `Pillow`, `numpy`, `matplotlib`).
  - MSCL se incluye localmente en `MSCL/` y es referenciado desde `modules/sensor_driver.py` — al empacar con PyInstaller mantener la ruta y añadir `MSCL/x64/Release` a los binarios.
  - Modbus: `modules/modbus_server.py` — requiere `pymodbus`. Protocolo: coil 0=data_available, coil 1=ack; holding registers desde `holding_start`.

- **Flujos de desarrollo y comandos útiles**:
  - Entorno virtual e instalación:
    ```bash
    python -m venv venv
    venv\Scripts\Activate.ps1   # Windows PowerShell
    pip install -r requirements.txt
    ```
  - Ejecutar en modo real/simulación: editar `config.py` (`MODO_EJECUCION = "REAL" | "MOCK"`) o crear `settings.json` con `"execution_mode": "MOCK"`.
  - Ejecutar la app: `python main.py`.
  - Empaquetado: la repo incluye spec files (`BalanzaSystem.spec`, `Sistema de Pesagem ARBRA.spec`). También existe `scripts/build_exe.py` como helper.

- **Patrones y cautelas específicas** (no genéricas):
  - No cambiar a multi-node sin revisar `DataProcessor` — el código actualmente fuerza single-node y varios lugares asumen 1 nodo.
  - `DataProcessor` usa mapas por `composite key` (ej. `"12:ch1"`); modificar nombres de key rompe la mapeo de taras/calibración.
  - `sensor_driver.MSCLDriver` realiza manipulación agresiva de Beacon y timeouts largos de recuperación; cambiar parámetros sin pruebas físicas puede dejar la red inestable.
  - Para depuración sin hardware, preferir `sensor_mock` y `MODO_EJECUCION=MOCK`.
  - Logs: `modules/logger.py` y archivo `log.log` en el `DATA_DIR` obtenido desde `config.get_writable_dir()`.

- **Archivos clave para leer/modificar**:
  - `main.py` — orquestación, loop de adquisición `hilo_adquisicion` y protocolo de mensajes.
  - `modules/data_processor.py` — reglas de procesado, tara y calibración por sensor.
  - `modules/sensor_driver.py` — driver MSCL (producción).
  - `modules/sensor_mock.py` — driver de simulación.
  - `modules/gui.py` — lógica y contratos UI (mensajes esperados y manejo de colas).
  - `modules/modbus_server.py` — integración Modbus con PLC.
  - `config.py`, `settings.json`, `requirements.txt`, `scripts/build_exe.py`, `MSCL/x64/Release`.

Si alguna sección es ambigua o necesitás ejemplos concretos (p. ej. payload esperado en `DATA` o cómo empacar MSCL en PyInstaller), indícame cuál y genero ejemplos/patches concretos.
