import json
from modules.data_processor import create_processor
p=json.load(open('settings.json','r',encoding='utf-8'))
proc=create_processor(p['nodes'])
print('Processor nodes:', len(proc.nodos_config))
print('node_to_name keys:', list(proc._node_to_name.keys()))
