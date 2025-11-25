import os
import sys

# Application Constants
APP_TITLE = "Sistema de Pesagem - MSCL"
APP_SIZE = "1280x800"
THEME_NAME = "litera"

# MSCL Configuration
if getattr(sys, 'frozen', False):
    # If running as a PyInstaller bundle
    CURRENT_DIR = sys._MEIPASS
else:
    # If running as a script
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

MSCL_DIR = os.path.join(CURRENT_DIR, "MSCL", "x64", "Release")

# Connection Settings
DEFAULT_PORTS = ["COM3", "COM4", "COM5", "COM6", "COM7", "COM8"]
BAUD_RATE = 921600 # Default for MSCL BaseStation usually
SIMULATION_MODE = True # Set to True to force simulated sensors without hardware

# Data Settings
MAX_SENSORS = 4
