import queue
import tkinter as tk
from tkinter import filedialog, BOTH, YES, NO, X, Y, LEFT, RIGHT, END, HORIZONTAL, BOTTOM
from PIL import Image, ImageTk

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.dialogs import Messagebox

from config import APP_TITLE, APP_SIZE, THEME_NAME, NODOS_CONFIG

class BalanzaGUI(ttk.Window):
    def __init__(self, data_queue, command_queue):
        super().__init__(themename=THEME_NAME)
        self.title(APP_TITLE)
        self.geometry(APP_SIZE)
        
        self.data_queue = data_queue
        self.command_queue = command_queue
        
        self.connected = False
        
        # Handle window close event
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        
        self._configure_styles()
        self._setup_ui()
        
        # Start update loop
        self.after(50, self.actualizar_gui)

    def _configure_styles(self):
        # Colors
        BG_BODY = "#f0f2f5"
        BG_CARD = "#ffffff"
        PRIMARY = "#2563eb"
        TEXT_MAIN = "#1e293b"
        TEXT_MUTED = "#64748b"
        
        # Fonts
        FONT_MAIN = "Segoe UI"
        FONT_MONO = "Consolas"
        
        # Configure TFrame styles
        self.style.configure('Body.TFrame', background=BG_BODY)
        self.style.configure('Card.TFrame', background=BG_CARD, relief="flat")
        
        # Configure Label styles
        self.style.configure('CardTitle.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 11, "bold"))
        self.style.configure('CardValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MONO, 42, "bold"))
        self.style.configure('Unit.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 16))
        
        # Total Panel
        self.style.configure('TotalPanel.TFrame', background=PRIMARY)
        self.style.configure('TotalLabel.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, 14))
        self.style.configure('TotalValue.TLabel', background=PRIMARY, foreground="white", font=(FONT_MONO, 64, "bold"))
        
        # Buttons
        self.style.configure('Tare.TButton', font=(FONT_MAIN, 18, 'bold'))
        self.style.configure('Reset.TButton', font=(FONT_MAIN, 18, 'bold'))
        self.style.configure('Exit.TButton', font=(FONT_MAIN, 14, 'bold'))
        self.style.configure('Connect.TButton', font=(FONT_MAIN, 14, 'bold'))
        
        # Large Dialog Buttons
        self.style.configure('Large.success.TButton', font=(FONT_MAIN, 14, 'bold'))
        self.style.configure('Large.danger.TButton', font=(FONT_MAIN, 14, 'bold'))
        
        # Header
        self.style.configure('Header.TFrame', background=BG_CARD)
        self.style.configure('HeaderTitle.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MAIN, 18, 'bold'))
        self.style.configure('HeaderSub.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 10))

    def _setup_ui(self):
        # Main Container
        main_container = ttk.Frame(self, style='Body.TFrame', padding=20)
        main_container.pack(fill=BOTH, expand=YES)
        
        # --- Header ---
        header_frame = ttk.Frame(main_container, style='Header.TFrame', padding=15)
        header_frame.pack(fill=X, pady=(0, 20))
        
        # Brand Area
        brand_frame = ttk.Frame(header_frame, style='Header.TFrame')
        brand_frame.pack(side=LEFT)
        
        # Intentar cargar logo de la empresa
        import os
        logo_path = os.path.join("assets", "logo.png")
        logo_loaded = False
        
        if os.path.exists(logo_path):
            try:
                pil_img = Image.open(logo_path)
                # Redimensionar manteniendo aspecto (altura 40px)
                base_height = 40
                w_percent = (base_height / float(pil_img.size[1]))
                w_size = int((float(pil_img.size[0]) * float(w_percent)))
                
                # Compatibilidad con versiones recientes de Pillow
                resample_method = getattr(Image, 'Resampling', Image).LANCZOS
                pil_img = pil_img.resize((w_size, base_height), resample_method)
                
                self.logo_img = ImageTk.PhotoImage(pil_img)
                self.logo_label = ttk.Label(brand_frame, image=self.logo_img, background="#ffffff")
                self.logo_label.pack(side=LEFT, padx=(0, 15))
                logo_loaded = True
            except Exception as e:
                print(f"Error cargando logo: {e}")

        if not logo_loaded:
            # Fallback al logo por defecto "M"
            self.logo_label = ttk.Label(brand_frame, text="M", font=("Segoe UI", 16, "bold"), background="#2563eb", foreground="white", width=3, anchor="center")
            self.logo_label.pack(side=LEFT, padx=(0, 15))
        
        title_box = ttk.Frame(brand_frame, style='Header.TFrame')
        title_box.pack(side=LEFT)
        ttk.Label(title_box, text="Sistema de Pesagem Industrial", style='HeaderTitle.TLabel').pack(anchor="w")
        self.lbl_status = ttk.Label(title_box, text="Desconectado", style='HeaderSub.TLabel')
        self.lbl_status.pack(anchor="w")
        
        # Header Actions
        actions_frame = ttk.Frame(header_frame, style='Header.TFrame')
        actions_frame.pack(side=RIGHT)
        
        # Botón de Configuración (Engranaje)
        btn_config = ttk.Button(actions_frame, text="⚙", bootstyle="secondary-outline", command=self.show_configuration_dialog, width=3)
        btn_config.pack(side=LEFT, padx=(0, 10))
        
        # Usar estilo explícito Large.success.TButton para asegurar tamaño de fuente inicial
        self.btn_connect = ttk.Button(actions_frame, text="CONECTAR", command=self.toggle_connection, style='Large.success.TButton', width=12, padding=(10, 8))
        self.btn_connect.pack(side=LEFT, padx=10)
        
        ttk.Button(actions_frame, text="SAIR", command=self.quit_app, bootstyle="danger", style='Exit.TButton', width=12, padding=(10, 8)).pack(side=LEFT)

        # --- Main Grid ---
        grid_area = ttk.Frame(main_container, style='Body.TFrame')
        grid_area.pack(fill=BOTH, expand=YES)
        
        grid_area.columnconfigure(0, weight=1)
        grid_area.columnconfigure(1, weight=0)
        grid_area.columnconfigure(2, weight=1)
        grid_area.rowconfigure(0, weight=1)
        grid_area.rowconfigure(1, weight=1)

        self.sensor_widgets = {} 

        # Helper to create cards mapped to config keys
        def create_sensor_card(key, title, row, col):
            card = ttk.Frame(grid_area, style='Card.TFrame', padding=20)
            card.grid(row=row, column=col, sticky="nsew", padx=10, pady=10)
            
            header = ttk.Frame(card, style='Card.TFrame')
            header.pack(fill=X, pady=(0, 15))
            
            ttk.Label(header, text=title, style='CardTitle.TLabel').pack(side=LEFT)
            rssi_lbl = ttk.Label(header, text="-- dBm", font=("Segoe UI", 9), bootstyle="secondary", padding=(5, 2))
            rssi_lbl.pack(side=RIGHT)
            
            value_container = ttk.Frame(card, style='Body.TFrame', padding=10)
            value_container.pack(fill=BOTH, expand=YES)
            
            value_lbl = ttk.Label(value_container, text="0.00", font=('Consolas', 36, 'bold'), background="#f0f2f5", foreground="#1e293b", anchor="center", width=8)
            value_lbl.pack(side=LEFT, expand=YES)
            
            ttk.Label(value_container, text="t", font=('Segoe UI', 14), background="#f0f2f5", foreground="#64748b").pack(side=RIGHT, padx=(0, 10))
            
            self.sensor_widgets[key] = {
                'value': value_lbl,
                'rssi': rssi_lbl
            }

        # Map config keys to grid positions
        # Assuming 4 sensors for this layout
        keys = list(NODOS_CONFIG.keys())
        if len(keys) >= 4:
            create_sensor_card(keys[0], "CELDA SUP. IZQ.", 0, 0)
            create_sensor_card(keys[1], "CELDA SUP. DER.", 0, 2)
            create_sensor_card(keys[2], "CELDA INF. IZQ.", 1, 0)
            create_sensor_card(keys[3], "CELDA INF. DER.", 1, 2)

        # --- Center Control Panel ---
        control_panel = ttk.Frame(grid_area, style='Card.TFrame')
        control_panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=10, pady=10)
        
        total_section = ttk.Frame(control_panel, style='TotalPanel.TFrame', padding=30)
        total_section.pack(fill=X)
        
        ttk.Label(total_section, text="TOTAL", style='TotalLabel.TLabel', anchor="center").pack(fill=X)
        self.lbl_total = ttk.Label(total_section, text="0.00", style='TotalValue.TLabel', anchor="center", width=8)
        self.lbl_total.pack(fill=X, pady=10)
        ttk.Label(total_section, text="t", background="#2563eb", foreground="white", font=("Segoe UI", 16), anchor="center").pack()
        
        actions_section = ttk.Frame(control_panel, style='Card.TFrame', padding=30)
        actions_section.pack(fill=BOTH, expand=YES)
        
        btn_tare = ttk.Button(actions_section, text="TARA", command=self.do_tare, bootstyle="warning", style='Tare.TButton', width=15, padding=15)
        btn_tare.pack(pady=20)
        
        self.lbl_tare_info = ttk.Label(actions_section, text="Tara Acumulada: 0.00 t", style='CardTitle.TLabel', anchor="center")
        self.lbl_tare_info.pack(pady=10)
        
        btn_reset = ttk.Button(actions_section, text="ZERAR TARA", command=self.reset_tare, bootstyle="secondary-outline", style='Reset.TButton', width=15, padding=15)
        btn_reset.pack(pady=10)

        # --- Log Area ---
        log_frame = ttk.Frame(main_container, style='Card.TFrame', padding=10)
        log_frame.pack(fill=X, side=BOTTOM, pady=(20, 0))
        
        ttk.Label(log_frame, text="Registro de Eventos", style='CardTitle.TLabel').pack(anchor="w", pady=(0, 5))
        
        # Explicitly set colors for visibility
        self.log_text = ScrolledText(log_frame, height=5, state="disabled", font=("Consolas", 9))
        self.log_text.text.configure(background="white", foreground="black") 
        self.log_text.pack(fill=BOTH, expand=YES)

    def actualizar_gui(self):
        """Consume mensajes de la cola y actualiza la UI."""
        try:
            while True:
                # Leer de la cola sin bloquear
                msg = self.data_queue.get_nowait()
                
                if msg['type'] == 'DATA':
                    data = msg['payload']
                    self._update_display(data)
                elif msg['type'] == 'STATUS':
                    self._update_status(msg['payload'])
                elif msg['type'] == 'ERROR':
                    from tkinter import messagebox
                    messagebox.showerror("Error", msg['payload'], parent=self)
                    self.log_message(f"[ERROR] {msg['payload']}")
                elif msg['type'] == 'LOG':
                    self.log_message(msg['payload'])
                
        except queue.Empty:
            pass
        finally:
            # Reprogramar la actualización
            self.after(50, self.actualizar_gui)

    def log_message(self, message):
        # Acceder al widget de texto interno para evitar error de 'unknown option -state'
        self.log_text.text.configure(state='normal')
        # Add timestamp
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.text.insert(END, f"[{timestamp}] {message}\n")
        self.log_text.text.see(END)
        self.log_text.text.configure(state='disabled')

    def _update_display(self, data):
        # Actualizar Total
        self.lbl_total.configure(text=f"{data['total']:.2f}")
        
        # Actualizar Tara Acumulada
        if 'total_tare' in data:
            self.lbl_tare_info.configure(text=f"Tara Acumulada: {data['total_tare']:.2f} t")
        
        # Actualizar Sensores Individuales
        sensores = data['sensores']
        for key, widgets in self.sensor_widgets.items():
            if key in sensores:
                info = sensores[key]
                
                # Actualizar valor
                widgets['value'].configure(text=f"{info['valor']:.2f}")
                
                # Actualizar estado visual según conexión
                if info.get('connected', True):
                    widgets['value'].configure(foreground="#1e293b") # Color normal
                    widgets['rssi'].configure(text="Online", bootstyle="success")
                else:
                    widgets['value'].configure(foreground="#cbd5e1") # Gris (deshabilitado)
                    widgets['rssi'].configure(text="Sin Señal", bootstyle="danger")

    def _update_status(self, connected):
        self.connected = connected
        if connected:
            self.lbl_status.configure(text="Conectado • Sistema Online", foreground="green")
            # Actualizar estilo explícitamente para mantener el tamaño de fuente
            self.btn_connect.configure(text="DESCONECTAR", style="Large.danger.TButton")
        else:
            self.lbl_status.configure(text="Desconectado", foreground="#64748b")
            # Actualizar estilo explícitamente para mantener el tamaño de fuente
            self.btn_connect.configure(text="CONECTAR", style="Large.success.TButton")

    def do_tare(self):
        self.command_queue.put({'cmd': 'TARE'})

    def show_large_confirmation(self, title, message):
        """Muestra un diálogo modal personalizado con fuentes y botones grandes."""
        result = {'value': False}
        
        # Crear ventana secundaria
        dialog = ttk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("500x280")
        dialog.resizable(False, False)
        
        # Centrar respecto a la ventana principal
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 250
            y = self.winfo_y() + (self.winfo_height() // 2) - 140
            dialog.geometry(f"+{x}+{y}")
        except:
            pass
            
        # Contenedor
        frame = ttk.Frame(dialog, padding=30)
        frame.pack(fill=BOTH, expand=YES)
        
        # Mensaje grande
        lbl = ttk.Label(frame, text=message, font=("Segoe UI", 18), wraplength=440, justify="center")
        lbl.pack(pady=(10, 40), expand=YES)
        
        # Botones grandes
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X, pady=10)
        
        def on_yes():
            result['value'] = True
            dialog.destroy()
            
        def on_no():
            dialog.destroy()
            
        btn_yes = ttk.Button(btn_frame, text="SIM", style="Large.success.TButton", width=12, command=on_yes)
        btn_yes.pack(side=LEFT, padx=20, expand=YES)
        
        btn_no = ttk.Button(btn_frame, text="NÃO", style="Large.danger.TButton", width=12, command=on_no)
        btn_no.pack(side=RIGHT, padx=20, expand=YES)

        dialog.transient(self)
        dialog.grab_set()
        self.wait_window(dialog)
        
        return result['value']

    def reset_tare(self):
        print("DEBUG: Botón Reset presionado")
        self.log_message("Solicitando Zerar Tara...")
        # Usar after para permitir que la UI se actualice
        self.after(100, self._show_reset_confirmation)

    def _show_reset_confirmation(self):
        respuesta = self.show_large_confirmation("Confirmação", "Tem certeza que deseja zerar a tara?")
        
        print(f"DEBUG: Respuesta diálogo: {respuesta}")
        
        if respuesta:
            self.command_queue.put({'cmd': 'RESET_TARE'})
            self.log_message("Comando RESET_TARE enviado.")
        else:
            self.log_message("Operação cancelada.")

    def toggle_connection(self):
        if not self.connected:
            self.command_queue.put({'cmd': 'CONNECT'})
        else:
            self.command_queue.put({'cmd': 'DISCONNECT'})

    def quit_app(self):
        if self.show_large_confirmation("Sair", "Deseja sair do sistema?"):
            self.command_queue.put({'cmd': 'EXIT'})
            self.destroy()

    def show_configuration_dialog(self):
        """Abre un diálogo para configurar conexión y nodos."""
        import json
        import os
        
        # Cargar configuración actual o usar defaults
        config_path = "settings.json"
        current_config = {
            "connection_type": "TCP", # Default a TCP por solicitud
            "serial_port": "COM3",
            "tcp_ip": "192.168.0.100",
            "tcp_port": "8000",
            "nodes": NODOS_CONFIG
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    saved_config = json.load(f)
                    current_config.update(saved_config)
            except:
                pass

        # Crear ventana modal
        dialog = ttk.Toplevel(self)
        dialog.title("Configuración del Sistema")
        dialog.geometry("700x600")
        dialog.resizable(False, False)
        
        # Centrar
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 350
            y = self.winfo_y() + (self.winfo_height() // 2) - 300
            dialog.geometry(f"+{x}+{y}")
        except:
            pass

        # --- Pestañas ---
        notebook = ttk.Notebook(dialog)
        notebook.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        
        # Tab Conexión
        tab_conn = ttk.Frame(notebook, padding=20)
        notebook.add(tab_conn, text="Conexión")
        
        ttk.Label(tab_conn, text="Tipo de Conexión:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))
        conn_type_var = tk.StringVar(value=current_config["connection_type"])
        
        # Contenedores para opciones
        lf_serial = ttk.LabelFrame(tab_conn, text="Configuración Serial", padding=15)
        lf_tcp = ttk.LabelFrame(tab_conn, text="Configuración TCP/IP", padding=15)

        # Función para alternar visibilidad
        def toggle_connection_options():
            if conn_type_var.get() == "SERIAL":
                lf_serial.pack(fill=X, pady=10)
                lf_tcp.pack_forget()
            else:
                lf_serial.pack_forget()
                lf_tcp.pack(fill=X, pady=10)

        frame_radios = ttk.Frame(tab_conn)
        frame_radios.pack(fill=X, pady=(0, 15))
        ttk.Radiobutton(frame_radios, text="TCP/IP (Ethernet/Wifi)", variable=conn_type_var, value="TCP", command=toggle_connection_options).pack(side=LEFT, padx=(0, 20))
        ttk.Radiobutton(frame_radios, text="Serial (USB)", variable=conn_type_var, value="SERIAL", command=toggle_connection_options).pack(side=LEFT)
        
        # Serial Options (Manual)
        ttk.Label(lf_serial, text="Puerto COM:").pack(anchor="w")
        entry_serial = ttk.Entry(lf_serial)
        entry_serial.insert(0, current_config["serial_port"])
        entry_serial.pack(fill=X, pady=(5, 0))
        
        # TCP Options
        ttk.Label(lf_tcp, text="Dirección IP:").pack(anchor="w")
        entry_ip = ttk.Entry(lf_tcp)
        entry_ip.insert(0, current_config["tcp_ip"])
        entry_ip.pack(fill=X, pady=(5, 10))
        
        ttk.Label(lf_tcp, text="Puerto TCP:").pack(anchor="w")
        entry_tcp_port = ttk.Entry(lf_tcp)
        entry_tcp_port.insert(0, current_config["tcp_port"])
        entry_tcp_port.pack(fill=X, pady=(5, 0))

        # Inicializar estado visual
        toggle_connection_options()

        # Tab Nodos
        tab_nodes = ttk.Frame(notebook, padding=20)
        notebook.add(tab_nodes, text="Sensores")
        
        node_entries = {}
        
        # Crear campos para cada nodo
        sensor_labels = {
            "celda_sup_izq": "Celda Superior Izquierda",
            "celda_sup_der": "Celda Superior Derecha",
            "celda_inf_izq": "Celda Inferior Izquierda",
            "celda_inf_der": "Celda Inferior Derecha"
        }
        
        # Usar Grid para mejor alineación
        nodes_container = ttk.Frame(tab_nodes)
        nodes_container.pack(fill=BOTH, expand=YES)
        
        row = 0
        for key, label_text in sensor_labels.items():
            lf_node = ttk.LabelFrame(nodes_container, text=label_text, padding=10)
            lf_node.pack(fill=X, pady=5)
            
            current_node_data = current_config["nodes"].get(key, {"id": 0, "ch": "ch1"})
            
            f_inputs = ttk.Frame(lf_node)
            f_inputs.pack(fill=X)
            
            # ID
            ttk.Label(f_inputs, text="Node ID:", width=10).pack(side=LEFT)
            e_id = ttk.Entry(f_inputs, width=15)
            e_id.insert(0, str(current_node_data["id"]))
            e_id.pack(side=LEFT, padx=(0, 20))
            
            # Channel
            ttk.Label(f_inputs, text="Canal:", width=8).pack(side=LEFT)
            e_ch = ttk.Entry(f_inputs, width=10)
            e_ch.insert(0, str(current_node_data["ch"]))
            e_ch.pack(side=LEFT)
            
            node_entries[key] = {"id": e_id, "ch": e_ch}
            row += 1

        # Botones de Acción
        btn_frame = ttk.Frame(dialog, padding=20)
        btn_frame.pack(fill=X, side=BOTTOM)
        
        def save_config():
            new_config = {
                "connection_type": conn_type_var.get(),
                "serial_port": entry_serial.get(),
                "tcp_ip": entry_ip.get(),
                "tcp_port": entry_tcp_port.get(),
                "nodes": {}
            }
            
            for key, inputs in node_entries.items():
                try:
                    nid = int(inputs["id"].get())
                except:
                    nid = 0
                new_config["nodes"][key] = {
                    "id": nid,
                    "ch": inputs["ch"].get()
                }
            
            try:
                with open(config_path, 'w') as f:
                    json.dump(new_config, f, indent=4)
                
                from tkinter import messagebox
                messagebox.showinfo("Guardado", "Configuración guardada.\nReinicie la aplicación para aplicar cambios.", parent=dialog)
                dialog.destroy()
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("Error", f"No se pudo guardar: {e}", parent=dialog)

        ttk.Button(btn_frame, text="Guardar Configuración", bootstyle="primary", command=save_config).pack(side=RIGHT)
        ttk.Button(btn_frame, text="Cancelar", bootstyle="secondary", command=dialog.destroy).pack(side=RIGHT, padx=10)

        dialog.transient(self)
        dialog.grab_set()
        self.wait_window(dialog)
