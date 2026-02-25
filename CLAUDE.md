# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Industrial weighing system (Balanza-Py) that monitors wireless load cells via MicroStrain MSCL hardware, with a touchscreen-optimized GUI, real-time Modbus RTU server, and a mock simulation mode for development without hardware.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application (mock mode by default if settings.json specifies MOCK)
python main.py

# Build standalone executable
python scripts/build_exe.py

# Run unit tests
python scripts/test_dp.py
python scripts/test_mscl_performance.py
```

To run in simulation mode without hardware, ensure `settings.json` contains `"execution_mode": "MOCK"` or set `MODO_EJECUCION = "MOCK"` in `config.py`.

## Architecture

The application uses a **multi-threaded, queue-based** design:

```
main.py (main thread)
├── Backend thread: hilo_adquisicion()
│   ├── SistemaPesaje (via factory.py)
│   │   ├── MSCLDriver  – real hardware (modules/sensor_driver.py)
│   │   └── MockDriver  – simulation  (modules/sensor_mock.py)
│   ├── DataProcessor   – normalizes raw frames (modules/data_processor.py)
│   └── ModbusDataServer – RTU server  (modules/modbus_server.py)
└── GUI thread: BalanzaGUI (modules/gui.py, Tkinter + ttkbootstrap)
```

**Inter-thread communication uses two queues:**
- `data_queue`: Backend → GUI. Message types: `DATA`, `STATUS`, `LOG`, `CONNECTION_PROGRESS`, `DISCOVERED_NODES`, `SENSOR_DISCONNECT`.
- `command_queue`: GUI → Backend. Commands: `CONNECT`, `DISCONNECT`, `CANCEL_CONNECT`, `CONNECT_WITH_PROGRESS`, `TARE`, `RESET_TARE`, `DISCOVER_NODES`, `APPLY_CONFIG`, `MANUAL_RECONNECT`, `PAUSE_ACQUISITION`, `RESUME_ACQUISITION`, `EXIT`.

## Key Conventions

- **Sensor key format**: `"<node_id>:ch1"` (load/carga) and `"<node_id>:ch2"` (angle/ángulo). These strings are used as dictionary keys throughout; changing them breaks tare and calibration.
- **Single-node enforcement**: `DataProcessor` always uses only the first entry in the nodes config dict. Multi-node support is a future consideration.
- **Modbus transmission**: Only publish `ch1` (load) data. Never transmit the angle channel. Minimize latency from data arrival to register write.
- **Filters off by default**: `USE_FILTERS = False` in `data_processor.py`; sample-and-hold is applied when readings are missing.

## Configuration Hierarchy

1. `config.py` – compile-time defaults (`MODO_EJECUCION`, `PUERTO_COM`, `NODOS_CONFIG`, `GATEWAY`, `TRANSMISSAO`)
2. `settings.json` – runtime overrides (loaded by `config.load_settings()`)
3. GUI settings panel – writes back to `settings.json`

`config.get_writable_dir()` resolves the data directory: next to the `.exe` when packaged, or the project root otherwise. All persistent files (`log.log`, `calibrations/curvas_celdas.csv`) are written there.

## MSCL Driver

The MSCL library is a native Windows DLL bundle located in `MSCL/x64/Release/`. `sensor_driver.py` appends this path to `sys.path` at runtime. When building with PyInstaller, this directory must be included as a binary bundle (already configured in the `.spec` files). There is no pip-installable MSCL package; it only works on Windows x64.

## Modbus Server

- Implemented with `pymodbus >= 3.0, < 4` over serial RS-485.
- **Coil 0**: `data_available` flag; **Coil 1**: client ACK.
- **Holding registers**: start index defined by `holding_start`; INT32 weight × 1000 scale factor split into two 16-bit registers (high word, low word).
- Auto-retries every 2 seconds if the serial port is unavailable.
- Full protocol documentation in `docs/MODBUS_SERVER.md`.

## Build / Packaging

Multiple `.spec` files exist for different customer variants (`BalanzaSystem.spec`, `Sistema de Pesagem ARBRA.spec`, etc.). All use `main.py` as entry point, bundle `MSCL/x64/Release`, `assets/`, and calibration data. The helper script `scripts/build_exe.py` wraps PyInstaller invocation. Output goes to `dist/Controle_de_Carga/`.
