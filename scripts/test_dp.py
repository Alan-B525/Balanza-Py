from modules.data_processor import DataProcessor
from config import NODOS_CONFIG

dp = DataProcessor(NODOS_CONFIG)
print('nodos_config keys:', list(dp.nodos_config.keys()))
print('single_node_mode:', getattr(dp, 'single_node_mode', False))
print('tares keys:', list(dp._tares.keys()))
print('initialized composites:', list(dp._last_stable_values.keys()))
