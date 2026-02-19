import PyInstaller.__main__
import os
import shutil

# Nombre del script a compilar
script_name = os.path.join("scripts", "test_mscl_performance.py")

# Carpetas y archivos a incluir
add_data = [
    ('MSCL', 'MSCL'),
    ('config.py', '.'),
    ('settings.json', '.'),
]

add_data_args = []
for src, dest in add_data:
    add_data_args.append(f'--add-data={src};{dest}')

# Argumentos para PyInstaller
args = [
    script_name,
    '--name=MSCL_Performance_Test',
    '--onefile',
    '--console',        # Mostrar consola para el test
    '--clean',
    '--noconfirm',
] + add_data_args

# Imports ocultos que PyInstaller podría omitir
hidden_imports = [
    'platform',
    'json',
    'argparse',
    'traceback',
    'ctypes',
]

for imp in hidden_imports:
    args.append(f'--hidden-import={imp}')

# Directorio de salida
dist_out = os.path.join('dist_test')
args.append(f'--distpath={dist_out}')

print("Iniciando compilación del TEST con los siguientes argumentos:")
print(args)

PyInstaller.__main__.run(args)

print("\nCompilación del TEST finalizada.")
print(f"El ejecutable se encuentra en: {os.path.abspath(dist_out)}")

# Copiar settings.json al directorio de salida para pruebas manuales
try:
    shutil.copy('settings.json', os.path.join(dist_out, 'settings.json'))
    print(f"[*] 'settings.json' copiado a {dist_out}")
except Exception as e:
    print(f"[!] No se pudo copiar settings.json: {e}")
