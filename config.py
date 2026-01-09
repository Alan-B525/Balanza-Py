# -*- coding: utf-8 -*-
import sys
import os

MSCL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MSCL", "x64", "Release")
if os.path.exists(MSCL_PATH) and MSCL_PATH not in sys.path:
    sys.path.insert(0, MSCL_PATH)
    print(f"[CONFIG] MSCL path: {MSCL_PATH}")

MODO_EJECUCION = "REAL"
PUERTO_COM = "COM3"
BAUDRATE = 921600

NODOS_CONFIG = {
    "celda_1": {"id": 0, "ch": "ch1", "nombre": "Célula 1", "posicion": "1", "serial": ""},
    "celda_2": {"id": 0, "ch": "ch2", "nombre": "Célula 2", "posicion": "2", "serial": ""},
    "celda_3": {"id": 0, "ch": "ch1", "nombre": "Célula 3", "posicion": "3", "serial": ""},
    "celda_4": {"id": 0, "ch": "ch2", "nombre": "Célula 4", "posicion": "4", "serial": ""},
}

RECONNECT_ATTEMPTS = 3
NODE_TIMEOUT_SECONDS = 5.0
DATA_TIMEOUT_MS = 100

# === Especificações do Display ===
# Windows 10 IoT Enterprise / Android 4.4
# Resolução: 10.1" 1280x800
APP_TITLE = "Sistema de Pesagem Industrial"
APP_SIZE = "1280x800"
THEME_NAME = "litera"

# === Especificações do Sensor (Célula de Carga) ===
SENSOR_MV_PER_V = 1.2      # Sensibilidade: 1.2 mV/V
SENSOR_MAX_VOLTAGE = 2.5   # Tensão máxima de excitação: 2.5V
DISPLAY_DECIMALS = 0       # Mostrar valores inteiros (sem decimais)
