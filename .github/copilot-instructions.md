# Instrucciones para agentes AI (Copilot)

Aplicación de pesaje industrial con UI (Tkinter + ttkbootstrap), driver MSCL y servidor Modbus opcional.

## Panorama y flujo de datos
- **Punto de entrada**: `main.py` orquesta hilos y colas (`data_queue`, `command_queue`) y crea componentes vía `modules.factory.criar_sistema_pesaje`.
- **Backend**: el `hilo_adquisicion` llama `sistema_pesaje.obtener_datos()` → `modules/data_processor.DataProcessor.procesar()` → envía mensajes a GUI por `data_queue`.
- **GUI**: `modules/gui.py` consume `data_queue` y emite comandos a `command_queue`.
- **Mensajes esperados GUI↔backend**: `DATA`, `STATUS`, `LOG`, `CONNECTION_PROGRESS`, `DISCOVERED_NODES`, `SENSOR_DISCONNECT`.

## Drivers y dependencias externas
- **Driver real**: `modules/sensor_driver.py` (MSCLDriver) usa MSCL local en `MSCL/x64/Release` y agrega esa ruta al `sys.path` en runtime.
- **Driver mock**: `modules/sensor_mock.py` para simular hardware (preferido en depuración sin equipo).
- **Modbus**: `modules/modbus_server.py` (pymodbus). Protocolo: coil 0=data_available, coil 1=ack; holding registers desde `holding_start`.
- **Transmisión Modbus (rápida)**: solo publicar el dato de **carga** de la celda 1 (`"<node_id>:ch1"`). **No** transmitir el ángulo (`"<node_id>:ch2"`). Priorizar la menor latencia posible desde que llega el dato hasta que se escribe en Modbus (evitar pasos extra y envío de datos innecesarios).

## Procesamiento y convenciones críticas
- `modules/data_processor.py` fuerza modo **single-node** (solo primer nodo del dict) por compatibilidad.
- Claves de sensores: `"<node_id>:ch1"` (carga) y `"<node_id>:ch2"` (ángulo). Cambiar nombres rompe tara/calibración.
- Comportamientos específicos: sample-&-hold cuando faltan lecturas; filtros por defecto apagados (`USE_FILTERS=False`).

## Comandos entre GUI y backend (payloads relevantes)
- `CONNECT`, `DISCONNECT`, `CANCEL_CONNECT`, `CONNECT_WITH_PROGRESS`
- `TARE`, `RESET_TARE`
- `DISCOVER_NODES` (usa `sistema_pesaje.descubrir_nodos()` si existe)
- `APPLY_CONFIG` con `serial_port` y `nodes` → actualiza `ACTIVE_COM`, `ACTIVE_NODOS` y reconfigura driver/procesador
- `MANUAL_RECONNECT`, `PAUSE_ACQUISITION`, `RESUME_ACQUISITION`, `EXIT`

## Flujos de trabajo
- Configuración: `config.py` (`MODO_EJECUCION = "REAL" | "MOCK"`) o `settings.json` con `"execution_mode": "MOCK"`.
- Ejecutar app: `python main.py`.
- Empaquetado: spec files (`BalanzaSystem.spec`, `Sistema de Pesagem ARBRA.spec`) y helper `scripts/build_exe.py`. Al empaquetar, incluir `MSCL/x64/Release` como binario.

## Logs y archivos clave
- Logs en `log.log` dentro de `DATA_DIR` (ver `modules/logger.py` y `config.get_writable_dir()`).
- Archivos clave: `main.py`, `modules/gui.py`, `modules/data_processor.py`, `modules/factory.py`, `modules/sensor_driver.py`, `modules/sensor_mock.py`, `modules/modbus_server.py`, `config.py`.

Si alguna sección quedó ambigua (p. ej., payload exacto de `DATA` o empaquetado MSCL), pedime detalles y preparo ejemplos/patches.
