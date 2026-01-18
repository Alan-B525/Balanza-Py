import PyInstaller.__main__
import os
import shutil

# Ruta al script unificado (asumiendo que ejecutas este build desde la raiz del proyecto)
# Si ejecutas "python scripts/build_test_tool.py", el script name es:
script_name = os.path.join("scripts", "test_driver.py")

# Verificar que exista
if not os.path.exists(script_name):
    # Intentar ver si estamos en la carpeta scripts
    if os.path.exists("test_driver.py"):
        script_name = "test_driver.py"
    else:
        print(f"Error: No encuentro {script_name}. Ejecuta desde la raíz del proyecto.")
        exit(1)

print(f"Compilando: {script_name}")

# Datos a incluir (Solo necesitamos MSCL para el driver de prueba)
# Formato: (origen, destino)
add_data = [
    ('MSCL', 'MSCL'), 
]

# Construir argumentos de datos para PyInstaller
# En Windows el separador es ';'
sep = ';' if os.name == 'nt' else ':'
add_data_args = []
for src, dest in add_data:
    if os.path.exists(src):
        add_data_args.append(f'--add-data={src}{sep}{dest}')
    else:
        print(f"ADVERTENCIA: Carpeta '{src}' no encontrada. El EXE podría fallar.")

# Argumentos para PyInstaller
args = [
    script_name,
    '--name=TestDriver_Console', # Nombre del EXE resultante
    '--onefile',                 # Un solo archivo .exe
    '--console',                 # <--- IMPORTANTE: Mostrar consola negra para ver logs
    '--clean',                   # Limpiar caché
    '--noconfirm',               # Sobrescribir sin preguntar
    # '--debug=all',             # Descomentar si falla al arrancar para ver trazas internas
] + add_data_args

# Opcional: compilar en un subdirectorio dentro de dist
# Define el nombre del subdirectorio aquí o a través de la variable de entorno DIST_SUBDIR
DIST_SUBDIR = os.environ.get('DIST_SUBDIR', 'alternative')
dist_target = os.path.join('dist', DIST_SUBDIR)
# Asegurar que exista la carpeta destino
os.makedirs(dist_target, exist_ok=True)

# Añadir argumento de PyInstaller para la ruta de salida
args.append(f'--distpath={dist_target}')

print("Iniciando PyInstaller...")
PyInstaller.__main__.run(args)
print(f"Compilación finalizada. Revisa la carpeta '{dist_target}'.")