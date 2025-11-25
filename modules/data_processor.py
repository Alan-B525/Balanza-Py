import time
from config import MAX_SENSORS

class DataProcessor:
    def __init__(self, logger):
        self.logger = logger
        # Stores the latest raw value for each sensor: {(node_id, channel_name): value}
        self.raw_data = {}
        
        # Stores metadata for each node: {node_id: {'rssi': val, 'last_seen': timestamp}}
        self.node_stats = {}
        
        # Maps display slots (0 to 3) to sensor keys (node_id, channel_name)
        self.display_slots = [None] * MAX_SENSORS
        
        # Stores the tare value for each slot
        self.tare_values = [0.0] * MAX_SENSORS
        
        # Calibration factors (Slope) for each slot. Default 1.0
        self.calibration_factors = [1.0] * MAX_SENSORS

    def process_incoming_data(self, node_id, data_dict, rssi):
        """
        Updates raw data and assigns new sensors to empty slots.
        Returns a list of updates for the UI if needed.
        """
        # Update Node Stats
        self.node_stats[node_id] = {
            'rssi': rssi,
            'last_seen': time.time()
        }

        updated_keys = []
        for ch_name, value in data_dict.items():
            key = (node_id, ch_name)
            self.raw_data[key] = value
            updated_keys.append(key)
            
            # Auto-assign to slot if new
            if key not in self.display_slots:
                if None in self.display_slots:
                    idx = self.display_slots.index(None)
                    self.display_slots[idx] = key
                    self.logger.log(f"Assigned Node {node_id}:{ch_name} to Slot {idx+1}")
        
        return updated_keys

    def get_display_values(self):
        """
        Calculates net values (Raw - Tare) for all slots.
        Returns:
            net_values: List of floats [val1, val2, val3, val4]
            total_net: Float (sum of net_values)
            total_tare: Float (sum of current tares)
            slot_info: List of strings ["Node X - chY", ...]
            slot_status: List of dicts [{'rssi': val, 'stale': bool}, ...]
        """
        net_values = []
        slot_info = []
        slot_status = []
        total_net = 0.0
        total_tare = 0.0
        
        now = time.time()

        for i in range(MAX_SENSORS):
            key = self.display_slots[i]
            raw = 0.0
            info = "Aguardando..."
            status = {'rssi': -999, 'stale': True}
            
            if key and key in self.raw_data:
                raw = self.raw_data[key]
                info = f"Nó {key[0]} - {key[1]}"
                
                # Check stats
                if key[0] in self.node_stats:
                    stats = self.node_stats[key[0]]
                    status['rssi'] = stats['rssi']
                    # Consider stale if no data for > 3 seconds
                    if now - stats['last_seen'] < 3.0:
                        status['stale'] = False
            
            # CRITICAL: Tare is always calculated from raw data
            # Formula: Net = (Raw * Slope) - Tare
            # Note: Usually Tare is applied after Slope, or Raw is Tared then Sloped.
            # Standard: Net = (Raw - Tare_Raw) * Slope
            # But here we stored Tare as the value at that moment.
            # Let's assume Tare is in the same units as Raw (unscaled).
            
            tare = self.tare_values[i]
            slope = self.calibration_factors[i]
            
            # We will apply slope to the difference
            net = (raw - tare) * slope
            
            net_values.append(net)
            slot_info.append(info)
            slot_status.append(status)
            
            total_net += net
            # For total tare display, we might want to show it scaled too?
            # Or just show the raw tare sum? Let's show scaled tare contribution.
            # Tare contribution = Tare * Slope
            total_tare += (tare * slope)

        return net_values, total_net, total_tare, slot_info, slot_status

    def set_tare(self):
        """
        Sets the current raw values as the new tare values.
        """
        for i in range(MAX_SENSORS):
            key = self.display_slots[i]
            if key and key in self.raw_data:
                self.tare_values[i] = self.raw_data[key]
            else:
                self.tare_values[i] = 0.0
        self.logger.log("Tare set. Values zeroed.")

    def reset_tare(self):
        """
        Resets all tare values to 0.0.
        """
        self.tare_values = [0.0] * MAX_SENSORS
        self.logger.log("Tare reset.")
