import sys
import os
import time
import threading
import queue
import logging
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, BOTH, YES, NO, X, Y, LEFT, RIGHT, END, HORIZONTAL, BOTTOM
from PIL import Image, ImageTk

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
# Intentar importar desde la nueva ubicación si existe, para evitar warnings
try:
    from ttkbootstrap.widgets import ScrolledText
except ImportError:
    from ttkbootstrap.scrolled import ScrolledText

from ttkbootstrap.dialogs import Messagebox

# Configuración de ruta para MSCL
if getattr(sys, 'frozen', False):
    # Si estamos en un ejecutable (PyInstaller)
    current_dir = sys._MEIPASS
else:
    # Si estamos corriendo el script normal
    current_dir = os.path.dirname(os.path.abspath(__file__))

mscl_dir = os.path.join(current_dir, "MSCL", "x64", "Release")

if os.path.exists(mscl_dir):
    sys.path.append(mscl_dir)
else:
    # Fallback por si la estructura es diferente o estamos en desarrollo
    print(f"Advertencia: No se encontró el directorio MSCL en {mscl_dir}")

try:
    import mscl
except ImportError as e:
    print(f"Error crítico: No se pudo importar el módulo 'mscl'. Asegúrate de que las librerías estén en {mscl_dir}")
    print(e)
    # Creamos un mock para que la interfaz gráfica funcione sin la librería real (para pruebas)
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
                # Simular datos aleatorios para pruebas si no hay librería real
                import random
                time.sleep(0.1)
                if random.random() < 0.1:
                    return [MockSweep()]
                return []
    
    class MockSweep:
        def nodeAddress(self): return 12345
        def data(self): return [MockDataPoint("ch1"), MockDataPoint("ch2"), MockDataPoint("ch3"), MockDataPoint("ch4")]
        
    class MockDataPoint:
        def __init__(self, name): self.name = name
        def channelName(self): return self.name
        def storedAs(self): return 1 # float
        def as_float(self): 
            import random
            return random.uniform(10.0, 50.0)
        def as_double(self): return self.as_float()

    mscl = MockMscl()

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MSCLWorker:
    def __init__(self, data_queue, log_queue):
        self.data_queue = data_queue
        self.log_queue = log_queue
        self.running = False
        self.connection = None
        self.base_station = None
        self.node = None
        self.thread = None

    def log(self, message):
        self.log_queue.put(f"{datetime.now().strftime('%H:%M:%S')} - {message}")

    def connect(self, com_port=None):
        try:
            if com_port is None:
                # Auto-discovery logic
                # En un entorno real, iteraríamos sobre puertos disponibles
                # Por ahora, intentamos detectar puertos comunes o usamos un valor por defecto
                ports_to_try = ["COM3", "COM4", "COM5", "COM6", "COM7", "COM8"]
                # Si tuvieramos pyserial: import serial.tools.list_ports
                
                self.log("Buscando BaseStation...")
                found = False
                for port in ports_to_try:
                    try:
                        self.log(f"Probando {port}...")
                        self.connection = mscl.Connection.Serial(port)
                        self.base_station = mscl.BaseStation(self.connection)
                        if self.base_station.ping():
                            self.log(f"BaseStation encontrada en {port}")
                            found = True
                            break
                        else:
                            self.connection.disconnect()
                    except:
                        pass
                
                if not found:
                    raise Exception("No se encontró BaseStation en puertos comunes.")
            else:
                self.log(f"Intentando conectar a {com_port}...")
                self.connection = mscl.Connection.Serial(com_port)
                self.base_station = mscl.BaseStation(self.connection)
            
            self.log(f"BaseStation conectada e iniciando escucha de Nodos Inalámbricos...")
            
            # Opcional: Verificar comunicación
            if self.base_station.ping():
                self.log("Ping a BaseStation exitoso.")
            
            self.running = True
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            self.log(f"Error de conexión: {str(e)}")
            return False

    def disconnect(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        
        if self.connection:
            self.connection.disconnect()
            self.log("Desconectado.")
            self.connection = None
            self.base_station = None

    def _read_loop(self):
        self.log("Iniciando lectura de datos...")
        while self.running:
            try:
                # Obtener todos los barridos de datos (sweeps) que han llegado
                sweeps = self.base_station.getData(500) # Timeout de 500ms
                
                for sweep in sweeps:
                    node_id = sweep.nodeAddress()
                    data = {}
                    
                    # Iterar sobre los datos del barrido
                    for data_point in sweep.data():
                        # Asumimos que nos interesan los canales float (ch1, ch2, ch3, ch4)
                        # El nombre del canal suele ser ch1, ch2, etc.
                        channel_name = data_point.channelName()
                        
                        # Filtramos solo canales relevantes si es necesario
                        # Aquí guardamos todo y dejamos que la UI decida qué mostrar
                        if data_point.storedAs() == mscl.valueType_float:
                            data[channel_name] = data_point.as_float()
                        elif data_point.storedAs() == mscl.valueType_double:
                            data[channel_name] = data_point.as_double()
                    
                    if data:
                        self.data_queue.put((node_id, data))
                        
            except Exception as e:
                # self.log(f"Error en lectura: {str(e)}")
                # Evitar spam de logs si hay error continuo
                time.sleep(1)

class BalanzaApp(ttk.Window):
    def __init__(self):
        super().__init__(themename="litera")
        self.title("Sistema de Pesaje - MSCL")
        self.geometry("1280x800")
        
        # Configurar estilos personalizados para tablet
        self.style.configure('.', font=('Segoe UI', 12)) # Fuente base más grande
        
        # Configurar estilos específicos para botones grandes (Tare/Reset)
        # Modificamos los estilos por defecto de Warning y Secondary para que tengan fuente grande
        self.style.configure('Warning.TButton', font=('Segoe UI', 36, 'bold'))
        self.style.configure('Secondary.TButton', font=('Segoe UI', 24, 'bold'))
        self.style.configure('Success.TButton', font=('Segoe UI', 16, 'bold'))
        self.style.configure('Danger.TButton', font=('Segoe UI', 20, 'bold')) # Para el botón de salir
        
        self.style.configure('Header.TLabel', font=('Segoe UI', 28, 'bold'))
        self.style.configure('Sensor.TLabel', font=('Consolas', 36, 'bold'))
        self.style.configure('Total.TLabel', font=('Consolas', 72, 'bold'))
        
        # Variables de estado
        self.connected = False
        self.data_queue = queue.Queue()
        self.log_queue = queue.Queue()
        self.mscl_worker = MSCLWorker(self.data_queue, self.log_queue)
        
        # Variables de datos
        # Almacenaremos el último valor conocido para cada (node_id, channel_name)
        self.sensor_data = {} 
        # Mapeo para visualización fija en la matriz (slot_index -> (node_id, channel_name))
        self.display_slots = [None] * 4
        
        self.tare_values = [0.0] * 4
        self.net_values = [0.0] * 4
        
        # UI Setup
        self._setup_ui()
        
        # Loop de actualización
        self.after(100, self._update_loop)

    def _setup_ui(self):
        # Contenedor principal
        main_container = ttk.Frame(self, padding=20)
        main_container.pack(fill=BOTH, expand=YES)
        
        # --- Header ---
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill=X, pady=(0, 10))
        
        # Logo
        self.logo_frame = ttk.Frame(header_frame, width=100, height=50, bootstyle="light")
        self.logo_frame.pack(side=LEFT)
        self.logo_label = ttk.Label(self.logo_frame, text="LOGO", font=("Segoe UI", 10, "bold"), justify="center")
        self.logo_label.pack(padx=5, pady=5)
        
        # Título
        title_label = ttk.Label(header_frame, text="Monitor de Celdas", style="Header.TLabel", font=("Segoe UI", 18, "bold"))
        title_label.pack(side=LEFT, padx=20)
        
        # Exit Button (Red X) - Far Right
        # Eliminamos style='TButton' para que bootstyle="danger" funcione correctamente (Rojo)
        btn_exit = ttk.Button(header_frame, text="X", command=self.quit_app, bootstyle="danger", width=5, padding=(5, 5))
        btn_exit.pack(side=RIGHT, padx=5)

        # Connection Controls - Right (before Exit)
        conn_frame = ttk.Frame(header_frame)
        conn_frame.pack(side=RIGHT, padx=20)
        
        # Eliminamos entrada manual de COM, ahora será automático o fijo si se desea, 
        # pero por ahora simplificamos la UI como pidió el usuario.
        # Si se requiere autodetectar el puerto de la BaseStation, se necesitaría lógica adicional.
        # Asumiremos que el usuario quiere que al dar "Conectar" el sistema busque.
        
        self.btn_connect = ttk.Button(conn_frame, text="Conectar Sistema", command=self.toggle_connection, bootstyle="success", padding=(20, 10))
        self.btn_connect.pack(side=LEFT, padx=5)

        # --- Scale Visualization Area (Grid) ---
        scale_area = ttk.Frame(main_container)
        scale_area.pack(fill=BOTH, expand=YES, pady=10)
        
        # Grid Configuration
        scale_area.columnconfigure(0, weight=1) # Left Cells
        scale_area.columnconfigure(1, weight=2) # Center (Total)
        scale_area.columnconfigure(2, weight=1) # Right Cells
        
        scale_area.rowconfigure(0, weight=1) # Top Cells
        scale_area.rowconfigure(1, weight=0) # Spacer
        scale_area.rowconfigure(2, weight=1) # Bottom Cells

        self.sensor_labels = []
        
        # Helper to create cell frame
        def create_cell_frame(parent, idx, row, col):
            # Usamos Labelframe con estilo 'info' y borde sólido para definir bien los límites
            frame = ttk.Labelframe(parent, text=f"Celda {idx+1}", padding=15, bootstyle="info")
            frame.grid(row=row, column=col, sticky="nsew", padx=10, pady=10)
            
            # Contenedor interno para dar efecto de tarjeta
            inner = ttk.Frame(frame, bootstyle="light")
            inner.pack(fill=BOTH, expand=YES)
            
            lbl = ttk.Label(inner, text="0.00 kg", style="Sensor.TLabel", anchor="center", bootstyle="inverse-light")
            lbl.pack(expand=YES, fill=BOTH)
            self.sensor_labels.append(lbl)
            return frame

        # Cell 1: Top-Left
        create_cell_frame(scale_area, 0, 0, 0)
        # Cell 2: Top-Right
        create_cell_frame(scale_area, 1, 0, 2)
        # Cell 3: Bottom-Left
        create_cell_frame(scale_area, 2, 2, 0)
        # Cell 4: Bottom-Right
        create_cell_frame(scale_area, 3, 2, 2)

        # Center Area: Total + Actions
        # Usamos Labelframe para definir bien la sección central
        center_frame = ttk.Labelframe(scale_area, text="Control Central", padding=20, bootstyle="primary")
        center_frame.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=20, pady=20)
        
        ttk.Label(center_frame, text="PESO TOTAL", font=("Segoe UI", 16)).pack(pady=(20, 10))
        self.lbl_total = ttk.Label(center_frame, text="0.00 kg", style="Total.TLabel", bootstyle="primary", anchor="center")
        self.lbl_total.pack(pady=10, fill=X)
        
        ttk.Separator(center_frame).pack(fill=X, pady=20)
        
        # Actions
        # Aumentamos el padding vertical (segundo valor) para hacerlos más altos
        # Eliminamos style='Large.TButton' para que bootstyle funcione y use la config de Warning.TButton
        btn_tare = ttk.Button(center_frame, text="TARA", command=self.do_tare, bootstyle="warning", width=20, padding=(10, 60))
        btn_tare.pack(pady=20, fill=X)
        
        # Info de Tara
        self.lbl_tare_info = ttk.Label(center_frame, text="Tara acumulada: 0.00 kg", font=("Segoe UI", 14), bootstyle="secondary", anchor="center")
        self.lbl_tare_info.pack(pady=10, fill=X)
        
        btn_reset = ttk.Button(center_frame, text="RESET TARA", command=self.reset_tare, bootstyle="secondary", width=20, padding=(10, 40))
        btn_reset.pack(pady=20, fill=X)

        # Log (Bottom)
        log_frame = ttk.Labelframe(main_container, text="Log", padding=5, height=100)
        log_frame.pack(fill=X, side=BOTTOM)
        self.log_text = ScrolledText(log_frame, height=4, state="disabled", font=("Consolas", 8))
        self.log_text.pack(fill=BOTH, expand=YES)

    def log_message(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert(END, message + "\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def toggle_connection(self):
        if not self.connected:
            # Modo automático: No pedimos puerto, dejamos que el worker busque
            self.btn_connect.configure(state="disabled", text="Buscando...")
            self.update() # Forzar actualización de UI
            
            # Ejecutar conexión en un hilo para no congelar UI mientras busca
            def connect_thread():
                success = self.mscl_worker.connect() # Auto-detect
                self.after(0, lambda: self._post_connect(success))
            
            threading.Thread(target=connect_thread, daemon=True).start()
        else:
            self.mscl_worker.disconnect()
            self.connected = False
            self.btn_connect.configure(text="Conectar Sistema", bootstyle="success")
            self.log_message("Desconectado.")

    def _post_connect(self, success):
        self.btn_connect.configure(state="normal")
        if success:
            self.connected = True
            self.btn_connect.configure(text="Desconectar", bootstyle="danger")
            self.log_message("Sistema en línea. Escuchando nodos inalámbricos...")
        else:
            self.btn_connect.configure(text="Conectar Sistema", bootstyle="success")
            Messagebox.show_error("No se pudo detectar el receptor inalámbrico automáticamente.\nVerifique que el dispositivo esté conectado.", "Error de Conexión")

    def do_tare(self):
        # Guardar los valores actuales como tara para los slots asignados
        for i in range(4):
            key = self.display_slots[i]
            if key and key in self.sensor_data:
                self.tare_values[i] = self.sensor_data[key]
        self.log_message("Tara realizada. Valores puestos a cero.")
        self._update_display()

    def reset_tare(self):
        self.tare_values = [0.0] * 4
        self.log_message("Tara reiniciada.")
        self._update_display()

    def _update_loop(self):
        # Procesar logs
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_message(msg)
            
        # Procesar datos
        while not self.data_queue.empty():
            node_id, data = self.data_queue.get_nowait()
            
            for ch_name, value in data.items():
                key = (node_id, ch_name)
                self.sensor_data[key] = value
                
                # Asignar a un slot de visualización si no está asignado y hay espacio
                if key not in self.display_slots:
                    if None in self.display_slots:
                        idx = self.display_slots.index(None)
                        self.display_slots[idx] = key
                        # Actualizar título del sensor para identificarlo
                        self.sensor_labels[idx].master.children['!label'].configure(text=f"Nodo {node_id} - {ch_name}")
        
        if self.connected:
            self._update_display()
            
        self.after(50, self._update_loop)

    def _update_display(self):
        total = 0.0
        total_tare = 0.0
        for i in range(4):
            key = self.display_slots[i]
            raw = 0.0
            if key and key in self.sensor_data:
                raw = self.sensor_data[key]
            
            net = raw - self.tare_values[i]
            self.net_values[i] = net
            total += net
            total_tare += self.tare_values[i]
            
            # Actualizar labels individuales
            self.sensor_labels[i].configure(text=f"{net:.2f} kg")
            
        # Actualizar total
        self.lbl_total.configure(text=f"{total:.2f} kg")
        # Actualizar info de tara
        self.lbl_tare_info.configure(text=f"Tara acumulada: {total_tare:.2f} kg")

    def load_logo(self):
        # Función auxiliar para cargar logo si el usuario lo desea
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg")])
        if file_path:
            try:
                img = Image.open(file_path)
                img = img.resize((100, 50), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.logo_label.configure(image=photo, text="")
                self.logo_label.image = photo # Mantener referencia
                self.log_message(f"Logo cargado: {file_path}")
            except Exception as e:
                self.log_message(f"Error cargando logo: {e}")

    def quit_app(self):
        if Messagebox.show_question("¿Desea cerrar la aplicación?", "Salir", buttons=['No:secondary', 'Si:danger']) == 'Si':
            if self.connected:
                self.mscl_worker.disconnect()
            self.destroy()

if __name__ == "__main__":
    app = BalanzaApp()
    
    # Añadir menú contextual o botón para cargar logo
    # Por simplicidad, lo vinculamos a un doble click en el placeholder del logo
    app.logo_label.bind("<Double-Button-1>", lambda e: app.load_logo())
    app.logo_frame.bind("<Double-Button-1>", lambda e: app.load_logo())
    
    app.mainloop()
