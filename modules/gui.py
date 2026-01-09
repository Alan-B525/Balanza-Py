import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, BOTH, YES, NO, X, Y, LEFT, RIGHT, END, HORIZONTAL, BOTTOM, TOP
from PIL import Image, ImageTk

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText

from config import APP_TITLE, APP_SIZE, THEME_NAME, NODOS_CONFIG

# Configurar matplotlib ANTES de cualquier import de backends
# Esto evita bloqueos cuando se abre el wizard de calibración
try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("[GUI] Warning: Matplotlib no disponible para gráficos de calibración")

class BalanzaGUI(ttk.Window):
    def __init__(self, data_queue, command_queue, data_processor=None):
        super().__init__(themename=THEME_NAME)
        self.data_processor = data_processor
        self.title(APP_TITLE)
        
        # Remover barra de ttulo de Windows (modo frameless)
        self.overrideredirect(True)
        
        # Obtener tamao de pantalla y usar pantalla completa
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{screen_width}x{screen_height}+0+0")
        
        # Guardar referencia para mover ventana (drag)
        self._drag_data = {"x": 0, "y": 0}
        
        self.data_queue = data_queue
        self.command_queue = command_queue
        
        self.connected = False
        
        # Almacenar ltimos datos para calibracin
        self._last_sensor_data = {}
        
        # Almacenar nodos descubiertos
        self._discovered_nodes = []
        
        # Control de visualización de decimales (por defecto: SIN decimales)
        self._show_decimals = False
        
        # Variables para conexin asncrona
        self._connection_thread = None
        self._cancel_connection = False
        
        # Handle window close event
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        
        self._configure_styles()
        self._setup_ui()
        
        # Start update loop
        self.after(50, self.actualizar_gui)
        
        # Iniciar conexo automaticamente removida para evitar travamento na inicializacao
        # self.after(500, self._auto_connect_on_startup)

    def _configure_styles(self):
        # Colors
        BG_BODY = "#e2e8f0"  # Gris ms claro para mejor contraste
        BG_CARD = "#ffffff"
        PRIMARY = "#2563eb"
        SUCCESS = "#22c55e"
        WARNING = "#f59e0b"
        DANGER = "#ef4444"
        TEXT_MAIN = "#1e293b"
        TEXT_MUTED = "#64748b"
        BORDER_COLOR = "#cbd5e1"
        
        # Fonts - Ms grandes para tablet
        FONT_MAIN = "Segoe UI"
        FONT_MONO = "Consolas"
        
        # Configure TFrame styles
        self.style.configure('Body.TFrame', background=BG_BODY)
        self.style.configure('Card.TFrame', background=BG_CARD, relief="solid", borderwidth=1)
        self.style.configure('CardNoBorder.TFrame', background=BG_CARD)
        
        # Configure Label styles - MS GRANDES para mejor visibilidad
        self.style.configure('CardTitle.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 16, "bold"))
        self.style.configure('CardValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MONO, 48, "bold"))
        self.style.configure('Unit.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 18))
        self.style.configure('SensorStatus.TLabel', background=BG_CARD, foreground=SUCCESS, font=(FONT_MAIN, 13, "bold"))
        
        # Total Panel - MUY PROMINENTE para nfasis mximo
        self.style.configure('TotalPanel.TFrame', background=PRIMARY)
        self.style.configure('TotalLabel.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, 28, "bold"))
        self.style.configure('TotalValue.TLabel', background=PRIMARY, foreground="white", font=(FONT_MONO, 120, "bold"))
        self.style.configure('TotalUnit.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, 36))
        
        # Total Panel DANGER - Cuando hay sensor desconectado (ROJO)
        self.style.configure('TotalPanelDanger.TFrame', background=DANGER)
        self.style.configure('TotalLabelDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MAIN, 28, "bold"))
        self.style.configure('TotalValueDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MONO, 120, "bold"))
        self.style.configure('TotalUnitDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MAIN, 36))
        
        # Tara Info - Ms visible
        self.style.configure('TareInfo.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 18, "bold"))
        
        # Buttons - Todos ms grandes para tablet
        self.style.configure('TButton', font=(FONT_MAIN, 14, 'bold'))  # Default global BOLD
        self.style.configure('Tare.TButton', font=(FONT_MAIN, 22, 'bold'))
        self.style.configure('Reset.TButton', font=(FONT_MAIN, 18, 'bold'))
        self.style.configure('Header.TButton', font=(FONT_MAIN, 16, 'bold'))
        
        # Large Dialog Buttons
        self.style.configure('Large.success.TButton', font=(FONT_MAIN, 18, 'bold'))
        self.style.configure('Large.danger.TButton', font=(FONT_MAIN, 18, 'bold'))
        self.style.configure('Large.info.TButton', font=(FONT_MAIN, 18, 'bold'))
        self.style.configure('Large.warning.TButton', font=(FONT_MAIN, 18, 'bold'))

        # Tabs config - Pestañas gruesas, anchas y centradas
        self.style.configure('TNotebook.Tab', font=(FONT_MAIN, 16, 'bold'), padding=(40, 15))
        self.style.map('TNotebook.Tab', 
                      background=[('selected', PRIMARY)], 
                      foreground=[('selected', 'white')])

        # Combobox - Más grandes para tablet (dropdown legible)
        self.style.configure('TCombobox', font=(FONT_MAIN, 14), padding=8)
        # Aumentar altura del dropdown list
        self.option_add('*TCombobox*Listbox.font', (FONT_MAIN, 14))
        self.option_add('*TCombobox*Listbox*selectBackground', PRIMARY)
        self.option_add('*TCombobox*Listbox*selectForeground', 'white')

        # Header
        self.style.configure('Header.TFrame', background=BG_CARD)
        self.style.configure('HeaderTitle.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MAIN, 22, "bold"))
        self.style.configure('HeaderSub.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 12))

    def _setup_ui(self):
        # Main Container
        main_container = ttk.Frame(self, style='Body.TFrame', padding=15)
        main_container.pack(fill=BOTH, expand=YES)
        
        # --- Header (Barra personalizada para reemplazar barra de Windows) ---
        header_frame = ttk.Frame(main_container, style='Header.TFrame', padding=12)
        header_frame.pack(fill=X, pady=(0, 15))
        
        # Permitir arrastrar la ventana desde el header
        header_frame.bind("<Button-1>", self._start_drag)
        header_frame.bind("<B1-Motion>", self._on_drag)
        
        # Brand Area
        brand_frame = ttk.Frame(header_frame, style='Header.TFrame')
        brand_frame.pack(side=LEFT)
        brand_frame.bind("<Button-1>", self._start_drag)
        brand_frame.bind("<B1-Motion>", self._on_drag)
        
        # Intentar cargar logos de la empresa (2 logos diferentes)
        import os
        assets_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
        
        # Rutas de logos (logo_left.png, logo_right.png, o logo.png como fallback)
        logo_left_path = os.path.join(assets_path, "logo_left.png")
        logo_right_path = os.path.join(assets_path, "logo_right.png")
        logo_fallback_path = os.path.join(assets_path, "logo.png")
        
        self.logo_left_img = None
        self.logo_right_img = None
        
        # Tamao de logos (ms grandes)
        logo_height = 100
        resample_method = getattr(Image, 'Resampling', Image).LANCZOS
        
        def load_logo(path, height):
            """Cargar y redimensionar un logo."""
            if os.path.exists(path):
                try:
                    pil_img = Image.open(path)
                    w_percent = (height / float(pil_img.size[1]))
                    w_size = int((float(pil_img.size[0]) * float(w_percent)))
                    pil_img_resized = pil_img.resize((w_size, height), resample_method)
                    return ImageTk.PhotoImage(pil_img_resized)
                except Exception as e:
                    print(f"Erro carregando logo {path}: {e}")
            return None
        
        # Cargar logo izquierdo
        self.logo_left_img = load_logo(logo_left_path, logo_height)
        if not self.logo_left_img:
            self.logo_left_img = load_logo(logo_fallback_path, logo_height)
        
        # Cargar logo derecho
        self.logo_right_img = load_logo(logo_right_path, logo_height)
        if not self.logo_right_img:
            self.logo_right_img = load_logo(logo_fallback_path, logo_height)
        
        # Ttulo sin logo
        title_box = ttk.Frame(brand_frame, style='Header.TFrame')
        title_box.pack(side=LEFT)
        ttk.Label(title_box, text="Sistema de Pesagem Industrial", style='HeaderTitle.TLabel').pack(anchor="w")
        self.lbl_status = ttk.Label(title_box, text="Desconectado", style='HeaderSub.TLabel')
        self.lbl_status.pack(anchor="w")
        
        # Header Actions - Botones uniformes y grandes para tablet
        actions_frame = ttk.Frame(header_frame, style='Header.TFrame')
        actions_frame.pack(side=RIGHT)
        
        # Espaciador para centrar mejor los botones
        ttk.Frame(actions_frame, width=50, style='Header.TFrame').pack(side=LEFT)
        
        # Botn de decimales - Antes de CONFIG, ms al centro
        self.btn_decimals = ttk.Button(
            actions_frame, 
            text="0.00", 
            bootstyle="primary", 
            command=self.toggle_decimals, 
            style='Header.TButton',
            width=8,
            padding=(15, 12)
        )
        self.btn_decimals.pack(side=LEFT, padx=5)
        
        # Botn de Configuracin - Color info (azul)
        self.btn_config = ttk.Button(
            actions_frame, 
            text="CONFIG", 
            bootstyle="info", 
            command=self.show_configuration_dialog, 
            style='Header.TButton',
            width=12,
            padding=(15, 12)
        )
        self.btn_config.pack(side=LEFT, padx=5)
        
        # Botn Conectar/Desconectar - Color success (verde)
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
        
        # Separador visual antes del botn SAIR
        ttk.Frame(actions_frame, width=30, style='Header.TFrame').pack(side=LEFT)
        
        # Botn Salir - Rojo y separado
        ttk.Button(
            actions_frame, 
            text="SAIR", 
            command=self.quit_app, 
            bootstyle="danger", 
            style='Header.TButton', 
            width=10, 
            padding=(15, 12)
        ).pack(side=LEFT, padx=(20, 5))

        # --- Separador visual ---
        ttk.Separator(main_container, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))

        # --- Main Grid (Layout Original: Sensores | Total | Sensores) ---
        grid_area = ttk.Frame(main_container, style='Body.TFrame')
        grid_area.pack(fill=BOTH, expand=YES)
        
        # Columnas con tamao FIJO usando minsize para evitar que cambien
        grid_area.columnconfigure(0, weight=1, minsize=280)
        grid_area.columnconfigure(1, weight=2, minsize=400)  # Centro ms ancho para el TOTAL
        grid_area.columnconfigure(2, weight=1, minsize=280)
        grid_area.rowconfigure(0, weight=1, minsize=200)
        grid_area.rowconfigure(1, weight=1, minsize=200)

        self.sensor_widgets = {} 

        # Helper to create cards mapped to config keys
        def create_sensor_card(key, title, row, col):
            # Card con borde visible y tamao uniforme
            card = ttk.Frame(grid_area, style='Card.TFrame', padding=20)
            card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
            card.grid_propagate(False)  # NO permitir que el contenido cambie el tamao
            
            # Header con ttulo y estado
            header = ttk.Frame(card, style='CardNoBorder.TFrame')
            header.pack(fill=X, pady=(0, 8))
            
            ttk.Label(header, text=title, style='CardTitle.TLabel').pack(side=LEFT)
            
            # Indicador de estado (ms visible)
            status_frame = ttk.Frame(header, style='CardNoBorder.TFrame')
            status_frame.pack(side=RIGHT)
            
            rssi_lbl = ttk.Label(status_frame, text="", font=("Segoe UI", 16), foreground="#94a3b8")
            rssi_lbl.pack(side=LEFT)
            status_lbl = ttk.Label(status_frame, text="Sem Sinal", font=("Segoe UI", 12, "bold"), foreground="#94a3b8")
            status_lbl.pack(side=LEFT, padx=(5, 0))
            
            # Separador
            ttk.Separator(card, orient=HORIZONTAL).pack(fill=X, pady=8)
            
            # Valor principal - Centrado con ancho fijo - MS GRANDE
            value_container = ttk.Frame(card, style='CardNoBorder.TFrame')
            value_container.pack(fill=BOTH, expand=YES)
            
            value_lbl = ttk.Label(
                value_container, 
                text="0.00", 
                font=('Consolas', 64, 'bold'),  # Ms grande: 56 -> 64
                foreground="#1e293b", 
                background="#ffffff",
                anchor="center",
                width=8  # Ancho fijo para evitar cambios
            )
            value_lbl.pack(expand=YES)
            
            # Unidade
            ttk.Label(
                value_container, 
                text="t", 
                font=('Segoe UI', 15), 
                foreground="#64748b",
                background="#ffffff"
            ).pack(pady=(5, 0))
            
            self.sensor_widgets[key] = {
                'value': value_lbl,
                'rssi': rssi_lbl,
                'status': status_lbl
            }

        # Crear sensores en posiciones: izquierda y derecha (numerados)
        keys = list(NODOS_CONFIG.keys())
        if len(keys) >= 4:
            create_sensor_card(keys[0], "CELULA 1", 0, 0)
            create_sensor_card(keys[1], "CELULA 2", 0, 2)
            create_sensor_card(keys[2], "CELULA 3", 1, 0)
            create_sensor_card(keys[3], "CELULA 4", 1, 2)
        elif len(keys) >= 2:
            # Fallback si solo hay 2 celdas configuradas
            create_sensor_card(keys[0], "CELULA 1", 0, 0)
            create_sensor_card(keys[1], "CELULA 2", 0, 2)

        # --- PANEL CENTRAL: TOTAL (MS GRANDE) ---
        control_panel = ttk.Frame(grid_area, style='Card.TFrame', padding=15)
        control_panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=8)
        control_panel.grid_propagate(False)  # Tamao fijo
        
        # Seccin TOTAL con fondo azul - MUY GRANDE Y PROMINENTE
        # Guardar referencia para poder cambiar color en caso de desconexin
        self.total_section = ttk.Frame(control_panel, style='TotalPanel.TFrame', padding=35)
        self.total_section.pack(fill=BOTH, expand=YES)
        
        self.lbl_total_title = ttk.Label(self.total_section, text="PESO TOTAL", style='TotalLabel.TLabel', anchor="center")
        self.lbl_total_title.pack(fill=X)
        self.lbl_total = ttk.Label(
            self.total_section, 
            text="0", 
            style='TotalValue.TLabel', 
            anchor="center",
            width=10  # Largura fixa para evitar mudanças
        )
        self.lbl_total.pack(fill=X, pady=20)
        self.lbl_total_unit = ttk.Label(self.total_section, text="t", style='TotalUnit.TLabel', anchor="center")
        self.lbl_total_unit.pack()
        
        # Separador dentro del panel
        ttk.Separator(control_panel, orient=HORIZONTAL).pack(fill=X, pady=15)
        
        # Seccin de Acciones debajo del total
        actions_section = ttk.Frame(control_panel, style='CardNoBorder.TFrame', padding=10)
        actions_section.pack(fill=X)
        
        # Info de Tara - MS GRANDE Y VISIBLE
        self.lbl_tare_info = ttk.Label(
            actions_section, 
            text="Tara Acumulada: 0 t", 
            style='TareInfo.TLabel',
            anchor="center"
        )
        self.lbl_tare_info.pack(pady=(0, 20))
        
        # Frame para botones lado a lado
        btn_row = ttk.Frame(actions_section, style='CardNoBorder.TFrame')
        btn_row.pack(fill=X)
        
        # Botão TARA - Grande e proeminente
        btn_tare = ttk.Button(
            btn_row, 
            text="TARA", 
            command=self.do_tare, 
            bootstyle="warning", 
            style='Tare.TButton', 
            width=12, 
            padding=(25, 18)
        )
        btn_tare.pack(side=LEFT, expand=YES, padx=5)
        
        # Botão Limpar Tara - MESMO TAMANHO que TARA
        btn_reset = ttk.Button(
            btn_row, 
            text="LIMPAR TARA", 
            command=self.reset_tare, 
            bootstyle="secondary", 
            style='Tare.TButton',  # Mesmo estilo que TARA
            width=12, 
            padding=(25, 18)  # Mesmo padding que TARA
        )
        btn_reset.pack(side=LEFT, expand=YES, padx=5)
        
        # --- Log Area con LOGOS GRANDES a cada lado ---
        log_frame = ttk.Frame(main_container, style='Card.TFrame', padding=12)
        log_frame.pack(fill=X, side=BOTTOM, pady=(10, 0))
        
        # Usar grid para que coincida con las proporciones de la columna central
        log_container = ttk.Frame(log_frame, style='CardNoBorder.TFrame')
        log_container.pack(fill=X)
        
        # Configurar columnas con los mismos pesos que el grid principal (1:2:1)
        log_container.columnconfigure(0, weight=1)  # Logo izquierdo
        log_container.columnconfigure(1, weight=2)  # Log central (mismo peso que columna TOTAL)
        log_container.columnconfigure(2, weight=1)  # Logo derecho
        
        # Logo GRANDE a la izquierda (logo_left.png o logo.png)
        if self.logo_left_img:
            logo_left = ttk.Label(log_container, image=self.logo_left_img, background="#ffffff")
            logo_left.grid(row=0, column=0, sticky="", padx=20)
        
        # Log centrado (misma proporcin que columna central)
        log_center = ttk.Frame(log_container, style='CardNoBorder.TFrame')
        log_center.grid(row=0, column=1, sticky="ew", padx=10)
        
        log_header = ttk.Frame(log_center, style='CardNoBorder.TFrame')
        log_header.pack(fill=X, pady=(0, 5))
        ttk.Label(log_header, text=" Registro de Eventos", font=("Segoe UI", 11, "bold"), foreground="#64748b", background="#ffffff").pack(anchor="center")
        
        self.log_text = ScrolledText(log_center, height=3, state="disabled", font=("Consolas", 9))
        self.log_text.text.configure(background="#f8fafc", foreground="#1e293b") 
        self.log_text.pack(fill=X)
        
        # Logo GRANDE a la derecha (logo_right.png o logo.png)
        if self.logo_right_img:
            logo_right = ttk.Label(log_container, image=self.logo_right_img, background="#ffffff")
            logo_right.grid(row=0, column=2, sticky="", padx=20)

    def _start_drag(self, event):
        """Inicio del arrastre de la ventana."""
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag(self, event):
        """Mover la ventana durante el arrastre."""
        deltax = event.x - self._drag_data["x"]
        deltay = event.y - self._drag_data["y"]
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")

    def actualizar_gui(self):
        """Consume mensajes de la cola y actualiza la UI."""
        try:
            while True:
                # Leer de la cola sin bloquear
                msg = self.data_queue.get_nowait()
                
                if msg['type'] == 'DATA':
                    data = msg['payload']
                    self._last_sensor_data = data  # Guardar para calibracin
                    self._update_display(data)
                elif msg['type'] == 'STATUS':
                    self._update_status(msg['payload'])
                elif msg['type'] == 'ERROR':
                    self.show_alert("Erro", msg['payload'], "error")
                    self.log_message(f"[ERRO] {msg['payload']}")
                elif msg['type'] == 'LOG':
                    self.log_message(msg['payload'])
                elif msg['type'] == 'CONNECTION_PROGRESS':
                    # Actualizar dialogo de conexion con progreso
                    payload = msg['payload']
                    self._update_connection_progress(payload)
                elif msg['type'] == 'SENSOR_DISCONNECT':
                    # Mostrar dialogo de alerta de sensor desconectado
                    payload = msg['payload']
                    self._show_sensor_disconnect_dialog(payload)
                elif msg['type'] == 'SENSOR_RECONNECTED':
                    # Cerrar dialogo si esta abierto y notificar
                    payload = msg['payload']
                    self._handle_sensor_reconnected(payload)
                elif msg['type'] == 'RECONNECT_PROGRESS':
                    # Actualizar progreso de reconexion en el dialogo
                    payload = msg['payload']
                    self._update_reconnect_progress(payload)
                elif msg['type'] == 'RECONNECT_FAILED':
                    # Notificar fallo de reconexion
                    payload = msg['payload']
                    self._handle_reconnect_failed(payload)
                elif msg['type'] == 'DISCOVERED_NODES':
                    # Actualizar lista de nodos descubiertos en configuracin
                    payload = msg['payload']
                    self._handle_discovered_nodes(payload)
                
        except queue.Empty:
            pass
        finally:
            # Reprogramar a atualizao
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
        # Guardar datos para actualización cuando cambie modo decimales
        self._last_sensor_data = data
        
        # Atualizar Tara Acumulada em Toneladas
        if 'total_tare' in data:
            tara_ton = data['total_tare']
            self.lbl_tare_info.configure(text=f"Tara Acumulada: {self._format_weight(tara_ton)} t")
        
        # Verificar si hay sensores desconectados para cambiar color del panel
        any_disconnected = data.get('any_disconnected', False)
        
        # Tambn verificar manualmente en los sensores
        if not any_disconnected:
            for sensor_info in data.get('sensores', {}).values():
                if not sensor_info.get('connected', True):
                    any_disconnected = True
                    break
        
        # Mudar cor do painel TOTAL segundo estado de sensores - FAIL-SAFE
        if any_disconnected:
            # VERMELHO - Há sensor(es) desconectado(s) - SISTEMA PARADO
            self.total_section.configure(style='TotalPanelDanger.TFrame')
            self.lbl_total_title.configure(text="ERRO DE COMUNICAÇÃO", style='TotalLabelDanger.TLabel')
            self.lbl_total.configure(text="---", style='TotalValueDanger.TLabel')
            self.lbl_total_unit.configure(text="SISTEMA PARADO", style='TotalUnitDanger.TLabel')
        else:
            # AZUL - Todos os sensores conectados (normal)
            self.total_section.configure(style='TotalPanel.TFrame')
            self.lbl_total_title.configure(text="PESO TOTAL", style='TotalLabel.TLabel')
            peso_ton = data['total']
            self.lbl_total.configure(text=f"{self._format_weight(peso_ton)}", style='TotalValue.TLabel')
            self.lbl_total_unit.configure(text="t", style='TotalUnit.TLabel')
        
        # Actualizar Sensores Individuales
        sensores = data['sensores']
        for key, widgets in self.sensor_widgets.items():
            if key in sensores:
                info = sensores[key]
                
                # Actualizar valor - Usar formato según configuración de decimales
                valor_ton = info['valor']
                widgets['value'].configure(text=f"{self._format_weight(valor_ton)}")
                
                # Atualizar estado visual segundo conexo
                if info.get('connected', True):
                    widgets['value'].configure(foreground="#1e293b") # Cor normal
                    widgets['rssi'].configure(text="", foreground="#22c55e")  # Verde
                    if 'status' in widgets:
                        widgets['status'].configure(text="Ativo", foreground="#22c55e")
                else:
                    widgets['value'].configure(foreground="#cbd5e1") # Cinza (desabilitado)
                    widgets['rssi'].configure(text="", foreground="#ef4444")  # Vermelho
                    if 'status' in widgets:
                        widgets['status'].configure(text="Sem Sinal", foreground="#ef4444")

    def _update_status(self, connected):
        self.connected = connected
        if connected:
            self.lbl_status.configure(text=" Conectado  Sistema Online", foreground="#22c55e")
            # Manter dimenses ao mudar estilo
            self.btn_connect.configure(
                text="DESCONECTAR", 
                bootstyle="danger",
                style='Header.TButton',
                width=14,
                padding=(15, 12)
            )
        else:
            self.lbl_status.configure(text=" Desconectado", foreground="#64748b")
            # Manter dimenses ao mudar estilo
            self.btn_connect.configure(
                text="CONECTAR", 
                bootstyle="success",
                style='Header.TButton',
                width=14,
                padding=(15, 12)
            )

    def _show_numeric_keypad(self, entry_widget, title="Inserir Valor"):
        """Teclado numérico virtual grande y funcional."""
        # Cerrar teclado anterior si existe
        if hasattr(self, '_active_keypad') and self._active_keypad:
            try:
                self._active_keypad.destroy()
            except:
                pass
            self._active_keypad = None
        
        # Valor actual del entry
        current_value = entry_widget.get() if hasattr(entry_widget, 'get') else ""
        
        # Tamaño del teclado
        kp_width, kp_height = 480, 650
        
        # Calcular posición centrada en pantalla
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - kp_width) // 2
        y = (screen_h - kp_height) // 2
        
        # Obtener la ventana padre (puede ser un diálogo)
        parent = entry_widget.winfo_toplevel()
        
        # Crear ventana del teclado como hija del padre del entry
        keypad = tk.Toplevel(parent)
        keypad.title(title)
        keypad.geometry(f"{kp_width}x{kp_height}+{x}+{y}")
        keypad.resizable(False, False)
        keypad.transient(parent)  # Asociado al padre
        keypad.attributes('-topmost', True)
        keypad.configure(bg="#222222")
        self._active_keypad = keypad
        
        # Variable para el valor
        kp_value = tk.StringVar(value=current_value)
        
        # Flag para saber si es la primera pulsación
        first_press = [True]
        
        # Funciones
        def press_digit(d):
            current = kp_value.get()
            # Si es la primera pulsación y el valor es "0", reemplazarlo
            if first_press[0] and current == "0" and d != ".":
                kp_value.set(d)
                first_press[0] = False
                return
            first_press[0] = False
            if d == "." and "." in current:
                return
            kp_value.set(current + d)
        
        def press_backspace():
            kp_value.set(kp_value.get()[:-1])
        
        def press_clear():
            kp_value.set("")
        
        def close_keypad():
            self._active_keypad = None
            keypad.grab_release()
            keypad.destroy()
        
        def confirm_and_close():
            val = kp_value.get()
            try:
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, val)
            except:
                pass
            try:
                var_name = entry_widget.cget('textvariable')
                if var_name:
                    entry_widget.nametowidget(var_name).set(val)
            except:
                pass
            self._active_keypad = None
            keypad.grab_release()
            keypad.destroy()
        
        # Cerrar con X de la ventana
        keypad.protocol("WM_DELETE_WINDOW", close_keypad)
        
        # Frame principal con padding
        main = ttk.Frame(keypad, padding=20)
        main.pack(fill=BOTH, expand=YES, padx=4, pady=4)
        
        # Display
        display = ttk.Entry(main, textvariable=kp_value, font=("Consolas", 36), 
                           justify="center", state="readonly")
        display.pack(fill=X, pady=(0, 20), ipady=12)
        
        # Frame para botones
        all_btns = ttk.Frame(main)
        all_btns.pack(fill=BOTH, expand=YES)
        
        for i in range(5):
            all_btns.rowconfigure(i, weight=1)
        for i in range(3):
            all_btns.columnconfigure(i, weight=1)
        
        # Padding de botones
        pad_num = (25, 22)
        pad_act = (20, 22)
        
        # Fila 0: 7 8 9
        ttk.Button(all_btns, text="7", command=lambda: press_digit("7"), 
                  bootstyle="light", padding=pad_num).grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="8", command=lambda: press_digit("8"), 
                  bootstyle="light", padding=pad_num).grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="9", command=lambda: press_digit("9"), 
                  bootstyle="light", padding=pad_num).grid(row=0, column=2, sticky="nsew", padx=4, pady=4)
        
        # Fila 1: 4 5 6
        ttk.Button(all_btns, text="4", command=lambda: press_digit("4"), 
                  bootstyle="light", padding=pad_num).grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="5", command=lambda: press_digit("5"), 
                  bootstyle="light", padding=pad_num).grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="6", command=lambda: press_digit("6"), 
                  bootstyle="light", padding=pad_num).grid(row=1, column=2, sticky="nsew", padx=4, pady=4)
        
        # Fila 2: 1 2 3
        ttk.Button(all_btns, text="1", command=lambda: press_digit("1"), 
                  bootstyle="light", padding=pad_num).grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="2", command=lambda: press_digit("2"), 
                  bootstyle="light", padding=pad_num).grid(row=2, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="3", command=lambda: press_digit("3"), 
                  bootstyle="light", padding=pad_num).grid(row=2, column=2, sticky="nsew", padx=4, pady=4)
        
        # Fila 3: . 0 DEL
        ttk.Button(all_btns, text=".", command=lambda: press_digit("."), 
                  bootstyle="secondary", padding=pad_num).grid(row=3, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="0", command=lambda: press_digit("0"), 
                  bootstyle="light", padding=pad_num).grid(row=3, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="DEL", command=press_backspace, 
                  bootstyle="warning", padding=pad_act).grid(row=3, column=2, sticky="nsew", padx=4, pady=4)
        
        # Fila 4: X | OK (OK ocupa 2 columnas)
        ttk.Button(all_btns, text="X", command=close_keypad, 
                  bootstyle="danger", padding=pad_act).grid(row=4, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="OK", command=confirm_and_close, 
                  bootstyle="success", padding=pad_act).grid(row=4, column=1, columnspan=2, sticky="nsew", padx=4, pady=4)
        
        # El teclado captura los eventos (importante para que funcione sobre diálogos con grab)
        keypad.grab_set()
        keypad.focus_set()
        keypad.lift()

    def _bind_numeric_keypad(self, entry_widget, title="Inserir Valor"):
        """Vincula un Entry para mostrar teclado numérico al hacer click."""
        def on_click(event):
            self.after(50, lambda: self._show_numeric_keypad(entry_widget, title))
            return "break"
        entry_widget.bind("<Button-1>", on_click)
        entry_widget.bind("<Return>", lambda e: "break")
        entry_widget.bind("<KP_Enter>", lambda e: "break")

    def do_tare(self):
        self.command_queue.put({'cmd': 'TARE'})

    def toggle_decimals(self):
        """Alterna entre mostrar valores con o sin decimales."""
        self._show_decimals = not self._show_decimals
        if self._show_decimals:
            # Decimales activos - botón oscuro/gris
            self.btn_decimals.configure(
                text="0.00", 
                bootstyle="dark",
                style='Header.TButton',
                width=8,
                padding=(15, 12)
            )
        else:
            # Decimales inactivos - botón azul brillante
            self.btn_decimals.configure(
                text="0.00", 
                bootstyle="primary",
                style='Header.TButton',
                width=8,
                padding=(15, 12)
            )
        # Forzar actualización visual inmediata de todos los valores
        self.after(10, self._refresh_all_displays)
    
    def _refresh_all_displays(self):
        """Actualiza todos los displays con el formato actual."""
        if hasattr(self, '_last_sensor_data') and self._last_sensor_data:
            self._update_display(self._last_sensor_data)

    def _format_weight(self, value):
        """Formatea el peso según configuración de decimales (redondeo bancario/IEEE 754)."""
        if self._show_decimals:
            # Con decimales: 2 posiciones usando redondeo bancario
            from decimal import Decimal, ROUND_HALF_EVEN
            d = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)
            return f"{d}"
        else:
            # Sin decimales: redondeo al entero más cercano (norma ISO 80000-1)
            return f"{round(value)}"

    def show_large_confirmation(self, title, message):
        """Mostra um dilogo modal personalizado SEM barra de ttulo, com fontes e botes grandes."""
        result = {'value': False, 'done': False}
        
        # Obtener la ventana padre (puede ser wizard o self)
        parent = self._cal_wizard if hasattr(self, '_cal_wizard') and self._cal_wizard else self
        
        # Liberar grab del padre si existe
        try:
            parent.grab_release()
        except:
            pass
        
        # Crear janela secundria SIN BARRA DE TTULO
        dialog = ttk.Toplevel(parent)
        dialog.overrideredirect(True)  # Quitar barra de Windows
        
        # Centralizar em relao  tela
        screen_w = dialog.winfo_screenwidth()
        screen_h = dialog.winfo_screenheight()
        x = (screen_w // 2) - 350
        y = (screen_h // 2) - 225
        dialog.geometry(f"700x450+{x}+{y}")
        
        # Forzar que aparezca arriba de todo
        dialog.attributes('-topmost', True)
            
        # Container con borde para definir el dilogo
        outer_frame = ttk.Frame(dialog, bootstyle="dark", padding=4)
        outer_frame.pack(fill=BOTH, expand=YES)
        
        frame = ttk.Frame(outer_frame, padding=40)
        frame.pack(fill=BOTH, expand=YES)
        
        # Ttulo personalizado
        title_lbl = ttk.Label(frame, text=title.upper(), font=("Segoe UI", 22, "bold"), foreground="#1e293b")
        title_lbl.pack(pady=(0, 25))
        
        # Mensagem grande
        lbl = ttk.Label(frame, text=message, font=("Segoe UI", 18), wraplength=600, justify="center")
        lbl.pack(pady=(10, 50), expand=YES)
        
        # Botes grandes
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X, pady=10)
        
        def on_yes():
            result['value'] = True
            result['done'] = True
            
        def on_no():
            result['done'] = True
            
        btn_yes = ttk.Button(btn_frame, text="SIM", bootstyle="success", width=15, 
                             command=on_yes, padding=(30, 20))
        btn_yes.pack(side=LEFT, padx=30, expand=YES, fill=X)
        
        btn_no = ttk.Button(btn_frame, text="NÃO", bootstyle="danger", width=15, 
                            command=on_no, padding=(30, 20))
        btn_no.pack(side=RIGHT, padx=30, expand=YES, fill=X)

        # Configurar cierre con protocolo
        dialog.protocol("WM_DELETE_WINDOW", on_no)
        
        dialog.transient(parent)
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()
        
        # Esperar respuesta con loop manual
        while not result['done']:
            dialog.update()
            self.update()
        
        # Limpiar
        try:
            dialog.grab_release()
            dialog.destroy()
        except:
            pass
        
        # Restaurar grab del padre
        try:
            if parent and parent.winfo_exists():
                parent.grab_set()
        except:
            pass
        
        return result['value']

    def show_alert(self, title, message, alert_type="info", parent=None):
        """Mostra um alerta SEM barra de ttulo, com estilo grande."""
        target = parent or self
        
        # Criar janela SIN BARRA DE TTULO
        dialog = ttk.Toplevel(target)
        dialog.overrideredirect(True)
        dialog.geometry("550x300")
        
        # Centralizar
        try:
            x = target.winfo_x() + (target.winfo_width() // 2) - 275
            y = target.winfo_y() + (target.winfo_height() // 2) - 150
            dialog.geometry(f"+{x}+{y}")
        except:
            pass
        
        dialog.lift()
        dialog.focus_force()
        
        # Estilo segn tipo
        if alert_type == "error":
            bootstyle = "danger"
            icon = ""
        elif alert_type == "success":
            bootstyle = "success"
            icon = ""
        else:
            bootstyle = "info"
            icon = ""
        
        # Container con borde
        outer_frame = ttk.Frame(dialog, bootstyle=bootstyle, padding=3)
        outer_frame.pack(fill=BOTH, expand=YES)
        
        frame = ttk.Frame(outer_frame, padding=25)
        frame.pack(fill=BOTH, expand=YES)
        
        # Ttulo
        title_lbl = ttk.Label(frame, text=f"{icon}  {title.upper()}", 
                              font=("Segoe UI", 16, "bold"), foreground="#1e293b")
        title_lbl.pack(pady=(0, 15))
        
        # Mensaje
        msg_lbl = ttk.Label(frame, text=message, font=("Segoe UI", 14), 
                            wraplength=440, justify="center")
        msg_lbl.pack(pady=(10, 25), expand=YES)
        
        # Funcin de cierre seguro
        def close_dialog():
            try:
                dialog.grab_release()
            except:
                pass
            try:
                dialog.destroy()
            except:
                pass
        
        # Botn OK
        btn_ok = ttk.Button(frame, text="OK", bootstyle=bootstyle, width=12,
                            command=close_dialog, padding=(20, 12))
        btn_ok.pack()
        
        # Configurar cierre con X (si se pudiera)
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        
        dialog.transient(target)
        try:
            dialog.grab_set()
        except:
            pass  # Ignorar si no se puede obtener el grab
        target.wait_window(dialog)

    def reset_tare(self):
        print("DEBUG: Botão Limpar Tara pressionado")
        self.log_message("Solicitando limpar tara...")
        # Usar after para permitir que a UI seja atualizada
        self.after(100, self._show_reset_confirmation)

    def _show_reset_confirmation(self):
        resposta = self.show_large_confirmation("Confirmação", "Tem certeza que deseja limpar a tara?")
        
        print(f"DEBUG: Resposta diálogo: {resposta}")
        
        if resposta:
            self.command_queue.put({'cmd': 'RESET_TARE'})
            self.log_message("Tara limpa com sucesso.")
        else:
            self.log_message("Operação cancelada.")

    # =========================================================================
    # DIALOGO DE DESCONEXION DE SENSOR
    # =========================================================================
    
    def _show_sensor_disconnect_dialog(self, payload):
        """
        Muestra dialogo de alerta cuando un sensor se desconecta.
        Permite reconexion manual o esperar reconexion automatica.
        """
        node_id = payload['node_id']
        nombre = payload['nombre']
        max_attempts = payload.get('max_attempts', 5)
        
        # Si ya hay un dialogo abierto para este nodo, no crear otro
        if hasattr(self, '_disconnect_dialogs') and node_id in self._disconnect_dialogs:
            return
        
        if not hasattr(self, '_disconnect_dialogs'):
            self._disconnect_dialogs = {}
        
        # Crear dialogo de alerta
        dialog = ttk.Toplevel(self)
        dialog.overrideredirect(True)
        dialog.geometry("700x480")
        
        # Centrar
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 350
            y = self.winfo_y() + (self.winfo_height() // 2) - 240
            dialog.geometry(f"+{x}+{y}")
        except:
            pass
        
        dialog.lift()
        dialog.attributes('-topmost', True)
        
        # Guardar referencia
        self._disconnect_dialogs[node_id] = {
            'dialog': dialog,
            'progress_label': None,
            'attempt_label': None
        }
        
        # Container con borde rojo
        outer_frame = ttk.Frame(dialog, bootstyle="danger", padding=4)
        outer_frame.pack(fill=BOTH, expand=YES)
        
        frame = ttk.Frame(outer_frame, padding=30)
        frame.pack(fill=BOTH, expand=YES)
        
        # Titulo
        title_lbl = ttk.Label(
            frame, 
            text="SENSOR DESCONECTADO", 
            font=("Segoe UI", 20, "bold"), 
            foreground="#dc2626"
        )
        title_lbl.pack(pady=(0, 20))
        
        # Mensaje principal
        msg_text = f"O sensor '{nombre}' (ID: {node_id}) perdeu a conexão.\n\n" \
                   f"A aquisição de dados esta pausada."
        msg_lbl = ttk.Label(
            frame, 
            text=msg_text, 
            font=("Segoe UI", 14), 
            wraplength=520, 
            justify="center"
        )
        msg_lbl.pack(pady=(10, 20))
        
        # Frame de progreso de reconexion
        progress_frame = ttk.Frame(frame)
        progress_frame.pack(fill=X, pady=10)
        
        progress_lbl = ttk.Label(
            progress_frame,
            text="Reconexão automática em progresso...",
            font=("Segoe UI", 12),
            foreground="#f59e0b"
        )
        progress_lbl.pack()
        
        attempt_lbl = ttk.Label(
            progress_frame,
            text=f"Tentativa 0 de {max_attempts}",
            font=("Segoe UI", 11),
            foreground="#64748b"
        )
        attempt_lbl.pack(pady=(5, 0))
        
        # Guardar referencias para actualizar
        self._disconnect_dialogs[node_id]['progress_label'] = progress_lbl
        self._disconnect_dialogs[node_id]['attempt_label'] = attempt_lbl
        
        # Botones
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X, pady=(25, 10))
        
        def on_manual_reconnect():
            self.command_queue.put({'cmd': 'MANUAL_RECONNECT', 'node_id': node_id})
            progress_lbl.configure(text="Reconexão manual iniciada...", foreground="#22c55e")
            attempt_lbl.configure(text="Aguardando resposta do sensor...")
        
        def on_continue_anyway():
            # Continuar sin el sensor
            self.command_queue.put({'cmd': 'RESUME_ACQUISITION'})
            self._close_disconnect_dialog(node_id)
            self.log_message(f"Continuando sin sensor {nombre} (ID: {node_id})")
        
        def on_pause():
            # Pausar y cerrar dialogo
            self.command_queue.put({'cmd': 'PAUSE_ACQUISITION'})
            self._close_disconnect_dialog(node_id)
        
        # Boton reconectar manual
        btn_reconnect = ttk.Button(
            btn_frame, 
            text=" RECONECTAR AGORA", 
            bootstyle="warning",
            command=on_manual_reconnect,
            padding=(20, 15),
            width=20
        )
        btn_reconnect.pack(side=LEFT, padx=10, expand=YES)
        
        # Boton continuar sin sensor
        btn_continue = ttk.Button(
            btn_frame, 
            text=" CONTINUAR SEM SENSOR", 
            bootstyle="secondary",
            command=on_continue_anyway,
            padding=(20, 15),
            width=22
        )
        btn_continue.pack(side=LEFT, padx=10, expand=YES)
        
        dialog.transient(self)
        # No usar grab_set para permitir que otros eventos lleguen
    
    def _update_reconnect_progress(self, payload):
        """Actualiza el progreso de reconexion en el dialogo."""
        node_id = payload['node_id']
        attempt = payload['attempt']
        max_attempts = payload['max_attempts']
        
        if hasattr(self, '_disconnect_dialogs') and node_id in self._disconnect_dialogs:
            dialog_info = self._disconnect_dialogs[node_id]
            if dialog_info['attempt_label']:
                dialog_info['attempt_label'].configure(
                    text=f"Tentativa {attempt} de {max_attempts}"
                )
    
    def _handle_sensor_reconnected(self, payload):
        """Maneja quando um sensor se reconecta com sucesso."""
        node_id = payload['node_id']
        
        # Mostrar mensaje de exito y cerrar dialogo
        self.log_message(f"Sensor {node_id} reconectado com sucesso")
        
        # Actualizar dialogo si existe
        if hasattr(self, '_disconnect_dialogs') and node_id in self._disconnect_dialogs:
            dialog_info = self._disconnect_dialogs[node_id]
            if dialog_info['progress_label']:
                dialog_info['progress_label'].configure(
                    text="RECONECTADO COM SUCESSO",
                    foreground="#22c55e"
                )
            if dialog_info['attempt_label']:
                dialog_info['attempt_label'].configure(text="")
            
            # Cerrar dialogo despues de 1.5 segundos
            self.after(1500, lambda: self._close_disconnect_dialog(node_id))
    
    def _handle_reconnect_failed(self, payload):
        """Maneja cuando falla la reconexion automatica."""
        node_id = payload['node_id']
        attempts = payload['attempts']
        
        self.log_message(f" Falha reconexão do sensor {node_id} após {attempts} tentativas")
        
        # Actualizar dialogo
        if hasattr(self, '_disconnect_dialogs') and node_id in self._disconnect_dialogs:
            dialog_info = self._disconnect_dialogs[node_id]
            if dialog_info['progress_label']:
                dialog_info['progress_label'].configure(
                    text=f" RECONEXÃO FALHOU ({attempts} tentativas)",
                    foreground="#dc2626"
                )
            if dialog_info['attempt_label']:
                dialog_info['attempt_label'].configure(
                    text="Use 'Reconectar Agora' ou continue sem o sensor"
                )
    
    def _close_disconnect_dialog(self, node_id):
        """Cierra el dialogo de desconexion para un nodo especifico."""
        if hasattr(self, '_disconnect_dialogs') and node_id in self._disconnect_dialogs:
            dialog_info = self._disconnect_dialogs.pop(node_id)
            try:
                dialog_info['dialog'].destroy()
            except:
                pass
    
    def _handle_discovered_nodes(self, nodes_list):
        """
        Maneja la respuesta de descubrimiento de nodos.
        Actualiza la UI con los nodos y canales encontrados.
        
        Args:
            nodes_list: Lista de dicts con info de cada nodo:
                [{
                    'id': 12345,
                    'rssi': -45,
                    'model': 'SG-Link-200',
                    'channels': [{'channel': 'ch1', 'type': 'strain', 'value': 0.0}, ...],
                    'sample_rate': '32 Hz'
                }, ...]
        """
        # Guardar nodos descubiertos
        self._discovered_nodes = nodes_list
        
        # Actualizar label de status
        if hasattr(self, '_discovered_nodes_var'):
            if nodes_list:
                total_channels = sum(len(n.get('channels', [])) for n in nodes_list)
                self._discovered_nodes_var.set(
                    f" Encontrados {len(nodes_list)} no(s) com {total_channels} canais"
                )
            else:
                self._discovered_nodes_var.set(" Nenhum no encontrado")
        
        # Actualizar treeview si existe
        if hasattr(self, '_disc_tree'):
            try:
                # Limpiar treeview
                for item in self._disc_tree.get_children():
                    self._disc_tree.delete(item)
                
                # Agregar nodos y canales
                for node in nodes_list:
                    node_id = node.get('id', 0)
                    serial = node.get('serial', str(node_id))
                    rssi = node.get('rssi', 0)
                    channels = node.get('channels', [])
                    
                    for ch_info in channels:
                        ch_name = ch_info.get('channel', 'ch1')
                        ch_value = ch_info.get('value', 0.0)
                        
                        self._disc_tree.insert("", "end", values=(
                            node_id,
                            serial,
                            ch_name,
                            f"{rssi} dBm",
                            f"{ch_value:.4f}",
                            " Activo"
                        ))
            except Exception as e:
                self.log_message(f"Erro atualizando lista de ns: {e}")

    def toggle_connection(self):
        if not self.connected:
            self._show_connection_dialog()
        else:
            self.command_queue.put({'cmd': 'DISCONNECT'})

    def _auto_connect_on_startup(self):
        """Inicia conexo automaticamente quando o programa abre."""
        if not self.connected:
            self._show_connection_dialog()

    def _show_connection_dialog(self):
        """Mostra dilogo de conexo - 100% no bloqueante."""
        
        # 1. Se j est ativo, apenas trazer para frente
        if getattr(self, '_connection_dialog_active', False):
            if hasattr(self, '_conn_dialog') and self._conn_dialog.winfo_exists():
                self._conn_dialog.lift()
                return
        
        # 2. Limpeza preventiva: Se existe janela "morta" ou "cancelando", destruir antes
        if hasattr(self, '_conn_dialog') and self._conn_dialog.winfo_exists():
            try:
                self._conn_dialog.destroy()
            except:
                pass

        self._connection_dialog_active = True
        self._cancel_connection = False
        
        # Criar janela
        dialog = ttk.Toplevel(self)
        dialog.overrideredirect(True)
        
        w_dlg = 700
        h_dlg = 480
        
        # Centralizar de forma robusta
        try:
            # Se a janela principal ainda não está visível ou é muito pequena, usar a tela
            if self.winfo_width() > 100:
                x = self.winfo_x() + (self.winfo_width() // 2) - (w_dlg // 2)
                y = self.winfo_y() + (self.winfo_height() // 2) - (h_dlg // 2)
            else:
                # Fallback para o centro da tela
                x = (self.winfo_screenwidth() // 2) - (w_dlg // 2)
                y = (self.winfo_screenheight() // 2) - (h_dlg // 2)
        except:
            x = 100
            y = 100
            
        dialog.geometry(f"{w_dlg}x{h_dlg}+{x}+{y}")
        dialog.lift()
        dialog.attributes("-topmost", True)
        
        # Container
        outer_frame = ttk.Frame(dialog, bootstyle="secondary", padding=3)
        outer_frame.pack(fill=BOTH, expand=YES)
        
        frame = ttk.Frame(outer_frame, padding=25)
        frame.pack(fill=BOTH, expand=YES)
        
        # Ttulo
        ttk.Label(frame, text="CONECTANDO", font=("Segoe UI", 20, "bold"), 
                  foreground="#1e293b").pack(pady=(5, 10))
        
        # cone
        ttk.Label(frame, text="", font=("Segoe UI", 44)).pack(pady=8)
        
        # Status
        self._conn_status = ttk.Label(frame, text="Procurando sensor...", 
                                       font=("Segoe UI", 16), wraplength=520)
        self._conn_status.pack(pady=(8, 5))
        
        # Info
        self._conn_info = ttk.Label(frame, text="Aguarde...", 
                                     font=("Segoe UI", 12), foreground="#64748b")
        self._conn_info.pack(pady=(0, 8))
        
        # Barra de progresso
        self._conn_progress = ttk.Progressbar(frame, mode='indeterminate', 
                                               bootstyle="info-striped", length=450)
        self._conn_progress.pack(pady=8, fill=X, padx=30)
        self._conn_progress.start(8)
        
        # Botones
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X, pady=(15, 5))
        
        self._conn_dialog = dialog
        self._conn_btn = ttk.Button(btn_frame, text="CANCELAR", bootstyle="danger",
                                     command=self._cancel_connection_dialog, padding=(30, 15))
        self._conn_btn.pack(expand=YES, ipadx=20, ipady=5)
        
        # NOTA: Remover transient cuando se usa overrideredirect en ambas ventanas para evitar conflictos
        # dialog.transient(self) 
        dialog.update_idletasks()  # Forzar renderizado inmediato
        dialog.after(20, lambda: dialog.grab_set())
        
        # Enviar comando y empezar a monitorear
        self.command_queue.put({'cmd': 'CONNECT'})
        self._conn_start_time = time.time()
        self._conn_attempt = 1
        dialog.after(100, self._check_connection_status)
    
    def _check_connection_status(self):
        """Verifica estado - llamado via after(), nunca bloquea."""
        if not self._connection_dialog_active:
            return
        
        try:
            if not self._conn_dialog.winfo_exists():
                return
        except:
            return
        
        # xito
        if self.connected:
            self._conn_progress.stop()
            self._conn_status.configure(text="Conectado!", foreground="#22c55e")
            self._conn_info.configure(text="")
            self._conn_btn.configure(state='disabled')
            self._connection_dialog_active = False
            self._conn_dialog.after(800, self._safe_close_conn_dialog)
            return
        
        # Cancelado
        if self._cancel_connection:
            return
        
        # Calcular tiempo
        elapsed = time.time() - self._conn_start_time
        
        # Actualizar info cada 100ms
        self._conn_info.configure(text=f"Tentativa {self._conn_attempt}  {int(elapsed)}s")
        
        # Timeout por intento (6 segundos)
        if elapsed > 6 * self._conn_attempt:
            if self._conn_attempt < 3:
                self._conn_attempt += 1
                self._conn_status.configure(text=f"Tentativa {self._conn_attempt}...")
                self.command_queue.put({'cmd': 'CONNECT'})
            else:
                # Fall despus de 3 intentos
                self._conn_progress.stop()
                self._conn_status.configure(
                    text=" Sensor não encontrado", foreground="#ef4444")
                self._conn_info.configure(text="Verifique a conexão e tente novamente")
                self._conn_btn.configure(text="FECHAR", bootstyle="secondary",
                                          command=self._safe_close_conn_dialog)
                self._connection_dialog_active = False
                return
        
        # Continuar verificando (nunca bloquea)
        self._conn_dialog.after(100, self._check_connection_status)
    
    def _cancel_connection_dialog(self):
        """Cancela conexin inmediatamente."""
        self._cancel_connection = True
        self._connection_dialog_active = False
        
        # Parar elementos visuais
        if hasattr(self, '_conn_progress') and self._conn_progress.winfo_exists():
            self._conn_progress.stop()
        if hasattr(self, '_conn_status') and self._conn_status.winfo_exists():
            self._conn_status.configure(text="Cancelado")
            
        # IMPORTANTE: Liberar grab imediatamente para evitar congelamento
        if hasattr(self, '_conn_dialog') and self._conn_dialog.winfo_exists():
            try:
                self._conn_dialog.grab_release()
            except:
                pass
        
        # Agendar fechamento passando a referncia da janela atual
        # para evitar fechar uma nova janela se for aberta rapidamente
        current_dialog = self._conn_dialog
        self.after(300, lambda: self._destroy_specific_dialog(current_dialog))
        
    def _destroy_specific_dialog(self, dialog):
        """Destri uma janela de dilogo especfica."""
        try:
            if dialog and dialog.winfo_exists():
                dialog.destroy()
        except:
            pass
            
    def _safe_close_conn_dialog(self):
        """Cierra dilogo de forma segura (wrapper legado)."""
        if hasattr(self, '_conn_dialog'):
            self._destroy_specific_dialog(self._conn_dialog)
        
    def _update_connection_progress(self, data):
        """Atualiza o dilogo de conexo com o progresso."""
        if not hasattr(self, '_conn_dialog') or not getattr(self, '_connection_dialog_active', False):
            return
            
        try:
            attempt = data.get('attempt', 1)
            max_attempts = data.get('max_attempts', 3)
            status = data.get('status', 'connecting')
            message = data.get('message', 'Conectando...')
            
            # Atualizar textos se os widgets existirem
            if hasattr(self, '_conn_info') and self._conn_info.winfo_exists():
                self._conn_info.configure(text=f"Tentativa {attempt} de {max_attempts}")
            
            if hasattr(self, '_conn_status') and self._conn_status.winfo_exists():
                self._conn_status.configure(text=message)
            
            if status == 'success':
                if hasattr(self, '_conn_progress') and self._conn_progress.winfo_exists():
                    self._conn_progress.stop()
                
                if hasattr(self, '_conn_status') and self._conn_status.winfo_exists():
                    self._conn_status.configure(
                        text=" Conexão estabelecida com sucesso!",
                        foreground="#22c55e"
                    )
                
                if hasattr(self, '_conn_btn') and self._conn_btn.winfo_exists():
                    self._conn_btn.configure(state='disabled')
                
                self._connection_dialog_active = False
                if self._conn_dialog.winfo_exists():
                    self._conn_dialog.after(1000, self._conn_dialog.destroy)
                
            elif status == 'failed':
                if hasattr(self, '_conn_progress') and self._conn_progress.winfo_exists():
                    self._conn_progress.stop()
                
                if hasattr(self, '_conn_status') and self._conn_status.winfo_exists():
                    self._conn_status.configure(
                        text=" " + message,
                        foreground="#ef4444"
                    )
                
                if hasattr(self, '_conn_btn') and self._conn_btn.winfo_exists():
                    self._conn_btn.configure(text="FECHAR", state='normal')
                
                self._connection_dialog_active = False
                
            elif status == 'cancelled':
                if hasattr(self, '_conn_progress') and self._conn_progress.winfo_exists():
                    self._conn_progress.stop()
                
                self._connection_dialog_active = False
                try:
                    if self._conn_dialog.winfo_exists():
                        self._conn_dialog.destroy()
                except:
                    pass
                    
        except Exception as e:
            print(f"[GUI] Erro atualizando progresso de conexo: {e}")
    
    def _close_connection_dialog(self):
        """Fecha o dilogo de conexo se estiver aberto."""
        self._connection_dialog_active = False
        if hasattr(self, '_conn_dialog'):
            try:
                if self._conn_dialog.winfo_exists():
                    self._conn_dialog.destroy()
            except:
                pass

    def quit_app(self):
        if self.show_large_confirmation("Sair", "Deseja sair do sistema?"):
            self.command_queue.put({'cmd': 'EXIT'})
            self.destroy()

    def show_configuration_dialog(self):
        """Abre um dilogo para configurar sensores e calibrao."""
        import json
        import os
        
        # Carregar configurao atual ou usar defaults
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "settings.json")
        current_config = {
            "execution_mode": "REAL",
            "connection_type": "SERIAL",
            "serial_port": "COM3",
            "nodes": NODOS_CONFIG
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    saved_config = json.load(f)
                    current_config.update(saved_config)
            except:
                pass

        # Criar janela modal - SEM BARRA DE TTULO
        dialog = ttk.Toplevel(self)
        dialog.overrideredirect(True)
        
        # Tamanho quase tela cheia para tablet
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        dialog_w = screen_w - 40
        dialog_h = screen_h - 40
        x = 20
        y = 20
        dialog.geometry(f"{dialog_w}x{dialog_h}+{x}+{y}")
        
        dialog.lift()
        dialog.focus_force()

        # Estilos para abas grandes (touch-friendly) y CENTRADAS (simulado com padding o fill)
        # Nota: El estilo 'TNotebook.Tab' ya fue ajustado en _configure_styles,
        # pero aqui podemos forzar aun mas
        style = ttk.Style()
        style.configure('BigTab.TNotebook.Tab', 
                       font=('Segoe UI', 16, 'bold'), 
                       padding=(60, 12),
                       width=25,
                       background="#e2e8f0",
                       foreground="#475569")
        
        style.map('BigTab.TNotebook.Tab',
                 background=[('selected', '#2563eb')],
                 foreground=[('selected', 'white')])
        
        # Funo de fechamento seguro
        def safe_close_dialog():
            try:
                dialog.grab_release()
            except:
                pass
            try:
                dialog.destroy()
            except:
                pass

        # === BORDA para delimitar a janela ===
        border_frame = ttk.Frame(dialog, bootstyle="dark", padding=4)
        border_frame.pack(fill=BOTH, expand=YES)
        
        main_frame = ttk.Frame(border_frame, padding=10)
        main_frame.pack(fill=BOTH, expand=YES)
        
        # Variable para almacenar referencia a save_config (se define después)
        save_config_ref = [None]
        
        def do_save():
            if save_config_ref[0]:
                save_config_ref[0]()
        
        # Header: Solo Tabs (ocupa todo el ancho)
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=X, pady=(0, 5))
        
        # Notebook/Tabs
        notebook = ttk.Notebook(header_frame, style='BigTab.TNotebook')
        notebook.pack(fill=X)

        # ==================== Tab Sensores ====================
        tab_nodes = ttk.Frame(notebook, padding=10)
        notebook.add(tab_nodes, text="  SENSORES  ")
        
        
        # === Porta Serial (USB Gateway) - Compacto ===
        port_frame = ttk.Labelframe(tab_nodes, text="Porta Serial (Gateway USB)", padding=10)
        port_frame.pack(fill=X, pady=(0, 10))
        
        # Layout con grid para mejor alineacion
        port_grid = ttk.Frame(port_frame)
        port_grid.pack(fill=X)
        port_grid.columnconfigure(1, weight=1)
        
        ttk.Label(port_grid, text="Porta COM:", font=("Segoe UI", 14)).grid(row=0, column=0, sticky="w", padx=(0, 15))
        
        # PROCURAR PORTAS DISPONIVEIS AUTOMATICAMENTE
        com_values = []
        try:
            import serial.tools.list_ports
            com_list = serial.tools.list_ports.comports()
            com_values = [p.device for p in com_list]
        except:
            com_values = []
            
        current_port = current_config.get("serial_port", "COM3")
        
        # Si la lista esta vacia, agregar al menos el default
        if not com_values:
            com_values.append(current_port)
        elif current_port not in com_values:
            com_values.append(current_port)
            
        # Ordenar portas
        try:
            com_values.sort(key=lambda x: int(x.replace('COM', '')) if x.startswith('COM') and x[3:].isdigit() else x)
        except:
            pass # No ordenar si falla
            
        # Combobox editable para seleccionar o escribir
        entry_serial = ttk.Combobox(port_grid, font=("Segoe UI", 14), width=12, values=com_values)
        entry_serial.set(current_port)
        entry_serial.grid(row=0, column=1, sticky="w", ipady=6)
        
        # Boton Actualizar Portas - sin feedback visual acumulativo
        def refresh_ports():
            try:
                import serial.tools.list_ports
                ports = serial.tools.list_ports.comports()
                new_values = [p.device for p in ports]
                # Ordenar
                if new_values:
                    new_values.sort(key=lambda x: int(x.replace('COM', '')) if x.startswith('COM') and x[3:].isdigit() else x)
                    entry_serial['values'] = new_values
                    entry_serial.set(new_values[0])
                
            except ImportError:
                self.show_alert("Aviso", "Instale 'pyserial' para deteccao automatica.", parent=dialog)
            except Exception as e:
                self.show_alert("Erro", str(e), "error", parent=dialog)
                
        ttk.Button(port_grid, text="Atualizar", command=refresh_ports, bootstyle="secondary-outline", width=10).grid(row=0, column=2, padx=(15, 0))
        
        node_entries = {}
        
        # === CONTENEDOR PRINCIPAL: Dos columnas lado a lado (ocupa todo el espacio) ===
        main_content = ttk.Frame(tab_nodes)
        main_content.pack(fill=BOTH, expand=True, pady=(5, 0))
        main_content.columnconfigure(0, weight=1, uniform="cols")
        main_content.columnconfigure(1, weight=1, uniform="cols")
        main_content.rowconfigure(0, weight=1)
        
        # === COLUMNA IZQUIERDA: Búsqueda de Nodos ===
        discover_frame = ttk.Labelframe(main_content, text="Descoberta de Nós", padding=15)
        discover_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        
        discover_btn_frame = ttk.Frame(discover_frame)
        discover_btn_frame.pack(fill=X, pady=(0, 10))
        
        # Variable para almacenar nodos descubiertos
        self._discovered_nodes = []
        self._discovered_nodes_var = tk.StringVar(value="Pressione 'Buscar' para descobrir nós")
        
        def discover_nodes_action():
            """Inicia descubrimiento de nodos."""
            self._discovered_nodes_var.set(" Procurando nós na rede...")
            self.command_queue.put({'cmd': 'DISCOVER_NODES'})
            self.log_message("Iniciando descoberta de nós SG-Link...")
        
        ttk.Button(
            discover_btn_frame, 
            text=" BUSCAR NÓS", 
            command=discover_nodes_action,
            bootstyle="info",
            padding=(20, 12)
        ).pack(side=LEFT)
        
        # Label de status
        ttk.Label(
            discover_frame, 
            textvariable=self._discovered_nodes_var, 
            font=("Segoe UI", 11), 
            foreground="#64748b",
            wraplength=350
        ).pack(anchor="w", pady=(10, 5))
        
        # Treeview para mostrar nodos descubiertos
        disc_columns = ("node_id", "serial", "channel", "rssi", "status")
        self._disc_tree = ttk.Treeview(discover_frame, columns=disc_columns, 
                                        show="headings", height=10)
        
        self._disc_tree.heading("node_id", text="ID do Nó")
        self._disc_tree.heading("serial", text="Nº Série")
        self._disc_tree.heading("channel", text="Canal")
        self._disc_tree.heading("rssi", text="RSSI")
        self._disc_tree.heading("status", text="Estado")
        
        self._disc_tree.column("node_id", width=90, anchor="center")
        self._disc_tree.column("serial", width=110, anchor="center")
        self._disc_tree.column("channel", width=70, anchor="center")
        self._disc_tree.column("rssi", width=70, anchor="center")
        self._disc_tree.column("status", width=90, anchor="center")
        
        self._disc_tree.pack(fill=BOTH, expand=True, pady=(10, 0))
        
        # === COLUMNA DERECHA: Asignación de Células ===
        assign_frame = ttk.Labelframe(main_content, text="Atribuição de Células", padding=15)
        assign_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        
        # Matriz 2x2 con tamaño fijo para evitar resize al abrir keypad
        matrix_frame = ttk.Frame(assign_frame)
        matrix_frame.pack(fill=BOTH, expand=True)
        matrix_frame.columnconfigure(0, weight=1, uniform="cells")
        matrix_frame.columnconfigure(1, weight=1, uniform="cells")
        matrix_frame.rowconfigure(0, weight=1, uniform="cells")
        matrix_frame.rowconfigure(1, weight=1, uniform="cells")
        
        # Posiciones de la matriz (esquinas de la balanza)
        # [1] [2]   <- Frente
        # [3] [4]   <- Atrás
        positions = [
            (0, 0, 1, "FRENTE ESQ"),   # Celda 1: arriba-izquierda
            (0, 1, 2, "FRENTE DIR"),   # Celda 2: arriba-derecha
            (1, 0, 3, "ATRÁS ESQ"),    # Celda 3: abajo-izquierda
            (1, 1, 4, "ATRÁS DIR"),    # Celda 4: abajo-derecha
        ]
        
        for row, col, celda_num, pos_name in positions:
            key = f"celda_{celda_num}"
            current_node_data = current_config["nodes"].get(key, {"id": 0, "ch": "ch1", "nombre": f"Celda {celda_num}", "serial": ""})
            
            # Frame de cada celda con borde más visible
            cell_frame = ttk.Labelframe(matrix_frame, text=f"CÉL {celda_num} - {pos_name}", padding=15)
            cell_frame.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
            # Evitar que el frame propague cambios de tamaño
            cell_frame.grid_propagate(False)
            cell_frame.pack_propagate(False)
            
            # Layout interno centrado
            cell_grid = ttk.Frame(cell_frame)
            cell_grid.pack(fill=BOTH, expand=True)
            
            field_width = 12
            
            # Node ID
            id_frame = ttk.Frame(cell_grid)
            id_frame.pack(fill=X, pady=4)
            ttk.Label(id_frame, text="ID:", font=("Segoe UI", 12), width=6).pack(side=LEFT)
            e_id = ttk.Entry(id_frame, font=("Segoe UI", 13), width=field_width)
            e_id.insert(0, str(current_node_data.get("id", 0)))
            e_id.pack(side=LEFT, ipady=4)
            self._bind_numeric_keypad(e_id, f"ID do Nó - Célula {celda_num}")
            
            # Número de Serie
            serial_frame = ttk.Frame(cell_grid)
            serial_frame.pack(fill=X, pady=4)
            ttk.Label(serial_frame, text="Série:", font=("Segoe UI", 12), width=6).pack(side=LEFT)
            e_serial = ttk.Entry(serial_frame, font=("Segoe UI", 13), width=field_width)
            e_serial.insert(0, str(current_node_data.get("serial", "")))
            e_serial.pack(side=LEFT, ipady=4)
            self._bind_numeric_keypad(e_serial, f"Nº Série - Célula {celda_num}")
            
            # Channel - RadioButtons
            ch_frame = ttk.Frame(cell_grid)
            ch_frame.pack(fill=X, pady=4)
            ttk.Label(ch_frame, text="Canal:", font=("Segoe UI", 12), width=6).pack(side=LEFT)
            
            ch_var = tk.StringVar(value=current_node_data.get("ch", "ch1"))
            ch_btn_frame = ttk.Frame(ch_frame)
            ch_btn_frame.pack(side=LEFT)
            
            for ch_opt in ["ch1", "ch2", "ch3"]:
                ch_btn = ttk.Radiobutton(
                    ch_btn_frame, 
                    text=ch_opt[-1],
                    variable=ch_var,
                    value=ch_opt,
                    bootstyle="info-toolbutton",
                    width=3,
                    padding=(8, 5)
                )
                ch_btn.pack(side=LEFT, padx=2)
            
            node_entries[key] = {"id": e_id, "ch": ch_var, "serial": e_serial}
        
        # ==================== Tab CALIBRACAO ====================
        tab_cal = ttk.Frame(notebook, padding=15)
        notebook.add(tab_cal, text="  CALIBRAÇÃO  ")
        
        self._setup_calibration_tab(tab_cal, current_config, safe_close_dialog, dialog)

        # Definir la función save_config y asignarla a la referencia del header
        def save_config():
            new_config = {
                "execution_mode": "REAL",
                "connection_type": "SERIAL",
                "serial_port": entry_serial.get(),
                "tcp_ip": "",
                "tcp_port": "",
                "nodes": {}
            }
            
            for key, inputs in node_entries.items():
                try:
                    nid = int(inputs["id"].get())
                except:
                    nid = 0
                serial_num = inputs.get("serial", None)
                serial_val = serial_num.get() if serial_num else ""
                new_config["nodes"][key] = {
                    "id": nid,
                    "ch": inputs["ch"].get(),
                    "serial": serial_val
                }
            
            try:
                with open(config_path, 'w') as f:
                    json.dump(new_config, f, indent=4)
                
                # Aplicar cambios en caliente al driver si existe
                if hasattr(self, 'driver') and self.driver:
                    try:
                        self.driver.update_nodes_config(new_config["nodes"])
                    except Exception as e:
                        print(f"[GUI] Aviso: No se pudo actualizar driver: {e}")
                
                self.show_alert("Salvo", "Configuração salva e aplicada.", "success", parent=dialog)
            except Exception as e:
                try:
                    dialog.grab_release()
                except:
                    pass
                self.show_alert("Erro", f"Não foi possível salvar: {e}", "error", parent=self)
        
        # Asignar la función a la referencia del header
        save_config_ref[0] = save_config

        # ==================== BOTONES ABAJO ====================
        btn_bottom_frame = ttk.Frame(main_frame, padding=(0, 10))
        btn_bottom_frame.pack(fill=X, side=BOTTOM)
        
        ttk.Separator(btn_bottom_frame, orient="horizontal").pack(fill=X, pady=(0, 10))
        
        btn_container = ttk.Frame(btn_bottom_frame)
        btn_container.pack()
        
        btn_salvar = ttk.Button(btn_container, text="SALVAR", 
                               bootstyle="success", 
                               command=do_save,
                               width=12,
                               padding=(20, 12))
        btn_salvar.pack(side=LEFT, padx=10)
        
        btn_cancelar = ttk.Button(btn_container, text="CANCELAR", 
                               bootstyle="secondary", 
                               command=safe_close_dialog,
                               width=12,
                               padding=(20, 12))
        btn_cancelar.pack(side=LEFT, padx=10)
        
        # Separador visual
        ttk.Frame(btn_container, width=30).pack(side=LEFT)
        
        btn_fechar = ttk.Button(btn_container, text="FECHAR", 
                               bootstyle="danger-outline", 
                               command=safe_close_dialog,
                               width=12,
                               padding=(20, 12))
        btn_fechar.pack(side=LEFT, padx=10)

        # Configurar protocolo de cierre
        dialog.protocol("WM_DELETE_WINDOW", safe_close_dialog)
        
        # Modal behavior
        dialog.transient(self)
        try:
            dialog.grab_set()
        except:
            pass
        self.wait_window(dialog)

    def _setup_calibration_tab(self, parent, current_config, close_config_dialog=None, config_dialog=None):
        """Configura a aba de calibração de sensores (Layout Tablet Grande)."""
        from modules.calibration import CalibrationManager
        
        # Descricao breve
        ttk.Label(parent, 
                  text="Selecione o sensor para iniciar o ensaio de calibração.",
                  font=("Segoe UI", 12), foreground="#64748b",
                  wraplength=800).pack(anchor="w", pady=(0, 15))
        
        # === SELECCION DE SENSOR (GRIGO DE BOTONES GRANDES) ===
        # Reemplazamos el combobox viejo por algo mas tactil
        
        # Remover texto del borde (frame) ya que es redundante con el texto de arriba
        select_frame = ttk.Labelframe(parent, text="", padding=20)
        select_frame.pack(fill=X, pady=(0, 25))
        
        # Container interior con borde para diferenciar visualmente la zona
        inner_container = ttk.Frame(select_frame, style='CardNoBorder.TFrame') 
        inner_container.pack(fill=X)
        
        sensor_names = list(current_config.get("nodes", {}).keys())
        if not sensor_names:
            ttk.Label(inner_container, text="Nenhum sensor configurado na aba SENSORES.", 
                     font=("Segoe UI", 16, "italic"), foreground="#94a3b8").pack(pady=20)
            # Mostrar mensaje y deshabilitar botones
            self._cal_sensor_selected = tk.StringVar(value="")
        else:
            # Variable para controlar la seleccion. Inicializada con el primer sensor.
            self._cal_sensor_selected = tk.StringVar(value=sensor_names[0])
            
            # Grid layout para botones de sensores (Max 2 por fila para ser enormes)
            row = 0
            col = 0
            MAX_COLS = 2
            
            for name in sensor_names:
                # Creamos un frame que actua como boton grande
                def select_sensor(s_name=name):
                    self._cal_sensor_selected.set(s_name)
                    # Actualizar visualmente
                    self._update_sensor_buttons_visuals(inner_container)

                # Frame principal del boton
                btn_frame = ttk.Frame(inner_container, style='Card.TFrame', cursor="hand2")
                
                # GRID con GAP GRANDE (20px) para que se note la separacion
                btn_frame.grid(row=row, column=col, sticky="nsew", padx=15, pady=15)
                
                btn_frame.grid_propagate(False)
                btn_frame.configure(height=140) # Altura aumentada
                
                # Binding para click
                btn_frame.bind("<Button-1>", lambda e, n=name: select_sensor(n))
                
                # Contenido interno
                content_frame = ttk.Frame(btn_frame, style='CardNoBorder.TFrame')
                content_frame.pack(expand=YES, fill=BOTH, padx=5, pady=5)
                content_frame.bind("<Button-1>", lambda e, n=name: select_sensor(n))
                
                # 1. Nombre del Sensor
                lbl_name = ttk.Label(content_frame, text=name, font=("Segoe UI", 26, "bold"))
                lbl_name.pack(expand=YES, side=TOP, pady=(20, 5))
                lbl_name.bind("<Button-1>", lambda e, n=name: select_sensor(n))
                
                # 2. Indicador Estado (Texto o Icono)
                lbl_status = ttk.Label(content_frame, text="Clicar para selecionar", font=("Segoe UI", 12))
                lbl_status.pack(side=BOTTOM, pady=(0, 20))
                lbl_status.bind("<Button-1>", lambda e, n=name: select_sensor(n))
                
                # Guardar referencia para actualizar estilo
                btn_frame.sensor_name = name
                
                # Tags para encontrar hijos facilmente en update
                lbl_name.tag = "name"
                lbl_status.tag = "status"
                
                inner_container.columnconfigure(col, weight=1)
                
                col += 1
                if col >= MAX_COLS:
                    col = 0
                    row += 1

            # Metodo para resaltar seleccionado
            self._update_sensor_buttons_visuals(inner_container)

            # === BOTONES DE ACCION (ENORMES) ===
            action_frame = ttk.Frame(parent)
            action_frame.pack(fill=X, pady=20)
            
            # Funcion para abrir wizard SIN cerrar el dialogo de configuracion
            def start_calibration_action():
                sensor_name = self._cal_sensor_selected.get()
                # Liberar grab del diálogo de config para que wizard funcione
                if config_dialog:
                    try:
                        config_dialog.grab_release()
                    except:
                        pass
                # Abrir wizard
                self._open_calibration_wizard(current_config, sensor_name, config_dialog)
            
            # Botao INICIAR - Texto en bold explicitamente si el estilo no lo toma
            # Se ha configurado style='Large.warning.TButton' en _configure_styles con font bold
            btn_start = ttk.Button(
                action_frame, 
                text=" INICIAR CALIBRAÇÃO ",
                bootstyle="warning", 
                command=start_calibration_action
            )
            btn_start.configure(style='Large.warning.TButton') 
            btn_start.pack(side=LEFT, fill=X, expand=YES, padx=(0, 10), ipady=15)
            
            # Botão CARREGAR
            btn_load = ttk.Button(
                action_frame, 
                text=" HISTÓRICO / CARREGAR ",
                bootstyle="info", 
                command=lambda: self._load_calibration_session(parent)
            )
            # Aplicamos estilo grande tambien aqui
            btn_load.configure(style='Large.info.TButton')
            btn_load.pack(side=LEFT, fill=X, expand=YES, padx=(10, 0), ipady=15)
        
        # === TEXTO DE AYUDA LIMPIO (Removido a pedido) ===
        # help_text = (...)
        # info_frame = ttk.Frame(parent, padding=15)
        # info_frame.pack(fill=X, pady=10)
        # ttk.Label(info_frame, text=help_text, ...).pack(anchor="center")

    def _update_sensor_buttons_visuals(self, container):
        """Helper para actualizar color de botones de selección com feedback visual claro."""
        selected = self._cal_sensor_selected.get()
        
        # Colores definidos hardcoded para garantizar contraste sin depender del tema
        COLOR_SELECTED_BG = "#2563eb" # Primary Blue
        COLOR_SELECTED_FG = "#ffffff" # White
        
        COLOR_NORMAL_BG = "#ffffff"   # White
        COLOR_NORMAL_FG = "#1e293b"   # Dark Slate
        COLOR_NORMAL_SUB = "#94a3b8"  # Gray
        
        for widget in container.winfo_children(): # widget = btn_frame
            s_name = getattr(widget, 'sensor_name', None)
            if not s_name:
                continue
                
            # Buscar elementos internos
            content_frame = None
            lbl_name = None
            lbl_status = None
            
            # Navegar hierarquia conhecida: btn_frame -> content_frame -> labels
            for child in widget.winfo_children():
                if isinstance(child, ttk.Frame):
                    content_frame = child
                    for sub in child.winfo_children():
                        if isinstance(sub, ttk.Label):
                            tag = getattr(sub, 'tag', None) # Si agregamos tag antes
                            # Fallback por orden o texto si no hay tag
                            if hasattr(sub, 'tag') and sub.tag == "name":
                                lbl_name = sub
                            elif hasattr(sub, 'tag') and sub.tag == "status":
                                lbl_status = sub
                            # Fallback simple
                            elif not lbl_name and sub.cget("text") == s_name:
                                lbl_name = sub
                            elif not lbl_status:
                                lbl_status = sub
                    break
            
            # APLICAR ESTILOS
            if s_name == selected:
                # == SELECCIONADO ==
                # Marco
                try: widget.configure(bootstyle="primary") 
                except: pass
                
                # Fondo interno (Simulado con labels pq Frame bg es dificil en ttk)
                # El truco es usar un Labelframe o style custom, pero aqui iteramos
                
                if lbl_name:
                    lbl_name.configure(background=COLOR_SELECTED_BG, foreground=COLOR_SELECTED_FG)
                
                if lbl_status:
                    lbl_status.configure(
                        text="SELECIONADO", 
                        background=COLOR_SELECTED_BG, 
                        foreground=COLOR_SELECTED_FG,
                        font=("Segoe UI", 12, "bold")
                    )
                
                # Hack para el background del frame contenedor
                # Si content_frame es un TFrame, el background depende del style.
                # Configuramos un style dinamico o usamos bootstyle="primary" inverse
                if content_frame:
                    try: content_frame.configure(bootstyle="primary")
                    except: pass

            else:
                # == NORMAL / NO SELECCIONADO ==
                # Marco
                try: widget.configure(bootstyle="secondary") 
                except: pass
                
                if lbl_name:
                    lbl_name.configure(background=COLOR_NORMAL_BG, foreground=COLOR_NORMAL_FG)
                
                if lbl_status:
                    lbl_status.configure(
                        text="Clicar para selecionar", 
                        background=COLOR_NORMAL_BG, 
                        foreground=COLOR_NORMAL_SUB,
                        font=("Segoe UI", 12)
                    )
                    
                if content_frame:
                    try: content_frame.configure(bootstyle="default")
                    except: pass
    
    def _open_calibration_wizard(self, current_config, sensor_name_override=None, config_dialog=None):
        """
        Wizard de Calibração Avançado.
        Permite entrada manual ou captura, múltiplos pontos, e seleção de curva.
        """
        # validar data processor
        if not self.data_processor:
            self.show_alert("Erro", "DataProcessor não disponível", "error")
            return

        # Guardar referencia al diálogo de config para restaurar grab
        self._config_dialog_ref = config_dialog

        # Setup manager
        from modules.calibration import CalibrationManager
        self._cal_manager = CalibrationManager(self.data_processor)
        self._cal_manager.clear_points()

        # Variables UI
        self._cal_method_var = tk.StringVar(value="Linear (y=mx+b)")
        self._cal_unit_var = tk.StringVar(value="Bits (Raw)")
        self._cal_input_weight = tk.StringVar(value="")
        self._cal_input_reading = tk.StringVar(value="")
        self._cal_wizard_active = True

        # Crear Ventana - Pantalla completa con estado fullscreen
        wizard = ttk.Toplevel(self)
        wizard.title("Assistente de Calibração")
        w, h = self.winfo_screenwidth(), self.winfo_screenheight()
        wizard.geometry(f"{w}x{h}+0+0")
        wizard.attributes('-fullscreen', True)  # Fullscreen nativo de Windows
        wizard.grab_set()  # Capturar eventos para el wizard
        wizard.lift()
        wizard.focus_force()
        self._cal_wizard = wizard

        # === HELPERS ===
        def close_wizard():
            self._cal_wizard_active = False
            try:
                self._cal_manager.cancel()
            except:
                pass
            try:
                wizard.grab_release()
            except:
                pass
            try:
                wizard.destroy()
            except:
                pass
            # Restaurar grab del diálogo de configuración
            if self._config_dialog_ref:
                try:
                    self._config_dialog_ref.grab_set()
                    self._config_dialog_ref.lift()
                    self._config_dialog_ref.focus_force()
                except:
                    pass
            self._cal_wizard = None
        
        wizard.protocol("WM_DELETE_WINDOW", close_wizard)
        
        def check_connection():
            return self.connected
        
        def get_reading_by_unit():
            """Obtiene la lectura según la unidad seleccionada."""
            unit = self._cal_unit_var.get()
            
            if unit == "Bits (Raw)":
                # Valor raw sin procesar
                return self.data_processor.get_last_total_raw()
            elif unit == "t":
                # Peso calibrado en toneladas (usa calibración actual)
                # Si hay calibración, devuelve el peso; si no, devuelve raw
                try:
                    # Obtener el último peso procesado
                    result = getattr(self, '_last_process_result', None)
                    if result and 'total' in result:
                        return result['total']
                except:
                    pass
                return self.data_processor.get_last_total_raw()
            elif unit == "kg":
                # Peso en kg (toneladas * 1000)
                try:
                    result = getattr(self, '_last_process_result', None)
                    if result and 'total' in result:
                        return result['total'] * 1000
                except:
                    pass
                return self.data_processor.get_last_total_raw()
            elif unit == "mV/V":
                # Conversión aproximada de bits a mV/V
                # Asumiendo ADC de 24 bits y rango típico
                raw = self.data_processor.get_last_total_raw()
                # Conversión aproximada (ajustar según especificaciones del sensor)
                mv_per_v = (raw / 16777216) * 2.5  # Ejemplo: 24-bit ADC, 2.5mV/V full scale
                return mv_per_v
            else:
                return self.data_processor.get_last_total_raw()
            
        def cmd_capture():
            if not check_connection():
                self.show_alert("Aviso", "Sistema não conectado.\nConecte o hardware para capturar.", "warning", parent=wizard)
                return
            
            val = get_reading_by_unit()
            unit = self._cal_unit_var.get()
            
            if unit == "mV/V":
                self._cal_input_reading.set(f"{val:.4f}")
            elif unit in ["t", "kg"]:
                self._cal_input_reading.set(f"{val:.2f}")
            else:
                self._cal_input_reading.set(f"{val:.0f}")
            
        def cmd_add_point():
            try:
                w_str = self._cal_input_weight.get()
                r_str = self._cal_input_reading.get()
                if not w_str or not r_str: 
                    self.show_alert("Aviso", "Complete ambos os campos", "warning", parent=wizard)
                    return
                
                weight = float(w_str)
                reading = float(r_str)
                
                self._cal_manager.add_point(weight, reading)
                self._refresh_cal_wizard_table_ui()
                self._update_cal_wizard_graph()
                
                self._cal_input_weight.set("")
                self._cal_input_reading.set("")
            except ValueError:
                self.show_alert("Erro", "Valores numéricos inválidos", "error", parent=wizard)
                
        def cmd_apply_cal():
            # Método fijo: Interpolación por Segmentos
            points = self._cal_manager.get_points()
            
            if len(points) < 2:
                self.show_alert("Erro", "São necessários pelo menos 2 pontos para calibrar.", "error", parent=wizard)
                return
            
            # Crear modelo de interpolación por segmentos
            sorted_points = sorted(points, key=lambda p: p[1])  # Ordenar por lectura
            
            # Guardar puntos de calibración para interpolación
            cal_data = {
                "method": "segments",
                "points": [(p[0], p[1]) for p in sorted_points],  # (peso, lectura)
                "valid": True
            }
            self._cal_manager.apply_calibration(cal_data)
            self.show_alert("Sucesso", f"Calibração salva com {len(sorted_points)} pontos.", "success", parent=wizard)
            close_wizard()

        # === UI LAYOUT ===
        
        # HEADER - Mejorado visualmente
        header = ttk.Frame(wizard, bootstyle="primary")
        header.pack(fill=X)
        
        header_inner = ttk.Frame(header, padding=(20, 15))
        header_inner.pack(fill=X)
        
        # Icono y título
        ttk.Label(header_inner, text="ASSISTENTE DE CALIBRAÇÃO", 
                  font=("Segoe UI", 22, "bold"), 
                  bootstyle="inverse-primary").pack(side=LEFT)
        
        # Botón cerrar grande
        btn_close = ttk.Button(header_inner, text="FECHAR", 
                               command=close_wizard, 
                               bootstyle="danger",
                               padding=(25, 12))
        btn_close.pack(side=RIGHT)
        
        # Main Split
        main = ttk.Frame(wizard, padding=15)
        main.pack(fill=BOTH, expand=YES)
        main.columnconfigure(0, weight=5)
        main.columnconfigure(1, weight=5)
        main.rowconfigure(0, weight=1)
        
        # === LEFT: Data Entry & Table ===
        left = ttk.Labelframe(main, text="  Dados de Calibração  ", padding=15, bootstyle="info")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        # Input Form
        f_in = ttk.Frame(left)
        f_in.pack(fill=X, pady=(0, 15))
        
        ttk.Label(f_in, text="Insira os pontos de calibração:", 
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
        
        # Campos de entrada en grid
        f_fields = ttk.Frame(f_in)
        f_fields.pack(fill=X)
        f_fields.columnconfigure(0, weight=1)
        f_fields.columnconfigure(1, weight=1)
        
        # Función para manejar Enter en los campos
        def on_weight_enter(event):
            # Al presionar Enter en peso, pasar a lectura
            e_reading.focus_set()
            return "break"
        
        def on_reading_enter(event):
            # Al presionar Enter en lectura, agregar punto automáticamente si hay datos
            w_str = self._cal_input_weight.get()
            r_str = self._cal_input_reading.get()
            if w_str and r_str:
                cmd_add_point()
            return "break"
        
        # Weight (en t)
        f_w = ttk.Frame(f_fields)
        f_w.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        ttk.Label(f_w, text="Peso Padrão (t):", font=("Segoe UI", 11)).pack(anchor="w")
        e_weight = ttk.Entry(f_w, textvariable=self._cal_input_weight, font=("Consolas", 16))
        e_weight.pack(fill=X, ipady=8)
        e_weight.bind("<Return>", on_weight_enter)
        e_weight.bind("<KP_Enter>", on_weight_enter)
        self._bind_numeric_keypad(e_weight, "Peso Padrão (t)")
        
        # Botón ADICIONAR debajo de Peso
        btn_add = ttk.Button(f_w, text="ADICIONAR PONTO", 
                   command=cmd_add_point, 
                   bootstyle="success",
                   padding=(20, 15))
        btn_add.pack(fill=X, pady=(10, 0))
        
        # Reading
        f_r = ttk.Frame(f_fields)
        f_r.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        ttk.Label(f_r, text="Leitura Sensor:", font=("Segoe UI", 11)).pack(anchor="w")
        e_reading = ttk.Entry(f_r, textvariable=self._cal_input_reading, font=("Consolas", 16))
        e_reading.pack(fill=X, ipady=8)
        e_reading.bind("<Return>", on_reading_enter)
        e_reading.bind("<KP_Enter>", on_reading_enter)
        self._bind_numeric_keypad(e_reading, "Leitura Sensor")
        
        # Botón CAPTURAR debajo de Leitura
        btn_capture = ttk.Button(f_r, text="CAPTURAR", 
                                  command=cmd_capture, 
                                  bootstyle="info",
                                  padding=(20, 15))
        btn_capture.pack(fill=X, pady=(10, 0))
        
        # Separador
        ttk.Separator(left).pack(fill=X, pady=15)
        
        # Table Header
        ttk.Label(left, text="Pontos Capturados:", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5))
        
        h_frame = ttk.Frame(left, bootstyle="dark", padding=8)
        h_frame.pack(fill=X)
        h_frame.columnconfigure(0, weight=1)
        h_frame.columnconfigure(1, weight=1)
        h_frame.columnconfigure(2, weight=0)
        ttk.Label(h_frame, text="PESO (t)", font=("Segoe UI", 10, "bold"), 
                  bootstyle="inverse-dark").grid(row=0, column=0)
        ttk.Label(h_frame, text="LEITURA", font=("Segoe UI", 10, "bold"),
                  bootstyle="inverse-dark").grid(row=0, column=1)
        # Columna vacía para alinear con botones de eliminar (sin texto)
        
        # Scrollable table
        from ttkbootstrap.scrolled import ScrolledFrame
        self._cal_tbl_scroll = ScrolledFrame(left, autohide=False, height=250)
        self._cal_tbl_scroll.pack(fill=BOTH, expand=YES, pady=5)
        
        # === RIGHT: Graph & Config ===
        right = ttk.Labelframe(main, text="Análise e Ajuste  ", padding=15, bootstyle="warning")
        right.grid(row=0, column=1, sticky="nsew")
        
        # Config Frame - Solo unidad
        f_cfg = ttk.Frame(right)
        f_cfg.pack(fill=X, pady=(0, 10))
        
        # Forzar método internamente (sin mostrar texto)
        self._cal_method_var.set("Interpolação Segmentos")
        
        # Unit selector
        f_unit = ttk.Frame(f_cfg)
        f_unit.pack(fill=X)
        ttk.Label(f_unit, text="Unidade de Leitura:", font=("Segoe UI", 12)).pack(anchor="w")
        units = ["Bits (Raw)", "mV/V", "kg", "t"]
        ttk.Combobox(f_unit, textvariable=self._cal_unit_var, values=units, 
                     state="readonly", font=("Segoe UI", 14)).pack(fill=X, ipady=6)
        
        # Graph Frame
        g_frame = ttk.Frame(right, bootstyle="light", padding=5)
        g_frame.pack(fill=BOTH, expand=YES, pady=10)
        
        # Inicializar gráfico de forma segura
        self._cal_fig = None
        self._cal_ax = None
        self._cal_canvas = None
        
        if MATPLOTLIB_AVAILABLE:
            try:
                self._cal_fig = Figure(figsize=(5, 4), dpi=100, facecolor='#f8f9fa')
                self._cal_ax = self._cal_fig.add_subplot(111)
                self._cal_ax.set_facecolor('#ffffff')
                self._cal_ax.set_xlabel("Leitura Sensor", fontsize=10)
                self._cal_ax.set_ylabel("Peso (t)", fontsize=10)
                self._cal_ax.grid(True, linestyle='--', alpha=0.5)
                
                self._cal_canvas = FigureCanvasTkAgg(self._cal_fig, master=g_frame)
                self._cal_canvas.get_tk_widget().pack(fill=BOTH, expand=YES)
                
                # Dibujo diferido para evitar bloqueo
                wizard.after(100, lambda: self._cal_canvas.draw_idle() if self._cal_wizard_active else None)
            except Exception as e:
                print(f"[GUI] Error matplotlib: {e}")
                ttk.Label(g_frame, text="Erro ao inicializar gráfico", 
                          font=("Segoe UI", 12)).pack(expand=YES)
        else:
            ttk.Label(g_frame, text="Matplotlib não disponível\nInstale com: pip install matplotlib", 
                      font=("Segoe UI", 12), justify="center").pack(expand=YES)
        
        ttk.Button(right, text="FINALIZAR E APLICAR CALIBRAÇÃO", 
                   command=cmd_apply_cal, 
                   bootstyle="success",
                   padding=(20, 15)).pack(fill=X, pady=(10, 0))
        
    def _refresh_cal_wizard_table_ui(self):
        for w in self._cal_tbl_scroll.winfo_children(): 
            w.destroy()
        
        points = self._cal_manager.get_points()
        
        if not points:
            # Mensaje cuando no hay puntos
            empty_lbl = ttk.Label(self._cal_tbl_scroll, 
                                  text="Não há pontos adicionados.\nInsira peso e leitura, depois pressione ADICIONAR.",
                                  font=("Segoe UI", 11), foreground="gray", justify="center")
            empty_lbl.pack(expand=YES, pady=30)
            return
            
        for i, (peso, lectura) in enumerate(points):
            # Fila con fondo alternado
            bg_style = "light" if i % 2 == 0 else "secondary"
            row = ttk.Frame(self._cal_tbl_scroll, padding=8, bootstyle=bg_style)
            row.pack(fill=X, pady=1)
            row.columnconfigure(0, weight=1)
            row.columnconfigure(1, weight=1)
            row.columnconfigure(2, weight=0)
            
            # Variables para edición
            v_w = tk.StringVar(value=f"{peso:.2f}")
            v_r = tk.StringVar(value=f"{lectura:.2f}")
            
            # Callback para actualizar modelo
            def update_model(idx=i, var=v_w, field='w'):
                try: 
                    val = float(var.get())
                    if idx < len(self._cal_manager.points):
                        if field == 'w': 
                            self._cal_manager.points[idx].weight = val
                        else: 
                            self._cal_manager.points[idx].reading = val
                        self._update_cal_wizard_graph()
                except: 
                    pass

            # Entry Peso - con teclado numérico
            e_w = ttk.Entry(row, textvariable=v_w, font=("Consolas", 12), justify="center")
            e_w.grid(row=0, column=0, sticky="ew", padx=5)
            e_w.bind("<FocusOut>", lambda e, idx=i, var=v_w: update_model(idx, var, 'w'))
            e_w.bind("<Button-1>", lambda e, ew=e_w: self.after(50, lambda: self._show_numeric_keypad(ew, "Peso (t)")))

            # Entry Leitura - con teclado numérico
            e_r = ttk.Entry(row, textvariable=v_r, font=("Consolas", 12), justify="center")
            e_r.grid(row=0, column=1, sticky="ew", padx=5)
            e_r.bind("<FocusOut>", lambda e, idx=i, var=v_r: update_model(idx, var, 'r'))
            e_r.bind("<Button-1>", lambda e, er=e_r: self.after(50, lambda: self._show_numeric_keypad(er, "Leitura")))
            
            # Botón Eliminar - más visible
            btn_del = ttk.Button(row, text="X", width=4, bootstyle="danger",
                                 command=lambda idx=i: self._cal_remove_point(idx),
                                 padding=(8, 5))
            btn_del.grid(row=0, column=2, padx=5)

    def _cal_remove_point(self, idx):
        """Elimina un punto de calibración con confirmación."""
        # Obtener info del punto
        points = self._cal_manager.get_points()
        if idx >= len(points):
            return
        peso, lectura = points[idx]
        
        # Mostrar confirmación con el estilo del programa
        if self.show_large_confirmation(
            "Eliminar Ponto", 
            f"Tem certeza que deseja eliminar o ponto?\n\nPeso: {peso:.2f} t\nLeitura: {lectura:.2f}"
        ):
            self._cal_manager.remove_point(idx)
            self._refresh_cal_wizard_table_ui()
            self._update_cal_wizard_graph()

    def _update_cal_wizard_graph(self):
        """Actualiza el gráfico usando interpolación lineal por segmentos."""
        if not MATPLOTLIB_AVAILABLE:
            return
        if not hasattr(self, '_cal_wizard_active') or not self._cal_wizard_active:
            return
        if self._cal_ax is None or self._cal_canvas is None: 
            return
        
        try:
            self._cal_ax.clear()
            self._cal_ax.set_xlabel("Leitura Sensor", fontsize=10)
            self._cal_ax.set_ylabel("Peso (t)", fontsize=10)
            self._cal_ax.grid(True, linestyle='--', alpha=0.5)
            self._cal_ax.set_facecolor('#ffffff')
            
            points = self._cal_manager.get_points()
            if not points: 
                self._cal_ax.set_title("Sem dados", fontsize=11, color='gray')
                self._cal_canvas.draw_idle()
                return

            # Ordenar puntos por valor de lectura (x)
            sorted_points = sorted(points, key=lambda p: p[1])
            x = np.array([p[1] for p in sorted_points])
            y = np.array([p[0] for p in sorted_points])
            
            # Scatter - puntos más grandes y visibles
            self._cal_ax.scatter(x, y, c='#2563eb', s=80, zorder=5, edgecolors='white', linewidth=2)
            
            # Interpolación Lineal por Segmentos (unir puntos con líneas rectas)
            if len(x) >= 2:
                # Dibujar líneas conectando los puntos ordenados
                self._cal_ax.plot(x, y, 'r-', linewidth=2, zorder=4)
                self._cal_ax.set_title(f"Curva de Calibração ({len(points)} pontos)", 
                                       fontsize=11, fontweight='bold')
            else:
                self._cal_ax.set_title(f"{len(points)} ponto(s) - Adicione mais para ajustar", 
                                       fontsize=11, color='gray')
                     
            self._cal_canvas.draw_idle()
        except Exception as e:
            print(f"[GUI] Erro atualizando gráfico: {e}")
