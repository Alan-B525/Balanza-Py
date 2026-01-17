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

print("Iniciando PyInstaller...")
PyInstaller.__main__.run(args)
print("Compilación finalizada. Revisa la carpeta 'dist/'.")