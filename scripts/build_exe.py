import PyInstaller.__main__
import os
import shutil

# Nombre del script principal
script_name = "main.py"

# Carpetas a incluir
# Formato: (origen, destino)
# Nota: En Windows el separador para add-data en línea de comandos es ';', 
# pero aquí pasamos argumentos como lista.

# Carpetas y archivos a incluir como datos precargados
add_data = [
    ('MSCL', 'MSCL'), # Incluir toda la carpeta MSCL
    ('settings.json', 'settings.json'),
    ('requirements.txt', 'requirements.txt'),
    ('config.py', 'config.py'),
    ('assets', 'assets'),
]

# Construir el argumento --add-data
add_data_args = []
for src, dest in add_data:
    # En Windows usamos ; como separador
    add_data_args.append(f'--add-data={src};{dest}')

# Argumentos para PyInstaller
args = [
    script_name,
    '--name=Controle de Carga',
    '--onefile',        # Crear un solo archivo ejecutable
    '--windowed',       # No mostrar consola (GUI app)
    '--clean',          # Limpiar caché antes de construir
    '--noconfirm',      # No preguntar para sobrescribir
    '--icon=assets/icon.ico', # Icono del ejecutable
] + add_data_args

# Directorio de salida deseado
dist_out = os.path.join('dist/Controle_de_Carga')
args.append(f'--distpath={dist_out}')

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
print(f"El ejecutable se encuentra en: {os.path.abspath(dist_out)}")

# Asegurarse de que settings.json esté copiado en dist_out para Inno Setup
try:
    shutil.copy('settings.json', os.path.join(dist_out, 'settings.json'))
    print(f"[*] settings.json copiado a {dist_out}")
except Exception as e:
    print(f"[!] No se pudo copiar settings.json: {e}")

# Compilar instalador Inno Setup si ISCC.exe está disponible
iscc_candidates = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    shutil.which("iscc"),
    shutil.which("ISCC.exe")
]
iscc_path = next((p for p in iscc_candidates if p and os.path.exists(p)), None)

iss_file = os.path.abspath(os.path.join(dist_out, "setup.iss"))
if iscc_path and os.path.exists(iss_file):
    print(f"\n[*] Compilador Inno Setup encontrado en: {iscc_path}")
    print(f"[*] Compilando instalador: {iss_file}...")
    import subprocess
    ret = subprocess.run([iscc_path, iss_file], cwd=dist_out)
    if ret.returncode == 0:
        print("[OK] Instalador compilado exitosamente en dist/Controle_de_Carga/Output/!")
    else:
        print(f"[!] Error compilando el instalador con Inno Setup (código {ret.returncode}).")
else:
    print("\n[*] Inno Setup no encontrado o no se encontró setup.iss. Se puede compilar manualmente.")
