import PyInstaller.__main__
import os
import shutil

# Nombre del script principal
script_name = "main.py"

# Carpetas a incluir
# Formato: (origen, destino)
# Nota: En Windows el separador para add-data en línea de comandos es ';', 
# pero aquí pasamos argumentos como lista.
add_data = [
    ('MSCL', 'MSCL'), # Incluir toda la carpeta MSCL
]

# Construir el argumento --add-data
add_data_args = []
for src, dest in add_data:
    # En Windows usamos ; como separador
    add_data_args.append(f'--add-data={src};{dest}')

# Argumentos para PyInstaller
args = [
    script_name,
    '--name=BalanzaSystem',
    '--onefile',        # Crear un solo archivo ejecutable
    '--windowed',       # No mostrar consola (GUI app)
    '--clean',          # Limpiar caché antes de construir
    '--noconfirm',      # No preguntar para sobrescribir
    # '--icon=logo.ico', # Si tuvieras un icono
] + add_data_args

# Imports ocultos que a veces PyInstaller no detecta
hidden_imports = [
    'ttkbootstrap',
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
]

for imp in hidden_imports:
    args.append(f'--hidden-import={imp}')

print("Iniciando compilación con los siguientes argumentos:")
print(args)

# Ejecutar PyInstaller
PyInstaller.__main__.run(args)

print("\nCompilación finalizada.")
print("El ejecutable se encuentra en la carpeta 'dist'.")
