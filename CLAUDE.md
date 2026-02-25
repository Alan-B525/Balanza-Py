# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the application
python main.py

# Build Windows executable (PyInstaller)
python scripts/build_exe.py

# Install dependencies
pip install -r requirements.txt
```

There are no automated tests in this project.

## Architecture

The application runs two threads that communicate via queues:

- **GUI thread** (`BalanzaGUI` in `modules/gui.py`): Tkinter/ttkbootstrap UI, polls `data_queue` every 50ms via `actualizar_gui()`, sends commands through `command_queue`.
- **Backend thread** (`hilo_adquisicion` in `main.py`): manages hardware I/O, reconnection logic, and data processing. Sends `DATA`, `STATUS`, `ERROR`, `LOG`, `CONNECTION_PROGRESS`, `SENSOR_DISCONNECT`, `SENSOR_RECONNECTED`, `RECONNECT_PROGRESS`, `RECONNECT_FAILED`, `DISCOVERED_NODES` message types to the GUI.

### Module roles

| Module | Role |
|---|---|
| `config.py` | Global constants, path resolution (dev vs PyInstaller EXE), MSCL path setup |
| `modules/gui.py` | Entire UI (~5000 lines). `BalanzaGUI(ttk.Window)`. Handles display, tare, calibration wizard, configuration dialog, connection dialogs |
| `modules/data_processor.py` | Business logic: moving averages, tare, weight calculation |
| `modules/sensor_driver.py` | MSCL-based hardware driver, node management, auto-reconnect |
| `modules/sensor_mock.py` | Simulated sensor for development without hardware |
| `modules/factory.py` | Creates the sensor system based on `execution_mode` setting |
| `modules/calibration.py` | Calibration data management (CSV storage in `calibrations/`) |
| `modules/interfaces.py` | Abstract interfaces for sensors |
| `modules/logger.py` | Lightweight logger with step/info/warning levels |

### Configuration

`config.py` defines hardware defaults (`MODO_EJECUCION`, `PUERTO_COM`, `NODOS_CONFIG`). These are overridden at runtime by `settings.json` (written by the in-app configuration dialog). `settings.json` lives in:
- Dev: project root
- EXE: `%LOCALAPPDATA%\SistemaDePesagem\`

### Target platform

The primary target is a **Windows tablet at 1280×800**. At that resolution, `BalanzaGUI` removes the OS title bar (`overrideredirect(True)`) and runs fullscreen. All sizes are scaled dynamically via `self.scale` / `self.scaled()` / `self.scaled_font()` relative to the `1280×800` base resolution.

### Configuration access (PIN)

The CONFIG button opens `show_configuration_dialog()`, which uses `_show_numeric_keypad()` in `pin_mode=True` to request a 4-digit PIN before showing the config UI. The PIN is hardcoded in `gui.py` near the `show_configuration_dialog` method.

### Numeric keypad

`_show_numeric_keypad(entry_widget, title, pin_mode, max_digits)` is a reusable `tk.Toplevel` numeric keypad. In `pin_mode=True` it masks input with `●`, removes `.`/`-` buttons, adds CANCELAR, hides the OS title bar, shows a custom title label, and returns the entered PIN (or `None` on cancel) via `wait_window`.

### EXE build

`scripts/build_exe.py` calls PyInstaller with `--onefile --windowed`. Bundled data includes `MSCL/`, `calibrations/`, `settings.json`, `config.py`, and `assets/`. Hidden imports: `ttkbootstrap`, `PIL`.
