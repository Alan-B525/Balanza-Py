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
        BG_BODY = "#e2e8f0"  # Gris más claro para mejor contraste
        BG_CARD = "#ffffff"
        PRIMARY = "#2563eb"
        SUCCESS = "#22c55e"
        WARNING = "#f59e0b"
        DANGER = "#ef4444"
        TEXT_MAIN = "#1e293b"
        TEXT_MUTED = "#64748b"
        BORDER_COLOR = "#cbd5e1"
        
        # Fonts - Más grandes para tablet
        FONT_MAIN = "Segoe UI"
        FONT_MONO = "Consolas"
        
        # Configure TFrame styles
        self.style.configure('Body.TFrame', background=BG_BODY)
        self.style.configure('Card.TFrame', background=BG_CARD, relief="solid", borderwidth=1)
        self.style.configure('CardNoBorder.TFrame', background=BG_CARD)
        
        # Configure Label styles - Más grandes
        self.style.configure('CardTitle.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 14, "bold"))
        self.style.configure('CardValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MONO, 48, "bold"))
        self.style.configure('Unit.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 18))
        self.style.configure('SensorStatus.TLabel', background=BG_CARD, foreground=SUCCESS, font=(FONT_MAIN, 12, "bold"))
        
        # Total Panel - Más prominente
        self.style.configure('TotalPanel.TFrame', background=PRIMARY)
        self.style.configure('TotalLabel.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, 18, "bold"))
        self.style.configure('TotalValue.TLabel', background=PRIMARY, foreground="white", font=(FONT_MONO, 72, "bold"))
        self.style.configure('TotalUnit.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, 20))
        
        # Buttons - Todos más grandes para tablet
        self.style.configure('Tare.TButton', font=(FONT_MAIN, 20, 'bold'))
        self.style.configure('Reset.TButton', font=(FONT_MAIN, 16, 'bold'))
        self.style.configure('Header.TButton', font=(FONT_MAIN, 14, 'bold'))
        
        # Large Dialog Buttons
        self.style.configure('Large.success.TButton', font=(FONT_MAIN, 16, 'bold'))
        self.style.configure('Large.danger.TButton', font=(FONT_MAIN, 16, 'bold'))
        
        # Header
        self.style.configure('Header.TFrame', background=BG_CARD)
        self.style.configure('HeaderTitle.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MAIN, 22, 'bold'))
        self.style.configure('HeaderSub.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 12))

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
                # Redimensionar mantendo aspecto (altura 40px)
                base_height = 40
                w_percent = (base_height / float(pil_img.size[1]))
                w_size = int((float(pil_img.size[0]) * float(w_percent)))
                
                # Compatibilidade com versões recentes de Pillow
                resample_method = getattr(Image, 'Resampling', Image).LANCZOS
                pil_img = pil_img.resize((w_size, base_height), resample_method)
                
                self.logo_img = ImageTk.PhotoImage(pil_img)
                self.logo_label = ttk.Label(brand_frame, image=self.logo_img, background="#ffffff")
                self.logo_label.pack(side=LEFT, padx=(0, 15))
                logo_loaded = True
            except Exception as e:
                print(f"Erro carregando logo: {e}")

        if not logo_loaded:
            # Fallback ao logo padrão "M"
            self.logo_label = ttk.Label(brand_frame, text="M", font=("Segoe UI", 16, "bold"), background="#2563eb", foreground="white", width=3, anchor="center")
            self.logo_label.pack(side=LEFT, padx=(0, 15))
        
        title_box = ttk.Frame(brand_frame, style='Header.TFrame')
        title_box.pack(side=LEFT)
        ttk.Label(title_box, text="Sistema de Pesagem Industrial", style='HeaderTitle.TLabel').pack(anchor="w")
        self.lbl_status = ttk.Label(title_box, text="Desconectado", style='HeaderSub.TLabel')
        self.lbl_status.pack(anchor="w")
        
        # Header Actions - Botones uniformes y grandes para tablet
        actions_frame = ttk.Frame(header_frame, style='Header.TFrame')
        actions_frame.pack(side=RIGHT)
        
        # Botón de Configuración - Mismo tamaño que los demás
        self.btn_config = ttk.Button(
            actions_frame, 
            text="⚙ CONFIG", 
            bootstyle="secondary", 
            command=self.show_configuration_dialog, 
            style='Header.TButton',
            width=12,
            padding=(15, 12)
        )
        self.btn_config.pack(side=LEFT, padx=5)
        
        # Botón Conectar/Desconectar
        self.btn_connect = ttk.Button(
            actions_frame, 
            text="CONECTAR", 
            command=self.toggle_connection, 
            bootstyle="success",
            style='Header.TButton', 
            width=14, 
            padding=(15, 12)
        )
        self.btn_connect.pack(side=LEFT, padx=5)
        
        # Botón Salir
        ttk.Button(
            actions_frame, 
            text="SAIR", 
            command=self.quit_app, 
            bootstyle="danger", 
            style='Header.TButton', 
            width=10, 
            padding=(15, 12)
        ).pack(side=LEFT, padx=5)

        # --- Separador visual ---
        ttk.Separator(main_container, orient=HORIZONTAL).pack(fill=X, pady=(0, 15))

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
            # Card con borde visible
            card = ttk.Frame(grid_area, style='Card.TFrame', padding=25)
            card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
            
            # Header con título y estado
            header = ttk.Frame(card, style='CardNoBorder.TFrame')
            header.pack(fill=X, pady=(0, 10))
            
            ttk.Label(header, text=title, style='CardTitle.TLabel').pack(side=LEFT)
            
            # Indicador de estado (más visible)
            status_frame = ttk.Frame(header, style='CardNoBorder.TFrame')
            status_frame.pack(side=RIGHT)
            
            rssi_lbl = ttk.Label(status_frame, text="●", font=("Segoe UI", 14), foreground="#94a3b8")
            rssi_lbl.pack(side=LEFT)
            status_lbl = ttk.Label(status_frame, text="Sem Sinal", font=("Segoe UI", 11, "bold"), foreground="#94a3b8")
            status_lbl.pack(side=LEFT, padx=(5, 0))
            
            # Separador
            ttk.Separator(card, orient=HORIZONTAL).pack(fill=X, pady=10)
            
            # Valor principal - Centrado y grande
            value_container = ttk.Frame(card, style='CardNoBorder.TFrame')
            value_container.pack(fill=BOTH, expand=YES)
            
            value_lbl = ttk.Label(
                value_container, 
                text="0.00", 
                font=('Consolas', 52, 'bold'), 
                foreground="#1e293b", 
                background="#ffffff",
                anchor="center"
            )
            value_lbl.pack(expand=YES)
            
            # Unidad
            ttk.Label(
                value_container, 
                text="toneladas", 
                font=('Segoe UI', 14), 
                foreground="#64748b",
                background="#ffffff"
            ).pack(pady=(5, 0))
            
            self.sensor_widgets[key] = {
                'value': value_lbl,
                'rssi': rssi_lbl,
                'status': status_lbl
            }

        # Map config keys to grid positions
        # Assuming 4 sensors for this layout
        keys = list(NODOS_CONFIG.keys())
        if len(keys) >= 4:
            create_sensor_card(keys[0], "CÉLULA SUP. ESQUERDA", 0, 0)
            create_sensor_card(keys[1], "CÉLULA SUP. DIREITA", 0, 2)
            create_sensor_card(keys[2], "CÉLULA INF. ESQUERDA", 1, 0)
            create_sensor_card(keys[3], "CÉLULA INF. DIREITA", 1, 2)

        # --- Center Control Panel ---
        control_panel = ttk.Frame(grid_area, style='Card.TFrame', padding=15)
        control_panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=8)
        
        # Sección TOTAL - Más prominente
        total_section = ttk.Frame(control_panel, style='TotalPanel.TFrame', padding=25)
        total_section.pack(fill=X)
        
        ttk.Label(total_section, text="PESO TOTAL", style='TotalLabel.TLabel', anchor="center").pack(fill=X)
        self.lbl_total = ttk.Label(total_section, text="0.00", style='TotalValue.TLabel', anchor="center")
        self.lbl_total.pack(fill=X, pady=15)
        ttk.Label(total_section, text="toneladas", style='TotalUnit.TLabel', anchor="center").pack()
        
        # Separador
        ttk.Separator(control_panel, orient=HORIZONTAL).pack(fill=X, pady=20)
        
        # Sección de Acciones
        actions_section = ttk.Frame(control_panel, style='CardNoBorder.TFrame', padding=10)
        actions_section.pack(fill=BOTH, expand=YES)
        
        # Botón TARA - Grande y prominente
        btn_tare = ttk.Button(
            actions_section, 
            text="TARA", 
            command=self.do_tare, 
            bootstyle="warning", 
            style='Tare.TButton', 
            width=18, 
            padding=(20, 18)
        )
        btn_tare.pack(pady=15)
        
        # Info de Tara
        self.lbl_tare_info = ttk.Label(
            actions_section, 
            text="Tara Acumulada: 0.00 t", 
            font=("Segoe UI", 13), 
            foreground="#64748b",
            background="#ffffff",
            anchor="center"
        )
        self.lbl_tare_info.pack(pady=10)
        
        # Botón Reset Tara
        btn_reset = ttk.Button(
            actions_section, 
            text="ZERAR TARA", 
            command=self.reset_tare, 
            bootstyle="secondary-outline", 
            style='Reset.TButton', 
            width=18, 
            padding=(15, 12)
        )
        btn_reset.pack(pady=15)

        # --- Log Area - Más compacto ---
        log_frame = ttk.Frame(main_container, style='Card.TFrame', padding=15)
        log_frame.pack(fill=X, side=BOTTOM, pady=(15, 0))
        
        log_header = ttk.Frame(log_frame, style='CardNoBorder.TFrame')
        log_header.pack(fill=X, pady=(0, 8))
        
        ttk.Label(log_header, text="📋 Registro de Eventos", font=("Segoe UI", 12, "bold"), foreground="#64748b", background="#ffffff").pack(side=LEFT)
        
        # Log com melhor visibilidade
        self.log_text = ScrolledText(log_frame, height=4, state="disabled", font=("Consolas", 10))
        self.log_text.text.configure(background="#f8fafc", foreground="#1e293b") 
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
                    messagebox.showerror("Erro", msg['payload'], parent=self)
                    self.log_message(f"[ERRO] {msg['payload']}")
                elif msg['type'] == 'LOG':
                    self.log_message(msg['payload'])
                
        except queue.Empty:
            pass
        finally:
            # Reprogramar a atualização
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
                
                # Atualizar estado visual segundo conexão
                if info.get('connected', True):
                    widgets['value'].configure(foreground="#1e293b") # Cor normal
                    widgets['rssi'].configure(text="●", foreground="#22c55e")  # Verde
                    if 'status' in widgets:
                        widgets['status'].configure(text="Ativo", foreground="#22c55e")
                else:
                    widgets['value'].configure(foreground="#cbd5e1") # Cinza (desabilitado)
                    widgets['rssi'].configure(text="●", foreground="#ef4444")  # Vermelho
                    if 'status' in widgets:
                        widgets['status'].configure(text="Sem Sinal", foreground="#ef4444")

    def _update_status(self, connected):
        self.connected = connected
        if connected:
            self.lbl_status.configure(text="● Conectado • Sistema Online", foreground="#22c55e")
            # Manter dimensões ao mudar estilo
            self.btn_connect.configure(
                text="DESCONECTAR", 
                bootstyle="danger",
                style='Header.TButton',
                width=14,
                padding=(15, 12)
            )
        else:
            self.lbl_status.configure(text="○ Desconectado", foreground="#64748b")
            # Manter dimensões ao mudar estilo
            self.btn_connect.configure(
                text="CONECTAR", 
                bootstyle="success",
                style='Header.TButton',
                width=14,
                padding=(15, 12)
            )

    def do_tare(self):
        self.command_queue.put({'cmd': 'TARE'})

    def show_large_confirmation(self, title, message):
        """Mostra um diálogo modal personalizado com fontes e botões grandes."""
        result = {'value': False}
        
        # Criar janela secundária
        dialog = ttk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("500x280")
        dialog.resizable(False, False)
        
        # Centralizar em relação à janela principal
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 250
            y = self.winfo_y() + (self.winfo_height() // 2) - 140
            dialog.geometry(f"+{x}+{y}")
        except:
            pass
            
        # Container
        frame = ttk.Frame(dialog, padding=30)
        frame.pack(fill=BOTH, expand=YES)
        
        # Mensagem grande
        lbl = ttk.Label(frame, text=message, font=("Segoe UI", 18), wraplength=440, justify="center")
        lbl.pack(pady=(10, 40), expand=YES)
        
        # Botões grandes
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
        print("DEBUG: Botão Reset pressionado")
        self.log_message("Solicitando zerar tara...")
        # Usar after para permitir que a UI seja atualizada
        self.after(100, self._show_reset_confirmation)

    def _show_reset_confirmation(self):
        resposta = self.show_large_confirmation("Confirmação", "Tem certeza que deseja zerar a tara?")
        
        print(f"DEBUG: Resposta diálogo: {resposta}")
        
        if resposta:
            self.command_queue.put({'cmd': 'RESET_TARE'})
            self.log_message("Tara zerada com sucesso.")
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
            "connection_type": "TCP",
            "serial_port": "COM3",
            "tcp_ip": "192.168.0.100",
            "tcp_port": "5000",
            "nodes": NODOS_CONFIG
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    saved_config = json.load(f)
                    current_config.update(saved_config)
            except:
                pass

        # Criar janela modal - Maior para tablet
        dialog = ttk.Toplevel(self)
        dialog.title("⚙ Configuração do Sistema")
        dialog.geometry("900x800")
        dialog.resizable(False, False)
        
        # Centrar
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 450
            y = self.winfo_y() + (self.winfo_height() // 2) - 400
            dialog.geometry(f"+{x}+{y}")
        except:
            pass

        # Estilos personalizados para abas grandes
        style = ttk.Style()
        style.configure('BigTab.TNotebook.Tab', font=('Segoe UI', 14, 'bold'), padding=(30, 15))
        style.configure('BigRadio.TRadiobutton', font=('Segoe UI', 14))

        # Container principal
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill=BOTH, expand=YES)

        # --- Abas com estilo grande ---
        notebook = ttk.Notebook(main_frame, style='BigTab.TNotebook')
        notebook.pack(fill=BOTH, expand=YES)
        
        # ==================== Tab Conexão ====================
        tab_conn = ttk.Frame(notebook, padding=30)
        notebook.add(tab_conn, text="   🔌 CONEXÃO   ")
        
        ttk.Label(tab_conn, text="Tipo de Conexão:", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 15))
        conn_type_var = tk.StringVar(value=current_config["connection_type"])
        
        # Containers para opções
        lf_serial = ttk.Labelframe(tab_conn, text="Configuração Serial", padding=25)
        lf_tcp = ttk.Labelframe(tab_conn, text="Configuração TCP/IP (BaseStation)", padding=25)

        # Função para alternar visibilidade
        def toggle_connection_options():
            if conn_type_var.get() == "SERIAL":
                lf_serial.pack(fill=X, pady=20)
                lf_tcp.pack_forget()
            else:
                lf_serial.pack_forget()
                lf_tcp.pack(fill=X, pady=20)

        # Radio buttons GRANDES para tablet
        frame_radios = ttk.Frame(tab_conn)
        frame_radios.pack(fill=X, pady=(0, 20))
        
        rb_tcp = ttk.Radiobutton(
            frame_radios, 
            text="   TCP/IP (Ethernet/Wifi)   ", 
            variable=conn_type_var, 
            value="TCP", 
            command=toggle_connection_options,
            style='BigRadio.TRadiobutton'
        )
        rb_tcp.pack(side=LEFT, padx=(0, 40), ipady=12, ipadx=15)
        
        rb_serial = ttk.Radiobutton(
            frame_radios, 
            text="   Serial (USB)   ", 
            variable=conn_type_var, 
            value="SERIAL", 
            command=toggle_connection_options,
            style='BigRadio.TRadiobutton'
        )
        rb_serial.pack(side=LEFT, ipady=12, ipadx=15)
        
        # Serial Options
        ttk.Label(lf_serial, text="Porta COM:", font=("Segoe UI", 14)).pack(anchor="w")
        entry_serial = ttk.Entry(lf_serial, font=("Segoe UI", 18))
        entry_serial.insert(0, current_config["serial_port"])
        entry_serial.pack(fill=X, pady=(8, 0), ipady=12)
        
        # TCP Options - Campos maiores
        frame_ip = ttk.Frame(lf_tcp)
        frame_ip.pack(fill=X, pady=(0, 20))
        
        ttk.Label(frame_ip, text="Endereço IP da BaseStation:", font=("Segoe UI", 14)).pack(anchor="w")
        entry_ip = ttk.Entry(frame_ip, font=("Segoe UI", 18))
        entry_ip.delete(0, END)
        entry_ip.insert(0, current_config["tcp_ip"])
        entry_ip.pack(fill=X, pady=(8, 0), ipady=12)
        
        frame_port = ttk.Frame(lf_tcp)
        frame_port.pack(fill=X)
        
        ttk.Label(frame_port, text="Porta TCP:", font=("Segoe UI", 14)).pack(anchor="w")
        entry_tcp_port = ttk.Entry(frame_port, font=("Segoe UI", 18))
        entry_tcp_port.delete(0, END)
        entry_tcp_port.insert(0, current_config["tcp_port"])
        entry_tcp_port.pack(fill=X, pady=(8, 0), ipady=12)
        
        # Info adicional
        ttk.Label(
            lf_tcp, 
            text="💡 A porta TCP típica para BaseStation é 5000", 
            font=("Segoe UI", 12), 
            foreground="#64748b"
        ).pack(anchor="w", pady=(20, 0))

        # Inicializar estado visual
        toggle_connection_options()

        # ==================== Tab Sensores ====================
        tab_nodes = ttk.Frame(notebook, padding=30)
        notebook.add(tab_nodes, text="   📡 SENSORES   ")
        
        ttk.Label(tab_nodes, text="Configuração de Nós Sem Fio", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 20))
        
        # Botão para descobrir nós (usando MSCL)
        discover_frame = ttk.Frame(tab_nodes)
        discover_frame.pack(fill=X, pady=(0, 20))
        
        self.discovered_nodes_var = tk.StringVar(value="Nenhuma busca de nós realizada")
        
        def discover_nodes():
            """Tenta descobrir nós usando MSCL se está conectado."""
            self.discovered_nodes_var.set("Procurando nós... (requer conexão ativa)")
            # Enviar comando ao backend para descobrir nós
            self.command_queue.put({'cmd': 'DISCOVER_NODES'})
            self.log_message("Solicitando descoberta de nós...")
        
        ttk.Button(
            discover_frame, 
            text="🔍 BUSCAR NÓS NA REDE", 
            command=discover_nodes,
            bootstyle="info",
            padding=(25, 15)
        ).pack(side=LEFT)
        
        ttk.Label(
            discover_frame, 
            textvariable=self.discovered_nodes_var, 
            font=("Segoe UI", 12), 
            foreground="#64748b"
        ).pack(side=LEFT, padx=(20, 0))
        
        node_entries = {}
        
        # Criar campos para cada nó - Maiores
        sensor_labels = {
            "celda_sup_izq": "📍 Célula Superior Esquerda",
            "celda_sup_der": "📍 Célula Superior Direita",
            "celda_inf_izq": "📍 Célula Inferior Esquerda",
            "celda_inf_der": "📍 Célula Inferior Direita"
        }
        
        nodes_container = ttk.Frame(tab_nodes)
        nodes_container.pack(fill=BOTH, expand=YES)
        
        for key, label_text in sensor_labels.items():
            lf_node = ttk.Labelframe(nodes_container, text=label_text, padding=18)
            lf_node.pack(fill=X, pady=10)
            
            current_node_data = current_config["nodes"].get(key, {"id": 0, "ch": "ch1"})
            
            f_inputs = ttk.Frame(lf_node)
            f_inputs.pack(fill=X)
            
            # ID - Maior
            ttk.Label(f_inputs, text="Node ID:", font=("Segoe UI", 14)).pack(side=LEFT)
            e_id = ttk.Entry(f_inputs, font=("Segoe UI", 16), width=12)
            e_id.insert(0, str(current_node_data["id"]))
            e_id.pack(side=LEFT, padx=(12, 40), ipady=8)
            
            # Channel - Maior
            ttk.Label(f_inputs, text="Canal:", font=("Segoe UI", 14)).pack(side=LEFT)
            e_ch = ttk.Entry(f_inputs, font=("Segoe UI", 16), width=10)
            e_ch.insert(0, str(current_node_data["ch"]))
            e_ch.pack(side=LEFT, padx=(12, 0), ipady=8)
            
            node_entries[key] = {"id": e_id, "ch": e_ch}

        # ==================== Botões de Ação ====================
        btn_frame = ttk.Frame(dialog, padding=30)
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
                messagebox.showinfo("Salvo", "Configuração salva.\nReinicie a aplicação para aplicar as alterações.", parent=dialog)
                dialog.destroy()
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("Erro", f"Não foi possível salvar: {e}", parent=dialog)

        # Botões GRANDES para tablet
        ttk.Button(
            btn_frame, 
            text="💾  SALVAR  ", 
            bootstyle="success", 
            command=save_config,
            padding=(40, 20),
            width=16
        ).pack(side=RIGHT)
        
        ttk.Button(
            btn_frame, 
            text="  CANCELAR  ", 
            bootstyle="secondary", 
            command=dialog.destroy,
            padding=(40, 20),
            width=16
        ).pack(side=RIGHT, padx=20)

        dialog.transient(self)
        dialog.grab_set()
        self.wait_window(dialog)
