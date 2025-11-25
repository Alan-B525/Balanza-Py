import sys
import os
import time
import threading
import queue
import random
from config import MSCL_DIR, DEFAULT_PORTS, SIMULATION_MODE

# Setup MSCL path
if os.path.exists(MSCL_DIR):
    sys.path.append(MSCL_DIR)
else:
    print(f"Warning: MSCL directory not found at {MSCL_DIR}")

# --- Mock Definitions ---
class MockDataPoint:
    def __init__(self, name): self.name = name
    def channelName(self): return self.name
    def storedAs(self): return 1 # float
    def as_float(self): return random.uniform(10.0, 50.0)
    def as_double(self): return self.as_float()

class MockSweep:
    def nodeAddress(self): return random.choice([12345, 67890, 11111, 22222])
    def data(self): return [MockDataPoint("ch1")]
    def nodeRSSI(self): return random.randint(-90, -40)

class MockMscl:
    valueType_float = 1
    valueType_double = 2
    class Connection:
        @staticmethod
        def Serial(port): return "MockConnection"
    class BaseStation:
        def __init__(self, conn): pass
        def ping(self): return True
        def getData(self, timeout): 
            time.sleep(0.1)
            # Simulate data arrival rate
            if random.random() < 0.2:
                return [MockSweep()]
            return []

# --- Library Selection ---
mscl = None

if not SIMULATION_MODE:
    try:
        import mscl as real_mscl
        mscl = real_mscl
        print("Loaded Real MSCL Library")
    except ImportError as e:
        print(f"Error importing MSCL: {e}")
        print("Falling back to Mock MSCL")

if mscl is None:
    print("Using Simulated Sensors (Mock MSCL)")
    mscl = MockMscl()

class SensorManager:
    def __init__(self, logger):
        self.logger = logger
        self.data_queue = queue.Queue()
        self.running = False
        self.connection = None
        self.base_station = None
        self.thread = None

    def connect(self):
        """Auto-discovers and connects to the BaseStation."""
        try:
            self.logger.log("Searching for BaseStation...")
            found = False
            
            # In a real scenario with pyserial, we could list ports.
            # Here we iterate through a predefined list.
            for port in DEFAULT_PORTS:
                try:
                    self.logger.log(f"Testing {port}...")
                    self.connection = mscl.Connection.Serial(port)
                    self.base_station = mscl.BaseStation(self.connection)
                    
                    if self.base_station.ping():
                        self.logger.log(f"BaseStation found on {port}")
                        found = True
                        break
                    else:
                        self.connection.disconnect()
                except Exception:
                    pass
            
            if not found:
                raise Exception("BaseStation not found on common ports.")
            
            self.logger.log("BaseStation connected. Listening for Wireless Nodes...")
            self.running = True
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
            return True
            
        except Exception as e:
            self.logger.log(f"Connection Error: {str(e)}")
            return False

    def disconnect(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        
        if self.connection:
            try:
                self.connection.disconnect()
            except:
                pass
            self.logger.log("Disconnected.")
            self.connection = None
            self.base_station = None

    def _read_loop(self):
        self.logger.log("Starting data acquisition...")
        while self.running:
            try:
                # Get sweeps with 500ms timeout
                sweeps = self.base_station.getData(500)
                
                for sweep in sweeps:
                    node_id = sweep.nodeAddress()
                    
                    # Try to get RSSI if available (WirelessSweep)
                    rssi = -999
                    try:
                        rssi = sweep.nodeRSSI()
                    except:
                        pass

                    data = {}
                    
                    for data_point in sweep.data():
                        channel_name = data_point.channelName()
                        
                        if data_point.storedAs() == mscl.valueType_float:
                            data[channel_name] = data_point.as_float()
                        elif data_point.storedAs() == mscl.valueType_double:
                            data[channel_name] = data_point.as_double()
                    
                    if data:
                        self.data_queue.put((node_id, data, rssi))
                        
            except Exception as e:
                # Avoid spamming logs on continuous errors
                time.sleep(1)

    def get_data(self):
        """Retrieves all available data from the queue."""
        items = []
        while not self.data_queue.empty():
            items.append(self.data_queue.get_nowait())
        return items
