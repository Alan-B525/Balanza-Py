import sys
import os

# Ensure modules can be imported
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from modules.utils import Logger
from modules.sensor_manager import SensorManager
from modules.data_processor import DataProcessor
from modules.gui import BalanzaGUI

def main():
    # 1. Initialize Logger
    logger = Logger()
    logger.log("Initializing Application...")

    # 2. Initialize Modules
    sensor_manager = SensorManager(logger)
    data_processor = DataProcessor(logger)

    # 3. Initialize GUI
    # We pass the manager and processor to the GUI so it can interact with them
    app = BalanzaGUI(sensor_manager, data_processor, logger)
    
    # 4. Run Application
    try:
        app.mainloop()
    except Exception as e:
        logger.log(f"Critical Error: {e}")
    finally:
        # Ensure clean shutdown
        sensor_manager.disconnect()

if __name__ == "__main__":
    main()
