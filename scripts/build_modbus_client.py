"""
build_modbus_client.py – Compila modbus_client.py como ejecutable .exe standalone.

Uso:
    python scripts/build_modbus_client.py

El .exe queda en dist/modbus_client/modbus_client.exe
"""
import os
import subprocess
import sys

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
SOURCE      = os.path.join(SCRIPT_DIR, "modbus_client.py")
DIST_DIR    = os.path.join(PROJECT_DIR, "dist")
BUILD_DIR   = os.path.join(PROJECT_DIR, "build_modbus")

def main():
    print("=" * 60)
    print("  Build: modbus_client.exe")
    print("=" * 60)

    # Verificar que pyinstaller esté disponible
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                       check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[ERROR] PyInstaller no encontrado. Instale con:")
        print("        pip install pyinstaller")
        sys.exit(1)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                          # Un solo .exe
        "--windowed",                         # Sin consola (ventana GUI)
        f"--name=modbus_client",
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        f"--specpath={BUILD_DIR}",
        # Asegurar que tkinter y pymodbus estén incluidos
        "--hidden-import=tkinter",
        "--hidden-import=tkinter.ttk",
        "--hidden-import=pymodbus",
        "--hidden-import=pymodbus.client",
        "--hidden-import=serial",
        "--hidden-import=serial.tools",
        "--hidden-import=serial.tools.list_ports",
        "--hidden-import=matplotlib",
        "--hidden-import=matplotlib.pyplot",
        "--hidden-import=matplotlib.backends.backend_tkagg",
        SOURCE,
    ]

    print(f"\n  Fuente:  {SOURCE}")
    print(f"  Destino: {DIST_DIR}\\modbus_client.exe\n")

    ret = subprocess.run(cmd, cwd=PROJECT_DIR)

    if ret.returncode == 0:
        exe_path = os.path.join(DIST_DIR, "modbus_client.exe")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n  ✓ Build exitoso: {exe_path} ({size_mb:.1f} MB)")
        else:
            print(f"\n  ✓ Build completado (ver en {DIST_DIR})")
    else:
        print(f"\n  ✗ Build fallido (código {ret.returncode})")
        sys.exit(ret.returncode)


if __name__ == "__main__":
    main()
