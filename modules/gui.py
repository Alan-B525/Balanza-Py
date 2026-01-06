import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, BOTH, YES, NO, X, Y, LEFT, RIGHT, END, HORIZONTAL, BOTTOM, TOP
from PIL import Image, ImageTk

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText

from config import APP_TITLE, APP_SIZE, THEME_NAME, NODOS_CONFIG

class BalanzaGUI(ttk.Window):
    def __init__(self, data_queue, command_queue):
        super().__init__(themename=THEME_NAME)
        self.title(APP_TITLE)
        
        # Remover barra de título de Windows (modo frameless)
        self.overrideredirect(True)
        
        # Obtener tamaño de pantalla y usar pantalla completa
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{screen_width}x{screen_height}+0+0")
        
        # Guardar referencia para mover ventana (drag)
        self._drag_data = {"x": 0, "y": 0}
        
        self.data_queue = data_queue
        self.command_queue = command_queue
        
        self.connected = False
        
        # Almacenar últimos datos para calibración
        self._last_sensor_data = {}
        
        # Almacenar nodos descubiertos
        self._discovered_nodes = []
        
        # Variables para conexión asíncrona
        self._connection_thread = None
        self._cancel_connection = False
        
        # Handle window close event
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        
        self._configure_styles()
        self._setup_ui()
        
        # Start update loop
        self.after(50, self.actualizar_gui)
        
        # Iniciar conexão automaticamente após a UI carregar
        self.after(500, self._auto_connect_on_startup)

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
        
        # Configure Label styles - MÁS GRANDES para mejor visibilidad
        self.style.configure('CardTitle.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 16, "bold"))
        self.style.configure('CardValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MONO, 48, "bold"))
        self.style.configure('Unit.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 18))
        self.style.configure('SensorStatus.TLabel', background=BG_CARD, foreground=SUCCESS, font=(FONT_MAIN, 13, "bold"))
        
        # Total Panel - MUY PROMINENTE para énfasis máximo
        self.style.configure('TotalPanel.TFrame', background=PRIMARY)
        self.style.configure('TotalLabel.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, 28, "bold"))
        self.style.configure('TotalValue.TLabel', background=PRIMARY, foreground="white", font=(FONT_MONO, 120, "bold"))
        self.style.configure('TotalUnit.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, 36))
        
        # Total Panel DANGER - Cuando hay sensor desconectado (ROJO)
        self.style.configure('TotalPanelDanger.TFrame', background=DANGER)
        self.style.configure('TotalLabelDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MAIN, 28, "bold"))
        self.style.configure('TotalValueDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MONO, 120, "bold"))
        self.style.configure('TotalUnitDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MAIN, 36))
        
        # Tara Info - Más visible
        self.style.configure('TareInfo.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 18, "bold"))
        
        # Buttons - Todos más grandes para tablet
        self.style.configure('Tare.TButton', font=(FONT_MAIN, 22, 'bold'))
        self.style.configure('Reset.TButton', font=(FONT_MAIN, 18, 'bold'))
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
        
        # Tamaño de logos (más grandes)
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
        
        # Título sin logo
        title_box = ttk.Frame(brand_frame, style='Header.TFrame')
        title_box.pack(side=LEFT)
        ttk.Label(title_box, text="Sistema de Pesagem Industrial", style='HeaderTitle.TLabel').pack(anchor="w")
        self.lbl_status = ttk.Label(title_box, text="Desconectado", style='HeaderSub.TLabel')
        self.lbl_status.pack(anchor="w")
        
        # Header Actions - Botones uniformes y grandes para tablet
        actions_frame = ttk.Frame(header_frame, style='Header.TFrame')
        actions_frame.pack(side=RIGHT)
        
        # Botón de Configuración - Color info (azul)
        self.btn_config = ttk.Button(
            actions_frame, 
            text="⚙ CONFIG", 
            bootstyle="info", 
            command=self.show_configuration_dialog, 
            style='Header.TButton',
            width=12,
            padding=(15, 12)
        )
        self.btn_config.pack(side=LEFT, padx=5)
        
        # Botón Conectar/Desconectar - Color success (verde)
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
        
        # Separador visual antes del botón SAIR
        ttk.Frame(actions_frame, width=30, style='Header.TFrame').pack(side=LEFT)
        
        # Botón Salir - Rojo y separado
        ttk.Button(
            actions_frame, 
            text="✕ SAIR", 
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
        
        # Columnas con tamaño FIJO usando minsize para evitar que cambien
        grid_area.columnconfigure(0, weight=1, minsize=280)
        grid_area.columnconfigure(1, weight=2, minsize=400)  # Centro más ancho para el TOTAL
        grid_area.columnconfigure(2, weight=1, minsize=280)
        grid_area.rowconfigure(0, weight=1, minsize=200)
        grid_area.rowconfigure(1, weight=1, minsize=200)

        self.sensor_widgets = {} 

        # Helper to create cards mapped to config keys
        def create_sensor_card(key, title, row, col):
            # Card con borde visible y tamaño uniforme
            card = ttk.Frame(grid_area, style='Card.TFrame', padding=20)
            card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
            card.grid_propagate(False)  # NO permitir que el contenido cambie el tamaño
            
            # Header con título y estado
            header = ttk.Frame(card, style='CardNoBorder.TFrame')
            header.pack(fill=X, pady=(0, 8))
            
            ttk.Label(header, text=title, style='CardTitle.TLabel').pack(side=LEFT)
            
            # Indicador de estado (más visible)
            status_frame = ttk.Frame(header, style='CardNoBorder.TFrame')
            status_frame.pack(side=RIGHT)
            
            rssi_lbl = ttk.Label(status_frame, text="●", font=("Segoe UI", 16), foreground="#94a3b8")
            rssi_lbl.pack(side=LEFT)
            status_lbl = ttk.Label(status_frame, text="Sem Sinal", font=("Segoe UI", 12, "bold"), foreground="#94a3b8")
            status_lbl.pack(side=LEFT, padx=(5, 0))
            
            # Separador
            ttk.Separator(card, orient=HORIZONTAL).pack(fill=X, pady=8)
            
            # Valor principal - Centrado con ancho fijo - MÁS GRANDE
            value_container = ttk.Frame(card, style='CardNoBorder.TFrame')
            value_container.pack(fill=BOTH, expand=YES)
            
            value_lbl = ttk.Label(
                value_container, 
                text="0.00", 
                font=('Consolas', 64, 'bold'),  # Más grande: 56 -> 64
                foreground="#1e293b", 
                background="#ffffff",
                anchor="center",
                width=8  # Ancho fijo para evitar cambios
            )
            value_lbl.pack(expand=YES)
            
            # Unidad
            ttk.Label(
                value_container, 
                text="ton", 
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
            create_sensor_card(keys[0], "📦 CELDA 1", 0, 0)
            create_sensor_card(keys[1], "📦 CELDA 2", 0, 2)
            create_sensor_card(keys[2], "📦 CELDA 3", 1, 0)
            create_sensor_card(keys[3], "📦 CELDA 4", 1, 2)
        elif len(keys) >= 2:
            # Fallback si solo hay 2 celdas configuradas
            create_sensor_card(keys[0], "📦 CELDA 1", 0, 0)
            create_sensor_card(keys[1], "📦 CELDA 2", 0, 2)

        # --- PANEL CENTRAL: TOTAL (MÁS GRANDE) ---
        control_panel = ttk.Frame(grid_area, style='Card.TFrame', padding=15)
        control_panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=8)
        control_panel.grid_propagate(False)  # Tamaño fijo
        
        # Sección TOTAL con fondo azul - MUY GRANDE Y PROMINENTE
        # Guardar referencia para poder cambiar color en caso de desconexión
        self.total_section = ttk.Frame(control_panel, style='TotalPanel.TFrame', padding=35)
        self.total_section.pack(fill=BOTH, expand=YES)
        
        self.lbl_total_title = ttk.Label(self.total_section, text="PESO TOTAL", style='TotalLabel.TLabel', anchor="center")
        self.lbl_total_title.pack(fill=X)
        self.lbl_total = ttk.Label(
            self.total_section, 
            text="0", 
            style='TotalValue.TLabel', 
            anchor="center",
            width=10  # Ancho fijo para evitar cambios
        )
        self.lbl_total.pack(fill=X, pady=20)
        self.lbl_total_unit = ttk.Label(self.total_section, text="ton", style='TotalUnit.TLabel', anchor="center")
        self.lbl_total_unit.pack()
        self.lbl_total_unit.pack()
        
        # Separador dentro del panel
        ttk.Separator(control_panel, orient=HORIZONTAL).pack(fill=X, pady=15)
        
        # Sección de Acciones debajo del total
        actions_section = ttk.Frame(control_panel, style='CardNoBorder.TFrame', padding=10)
        actions_section.pack(fill=X)
        
        # Info de Tara - MÁS GRANDE Y VISIBLE
        self.lbl_tare_info = ttk.Label(
            actions_section, 
            text="Tara Acumulada: 0 kg", 
            style='TareInfo.TLabel',
            anchor="center"
        )
        self.lbl_tare_info.pack(pady=(0, 20))
        
        # Frame para botones lado a lado
        btn_row = ttk.Frame(actions_section, style='CardNoBorder.TFrame')
        btn_row.pack(fill=X)
        
        # Botón ZERAR (Tarar) - Grande y prominente
        btn_tare = ttk.Button(
            btn_row, 
            text="ZERAR", 
            command=self.do_tare, 
            bootstyle="warning", 
            style='Tare.TButton', 
            width=12, 
            padding=(25, 18)
        )
        btn_tare.pack(side=LEFT, expand=YES, padx=5)
        
        # Botón Reset Tara - MISMO TAMAÑO que ZERAR
        btn_reset = ttk.Button(
            btn_row, 
            text="RESET TARA", 
            command=self.reset_tare, 
            bootstyle="secondary", 
            style='Tare.TButton',  # Mismo estilo que ZERAR
            width=12, 
            padding=(25, 18)  # Mismo padding que ZERAR
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
        
        # Log centrado (misma proporción que columna central)
        log_center = ttk.Frame(log_container, style='CardNoBorder.TFrame')
        log_center.grid(row=0, column=1, sticky="ew", padx=10)
        
        log_header = ttk.Frame(log_center, style='CardNoBorder.TFrame')
        log_header.pack(fill=X, pady=(0, 5))
        ttk.Label(log_header, text="📋 Registro de Eventos", font=("Segoe UI", 11, "bold"), foreground="#64748b", background="#ffffff").pack(anchor="center")
        
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
                    self._last_sensor_data = data  # Guardar para calibración
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
                    # Actualizar lista de nodos descubiertos en configuración
                    payload = msg['payload']
                    self._handle_discovered_nodes(payload)
                
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
        # Actualizar Tara Acumulada en toneladas
        if 'total_tare' in data:
            tara_ton = data['total_tare']  # Ya viene en toneladas del procesador
            self.lbl_tare_info.configure(text=f"Tara Acumulada: {tara_ton:.2f} ton")
        
        # Verificar si hay sensores desconectados para cambiar color del panel
        any_disconnected = data.get('any_disconnected', False)
        
        # También verificar manualmente en los sensores
        if not any_disconnected:
            for sensor_info in data.get('sensores', {}).values():
                if not sensor_info.get('connected', True):
                    any_disconnected = True
                    break
        
        # Cambiar color del panel TOTAL según estado de sensores - FAIL-SAFE
        if any_disconnected:
            # ROJO - Hay sensor(es) desconectado(s) - SISTEMA PARADO
            self.total_section.configure(style='TotalPanelDanger.TFrame')
            self.lbl_total_title.configure(text="ERRO DE COMUNICAÇÃO", style='TotalLabelDanger.TLabel')
            self.lbl_total.configure(text="---", style='TotalValueDanger.TLabel')
            self.lbl_total_unit.configure(text="SISTEMA PARADO", style='TotalUnitDanger.TLabel')
        else:
            # AZUL - Todos los sensores conectados (normal)
            self.total_section.configure(style='TotalPanel.TFrame')
            self.lbl_total_title.configure(text="PESO TOTAL", style='TotalLabel.TLabel')
            peso_ton = data['total']  # Ya viene en toneladas del procesador
            self.lbl_total.configure(text=f"{peso_ton:.2f}", style='TotalValue.TLabel')
            self.lbl_total_unit.configure(text="ton", style='TotalUnit.TLabel')
        
        # Actualizar Sensores Individuales
        sensores = data['sensores']
        for key, widgets in self.sensor_widgets.items():
            if key in sensores:
                info = sensores[key]
                
                # Actualizar valor - Mostrar en toneladas con 2 decimales
                valor_ton = info['valor']  # Ya viene en toneladas del procesador
                widgets['value'].configure(text=f"{valor_ton:.2f}")
                
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
        """Mostra um diálogo modal personalizado SEM barra de título, com fontes e botões grandes."""
        result = {'value': False}
        
        # Criar janela secundária SIN BARRA DE TÍTULO
        dialog = ttk.Toplevel(self)
        dialog.overrideredirect(True)  # Quitar barra de Windows
        dialog.geometry("600x360")
        
        # Centralizar em relação à janela principal
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 300
            y = self.winfo_y() + (self.winfo_height() // 2) - 180
            dialog.geometry(f"+{x}+{y}")
        except:
            pass
        
        # Forzar que aparezca arriba
        dialog.lift()
        dialog.focus_force()
            
        # Container con borde para definir el diálogo
        outer_frame = ttk.Frame(dialog, bootstyle="secondary", padding=3)
        outer_frame.pack(fill=BOTH, expand=YES)
        
        frame = ttk.Frame(outer_frame, padding=30)
        frame.pack(fill=BOTH, expand=YES)
        
        # Título personalizado
        title_lbl = ttk.Label(frame, text=title.upper(), font=("Segoe UI", 16, "bold"), foreground="#1e293b")
        title_lbl.pack(pady=(0, 20))
        
        # Mensagem grande
        lbl = ttk.Label(frame, text=message, font=("Segoe UI", 20), wraplength=480, justify="center")
        lbl.pack(pady=(10, 40), expand=YES)
        
        # Botões grandes
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X, pady=10)
        
        # Función de cierre seguro
        def safe_close():
            try:
                dialog.grab_release()
            except:
                pass
            try:
                dialog.destroy()
            except:
                pass
        
        def on_yes():
            result['value'] = True
            safe_close()
            
        def on_no():
            safe_close()
            
        btn_yes = ttk.Button(btn_frame, text="SIM", style="Large.success.TButton", width=12, 
                             command=on_yes, padding=(20, 15))
        btn_yes.pack(side=LEFT, padx=20, expand=YES, fill=X)
        
        btn_no = ttk.Button(btn_frame, text="NÃO", style="Large.danger.TButton", width=12, 
                            command=on_no, padding=(20, 15))
        btn_no.pack(side=RIGHT, padx=20, expand=YES, fill=X)

        # Configurar cierre con protocolo
        dialog.protocol("WM_DELETE_WINDOW", on_no)
        
        dialog.transient(self)
        try:
            dialog.grab_set()
        except:
            pass  # Ignorar si no se puede obtener el grab
        self.wait_window(dialog)
        
        return result['value']

    def show_alert(self, title, message, alert_type="info", parent=None):
        """Mostra um alerta SEM barra de título, com estilo grande."""
        target = parent or self
        
        # Criar janela SIN BARRA DE TÍTULO
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
        
        # Estilo según tipo
        if alert_type == "error":
            bootstyle = "danger"
            icon = "⚠️"
        elif alert_type == "success":
            bootstyle = "success"
            icon = "✅"
        else:
            bootstyle = "info"
            icon = "ℹ️"
        
        # Container con borde
        outer_frame = ttk.Frame(dialog, bootstyle=bootstyle, padding=3)
        outer_frame.pack(fill=BOTH, expand=YES)
        
        frame = ttk.Frame(outer_frame, padding=25)
        frame.pack(fill=BOTH, expand=YES)
        
        # Título
        title_lbl = ttk.Label(frame, text=f"{icon}  {title.upper()}", 
                              font=("Segoe UI", 16, "bold"), foreground="#1e293b")
        title_lbl.pack(pady=(0, 15))
        
        # Mensaje
        msg_lbl = ttk.Label(frame, text=message, font=("Segoe UI", 14), 
                            wraplength=440, justify="center")
        msg_lbl.pack(pady=(10, 25), expand=YES)
        
        # Función de cierre seguro
        def close_dialog():
            try:
                dialog.grab_release()
            except:
                pass
            try:
                dialog.destroy()
            except:
                pass
        
        # Botón OK
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
        
        # Icono y titulo
        title_lbl = ttk.Label(
            frame, 
            text="⚠️  SENSOR DESCONECTADO", 
            font=("Segoe UI", 20, "bold"), 
            foreground="#dc2626"
        )
        title_lbl.pack(pady=(0, 20))
        
        # Mensaje principal
        msg_text = f"El sensor '{nombre}' (ID: {node_id}) ha perdido la conexión.\n\n" \
                   f"La adquisición de datos está pausada."
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
            text="Reconexión automática en progreso...",
            font=("Segoe UI", 12),
            foreground="#f59e0b"
        )
        progress_lbl.pack()
        
        attempt_lbl = ttk.Label(
            progress_frame,
            text=f"Intento 0 de {max_attempts}",
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
            progress_lbl.configure(text="Reconexión manual iniciada...", foreground="#22c55e")
            attempt_lbl.configure(text="Esperando respuesta del sensor...")
        
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
            text="🔄 RECONECTAR AHORA", 
            bootstyle="warning",
            command=on_manual_reconnect,
            padding=(20, 15),
            width=20
        )
        btn_reconnect.pack(side=LEFT, padx=10, expand=YES)
        
        # Boton continuar sin sensor
        btn_continue = ttk.Button(
            btn_frame, 
            text="➡️ CONTINUAR SIN SENSOR", 
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
                    text=f"Intento {attempt} de {max_attempts}"
                )
    
    def _handle_sensor_reconnected(self, payload):
        """Maneja cuando un sensor se reconecta exitosamente."""
        node_id = payload['node_id']
        
        # Mostrar mensaje de exito y cerrar dialogo
        self.log_message(f"✓ Sensor {node_id} reconectado exitosamente")
        
        # Actualizar dialogo si existe
        if hasattr(self, '_disconnect_dialogs') and node_id in self._disconnect_dialogs:
            dialog_info = self._disconnect_dialogs[node_id]
            if dialog_info['progress_label']:
                dialog_info['progress_label'].configure(
                    text="✓ RECONECTADO EXITOSAMENTE",
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
        
        self.log_message(f"✗ Falló reconexión del sensor {node_id} después de {attempts} intentos")
        
        # Actualizar dialogo
        if hasattr(self, '_disconnect_dialogs') and node_id in self._disconnect_dialogs:
            dialog_info = self._disconnect_dialogs[node_id]
            if dialog_info['progress_label']:
                dialog_info['progress_label'].configure(
                    text=f"✗ RECONEXIÓN FALLIDA ({attempts} intentos)",
                    foreground="#dc2626"
                )
            if dialog_info['attempt_label']:
                dialog_info['attempt_label'].configure(
                    text="Use 'Reconectar Ahora' o continúe sin el sensor"
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
                    f"✅ Encontrados {len(nodes_list)} nodo(s) com {total_channels} canal(is)"
                )
            else:
                self._discovered_nodes_var.set("⚠️ Nenhum nó encontrado")
        
        # Actualizar treeview si existe
        if hasattr(self, '_disc_tree'):
            try:
                # Limpiar treeview
                for item in self._disc_tree.get_children():
                    self._disc_tree.delete(item)
                
                # Agregar nodos y canales
                for node in nodes_list:
                    node_id = node.get('id', 0)
                    rssi = node.get('rssi', 0)
                    channels = node.get('channels', [])
                    
                    for ch_info in channels:
                        ch_name = ch_info.get('channel', 'ch1')
                        ch_value = ch_info.get('value', 0.0)
                        
                        self._disc_tree.insert("", "end", values=(
                            node_id,
                            ch_name,
                            f"{rssi} dBm",
                            f"{ch_value:.4f}",
                            "✅ Activo"
                        ))
            except Exception as e:
                self.log_message(f"Erro atualizando lista de nós: {e}")

    def toggle_connection(self):
        if not self.connected:
            self._show_connection_dialog()
        else:
            self.command_queue.put({'cmd': 'DISCONNECT'})

    def _auto_connect_on_startup(self):
        """Inicia conexão automaticamente quando o programa abre."""
        if not self.connected:
            self._show_connection_dialog()

    def _show_connection_dialog(self):
        """Mostra diálogo de conexão - 100% não bloqueante."""
        self._connection_dialog_active = True
        self._cancel_connection = False
        
        # Criar janela
        dialog = ttk.Toplevel(self)
        dialog.overrideredirect(True)
        dialog.geometry("700x480")
        
        # Centralizar
        x = self.winfo_x() + (self.winfo_width() // 2) - 350
        y = self.winfo_y() + (self.winfo_height() // 2) - 240
        dialog.geometry(f"+{x}+{y}")
        
        dialog.lift()
        
        # Container
        outer_frame = ttk.Frame(dialog, bootstyle="secondary", padding=3)
        outer_frame.pack(fill=BOTH, expand=YES)
        
        frame = ttk.Frame(outer_frame, padding=25)
        frame.pack(fill=BOTH, expand=YES)
        
        # Título
        ttk.Label(frame, text="CONECTANDO", font=("Segoe UI", 20, "bold"), 
                  foreground="#1e293b").pack(pady=(5, 10))
        
        # Ícone
        ttk.Label(frame, text="🔌", font=("Segoe UI", 44)).pack(pady=8)
        
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
        
        dialog.transient(self)
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
        
        # Éxito
        if self.connected:
            self._conn_progress.stop()
            self._conn_status.configure(text="✅ Conectado!", foreground="#22c55e")
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
        self._conn_info.configure(text=f"Tentativa {self._conn_attempt} • {int(elapsed)}s")
        
        # Timeout por intento (6 segundos)
        if elapsed > 6 * self._conn_attempt:
            if self._conn_attempt < 3:
                self._conn_attempt += 1
                self._conn_status.configure(text=f"Tentativa {self._conn_attempt}...")
                self.command_queue.put({'cmd': 'CONNECT'})
            else:
                # Falló después de 3 intentos
                self._conn_progress.stop()
                self._conn_status.configure(
                    text="❌ Sensor não encontrado", foreground="#ef4444")
                self._conn_info.configure(text="Verifique a conexão e tente novamente")
                self._conn_btn.configure(text="FECHAR", bootstyle="secondary",
                                          command=self._safe_close_conn_dialog)
                self._connection_dialog_active = False
                return
        
        # Continuar verificando (nunca bloquea)
        self._conn_dialog.after(100, self._check_connection_status)
    
    def _cancel_connection_dialog(self):
        """Cancela conexión inmediatamente."""
        self._cancel_connection = True
        self._connection_dialog_active = False
        self._conn_progress.stop()
        self._conn_status.configure(text="Cancelado")
        self._conn_dialog.after(300, self._safe_close_conn_dialog)
    
    def _safe_close_conn_dialog(self):
        """Cierra diálogo de forma segura."""
        try:
            if hasattr(self, '_conn_dialog') and self._conn_dialog.winfo_exists():
                self._conn_dialog.destroy()
        except:
            pass
        
    def _update_connection_progress(self, data):
        """Atualiza o diálogo de conexão com o progresso."""
        if not hasattr(self, '_connection_dialog') or not self._connection_dialog_active:
            return
            
        try:
            attempt = data.get('attempt', 1)
            max_attempts = data.get('max_attempts', 3)
            status = data.get('status', 'connecting')
            message = data.get('message', 'Conectando...')
            
            self._connection_attempt_lbl.configure(
                text=f"Tentativa {attempt} de {max_attempts}"
            )
            self._connection_status_lbl.configure(text=message)
            
            if status == 'success':
                self._connection_progress.stop()
                self._connection_status_lbl.configure(
                    text="✅ Conexão estabelecida com sucesso!",
                    foreground="#22c55e"
                )
                self._connection_btn_cancel.configure(state='disabled')
                self._connection_dialog_active = False
                self._connection_dialog.after(1000, self._connection_dialog.destroy)
                
            elif status == 'failed':
                self._connection_progress.stop()
                self._connection_status_lbl.configure(
                    text="❌ " + message,
                    foreground="#ef4444"
                )
                self._connection_btn_cancel.configure(text="FECHAR", state='normal')
                self._connection_dialog_active = False
                
            elif status == 'cancelled':
                self._connection_progress.stop()
                self._connection_dialog_active = False
                try:
                    self._connection_dialog.destroy()
                except:
                    pass
                    
        except Exception as e:
            print(f"[GUI] Erro atualizando progresso de conexão: {e}")
    
    def _close_connection_dialog(self):
        """Fecha o diálogo de conexão se estiver aberto."""
        self._connection_dialog_active = False
        if hasattr(self, '_connection_dialog'):
            try:
                self._connection_dialog.destroy()
            except:
                pass

    def quit_app(self):
        if self.show_large_confirmation("Sair", "Deseja sair do sistema?"):
            self.command_queue.put({'cmd': 'EXIT'})
            self.destroy()

    def show_configuration_dialog(self):
        """Abre um diálogo para configurar sensores e calibração."""
        import json
        import os
        
        # Carregar configuração atual ou usar defaults
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

        # Criar janela modal - SEM BARRA DE TÍTULO
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

        # Estilos para abas grandes (touch-friendly)
        style = ttk.Style()
        style.configure('BigTab.TNotebook.Tab', 
                        font=('Segoe UI', 22, 'bold'), 
                        padding=(50, 25))
        
        # Função de fechamento seguro
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
        
        main_frame = ttk.Frame(border_frame, padding=20)
        main_frame.pack(fill=BOTH, expand=YES)
        
        # Título
        title_frame = ttk.Frame(main_frame, style='Header.TFrame', padding=10)
        title_frame.pack(fill=X, pady=(0, 15))
        
        ttk.Label(title_frame, text="⚙  CONFIGURAÇÃO DO SISTEMA", 
                  font=("Segoe UI", 26, "bold"), 
                  foreground="#1e293b", 
                  background="#ffffff").pack(side=LEFT)
        
        btn_close = ttk.Button(title_frame, text="✕ FECHAR", 
                               bootstyle="danger", 
                               command=safe_close_dialog,
                               width=12,
                               padding=(20, 12))
        btn_close.pack(side=RIGHT)

        # --- Container com SCROLL ---
        from ttkbootstrap.scrolled import ScrolledFrame
        scroll_container = ScrolledFrame(main_frame, autohide=True)
        scroll_container.pack(fill=BOTH, expand=YES)
        
        # --- Abas ---
        notebook = ttk.Notebook(scroll_container, style='BigTab.TNotebook')
        notebook.pack(fill=BOTH, expand=YES)
        
        # ==================== Tab Sensores ====================
        tab_nodes = ttk.Frame(notebook, padding=30)
        notebook.add(tab_nodes, text="   📡 SENSORES   ")
        
        ttk.Label(tab_nodes, text="Configuração de Celdas de Carga", 
                  font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 10))
        
        ttk.Label(tab_nodes, 
                  text="2 Nodos SG-Link-200 com 2 canais cada = 4 celdas de carga no total",
                  font=("Segoe UI", 12), foreground="#64748b").pack(anchor="w", pady=(0, 20))
        
        # === Porta Serial (USB Gateway) ===
        port_frame = ttk.Labelframe(tab_nodes, text="Porta Serial (Gateway USB)", padding=15)
        port_frame.pack(fill=X, pady=(0, 20))
        
        port_inner = ttk.Frame(port_frame)
        port_inner.pack(fill=X)
        
        ttk.Label(port_inner, text="Porta COM:", font=("Segoe UI", 14)).pack(side=LEFT, padx=(0, 10))
        entry_serial = ttk.Entry(port_inner, font=("Segoe UI", 14), width=15)
        entry_serial.insert(0, current_config.get("serial_port", "COM3"))
        entry_serial.pack(side=LEFT, ipady=6)
        
        ttk.Label(port_inner, text="(ex: COM3, COM4, etc.)", 
                  font=("Segoe UI", 11), foreground="#64748b").pack(side=LEFT, padx=(15, 0))
        
        # === Frame de Descubrimiento ===
        discover_frame = ttk.Labelframe(tab_nodes, text="Descoberta de Nós", padding=15)
        discover_frame.pack(fill=X, pady=(0, 20))
        
        discover_btn_frame = ttk.Frame(discover_frame)
        discover_btn_frame.pack(fill=X, pady=(0, 10))
        
        # Variable para almacenar nodos descubiertos
        self._discovered_nodes = []
        self._discovered_nodes_var = tk.StringVar(value="Conecte o sistema e pressione 'Buscar' para descobrir nós")
        
        def discover_nodes_action():
            """Inicia descubrimiento de nodos."""
            self._discovered_nodes_var.set("🔍 Procurando nós na rede... aguarde...")
            self.command_queue.put({'cmd': 'DISCOVER_NODES'})
            self.log_message("Iniciando descoberta de nós SG-Link...")
        
        ttk.Button(
            discover_btn_frame, 
            text="🔍 BUSCAR NÓS NA REDE", 
            command=discover_nodes_action,
            bootstyle="info",
            padding=(25, 15)
        ).pack(side=LEFT)
        
        # Botón para autoasignar
        def auto_assign_nodes():
            """Autoasigna nodos descubiertos a las celdas."""
            if not self._discovered_nodes:
                self._discovered_nodes_var.set("⚠️ Primeiro busque os nós na rede")
                return
            
            # Autoasignar: recorrer nodos y canales
            celda_idx = 1
            for node in self._discovered_nodes:
                node_id = node.get('id', 0)
                channels = node.get('channels', [])
                
                for ch_info in channels:
                    if celda_idx > 4:
                        break
                    ch_name = ch_info.get('channel', 'ch1')
                    
                    # Actualizar entries
                    key = f"celda_{celda_idx}"
                    if key in node_entries:
                        node_entries[key]["id"].delete(0, END)
                        node_entries[key]["id"].insert(0, str(node_id))
                        node_entries[key]["ch"].delete(0, END)
                        node_entries[key]["ch"].insert(0, ch_name)
                    
                    celda_idx += 1
                
                if celda_idx > 4:
                    break
            
            self._discovered_nodes_var.set(f"✅ {celda_idx - 1} celdas auto-atribuídas")
        
        ttk.Button(
            discover_btn_frame, 
            text="⚡ AUTO-ATRIBUIR", 
            command=auto_assign_nodes,
            bootstyle="warning",
            padding=(20, 15)
        ).pack(side=LEFT, padx=(15, 0))
        
        # Label de status
        ttk.Label(
            discover_frame, 
            textvariable=self._discovered_nodes_var, 
            font=("Segoe UI", 12), 
            foreground="#64748b"
        ).pack(anchor="w", pady=(10, 5))
        
        # Frame para mostrar nodos descubiertos
        discovered_list_frame = ttk.Frame(discover_frame)
        discovered_list_frame.pack(fill=X, pady=(5, 0))
        
        # Treeview para mostrar nodos descubiertos
        disc_columns = ("node_id", "channel", "rssi", "value", "status")
        self._disc_tree = ttk.Treeview(discovered_list_frame, columns=disc_columns, 
                                        show="headings", height=4)
        
        self._disc_tree.heading("node_id", text="Nodo ID")
        self._disc_tree.heading("channel", text="Canal")
        self._disc_tree.heading("rssi", text="RSSI")
        self._disc_tree.heading("value", text="Valor Atual")
        self._disc_tree.heading("status", text="Estado")
        
        self._disc_tree.column("node_id", width=100, anchor="center")
        self._disc_tree.column("channel", width=80, anchor="center")
        self._disc_tree.column("rssi", width=80, anchor="center")
        self._disc_tree.column("value", width=120, anchor="center")
        self._disc_tree.column("status", width=100, anchor="center")
        
        self._disc_tree.pack(fill=X, pady=(5, 0))
        
        node_entries = {}
        
        # === CONFIGURACIÓN DE 4 CELDAS NUMERADAS ===
        ttk.Label(tab_nodes, text="Atribuição de Celdas (1-4):", 
                  font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(20, 10))
        
        # Frame para las 4 celdas en una fila
        cells_frame = ttk.Frame(tab_nodes)
        cells_frame.pack(fill=X, pady=(0, 15))
        
        for i in range(4):
            cells_frame.columnconfigure(i, weight=1)
        
        # Crear las 4 celdas
        for celda_num in range(1, 5):
            key = f"celda_{celda_num}"
            current_node_data = current_config["nodes"].get(key, {"id": 0, "ch": "ch1", "nombre": f"Celda {celda_num}"})
            
            # Frame de cada celda
            cell_frame = ttk.Labelframe(cells_frame, text=f"📦 CELDA {celda_num}", padding=15)
            cell_frame.grid(row=0, column=celda_num-1, sticky="nsew", padx=8, pady=5)
            
            # Node ID
            id_frame = ttk.Frame(cell_frame)
            id_frame.pack(fill=X, pady=5)
            ttk.Label(id_frame, text="Nodo ID:", font=("Segoe UI", 12)).pack(side=LEFT)
            e_id = ttk.Entry(id_frame, font=("Segoe UI", 14), width=10)
            e_id.insert(0, str(current_node_data.get("id", 0)))
            e_id.pack(side=RIGHT, ipady=6)
            
            # Channel
            ch_frame = ttk.Frame(cell_frame)
            ch_frame.pack(fill=X, pady=5)
            ttk.Label(ch_frame, text="Canal:", font=("Segoe UI", 12)).pack(side=LEFT)
            ch_combo = ttk.Combobox(ch_frame, values=["ch1", "ch2", "ch3", "ch4"], 
                                     font=("Segoe UI", 14), width=8, state="readonly")
            ch_combo.set(current_node_data.get("ch", "ch1"))
            ch_combo.pack(side=RIGHT, ipady=4)
            
            node_entries[key] = {"id": e_id, "ch": ch_combo}
        
        # Nota explicativa
        ttk.Label(tab_nodes, 
                  text="💡 Cada nodo SG-Link-200 tiene 2 canales (ch1, ch2). "
                       "Configure cada celda con su nodo y canal correspondiente.",
                  font=("Segoe UI", 11), foreground="#64748b",
                  wraplength=800).pack(anchor="w", pady=(10, 5))

        # ==================== Tab CALIBRAÇÃO ====================
        tab_cal = ttk.Frame(notebook, padding=30)
        notebook.add(tab_cal, text="   ⚖ CALIBRAÇÃO   ")
        
        self._setup_calibration_tab(tab_cal, current_config)

        # ==================== Botões de Ação ====================
        # Frame de botões fixo na parte inferior con borda superior
        btn_frame = ttk.Frame(border_frame, padding=(30, 20))
        btn_frame.pack(fill=X, side=BOTTOM)
        
        # Separador visual
        ttk.Separator(btn_frame, orient="horizontal").pack(fill=X, pady=(0, 15))
        
        # Container para botões
        btn_container = ttk.Frame(btn_frame)
        btn_container.pack(fill=X)
        
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
                new_config["nodes"][key] = {
                    "id": nid,
                    "ch": inputs["ch"].get()
                }
            
            try:
                with open(config_path, 'w') as f:
                    json.dump(new_config, f, indent=4)
                
                # Liberar grab antes de mostrar alerta
                try:
                    dialog.grab_release()
                except:
                    pass
                
                self.show_alert("Salvo", "Configuração salva.\nReinicie a aplicação para aplicar as alterações.", "success", parent=self)
                safe_close_dialog()
            except Exception as e:
                try:
                    dialog.grab_release()
                except:
                    pass
                self.show_alert("Erro", f"Não foi possível salvar: {e}", "error", parent=self)
        # Botões GRANDES para tablet - más visibles
        btn_salvar = ttk.Button(
            btn_container, 
            text="💾  SALVAR  ", 
            bootstyle="success", 
            command=save_config,
            padding=(50, 18)
        )
        btn_salvar.pack(side=RIGHT, ipadx=20, ipady=5)
        
        btn_cancelar = ttk.Button(
            btn_container, 
            text="  CANCELAR  ", 
            bootstyle="secondary", 
            command=safe_close_dialog,
            padding=(50, 18)
        )
        btn_cancelar.pack(side=RIGHT, padx=25, ipadx=20, ipady=5)

        # Configurar protocolo de cierre
        dialog.protocol("WM_DELETE_WINDOW", safe_close_dialog)
        
        # Modal behavior
        dialog.transient(self)
        try:
            dialog.grab_set()
        except:
            pass
        self.wait_window(dialog)

    def _setup_calibration_tab(self, parent, current_config):
        """Configura la pestaña de calibración de sensores."""
        from modules.calibration import CalibrationManager, CalibrationPoint
        
        # Título - fuente grande para tablet
        ttk.Label(parent, text="Calibração de Celdas de Carga", 
                  font=("Segoe UI", 22, "bold")).pack(anchor="w", pady=(0, 15))
        
        # Descripción - fuente legible
        ttk.Label(parent, 
                  text="Esta ferramenta permite realizar ensaios de calibração com pesos padrão.\n"
                       "Os valores são salvos em CSV para análise posterior.",
                  font=("Segoe UI", 14), foreground="#64748b",
                  wraplength=900).pack(anchor="w", pady=(0, 20))
        
        # Frame de selección de sensor
        select_frame = ttk.Labelframe(parent, text="Selecionar Sensor", padding=20)
        select_frame.pack(fill=X, pady=(0, 15))
        
        # Combo de sensores - fuentes grandes
        sensor_names = list(current_config.get("nodes", {}).keys())
        self._cal_sensor_var = tk.StringVar(value=sensor_names[0] if sensor_names else "")
        
        ttk.Label(select_frame, text="Sensor a calibrar:", font=("Segoe UI", 18)).pack(side=LEFT, padx=(0, 15))
        sensor_combo = ttk.Combobox(select_frame, textvariable=self._cal_sensor_var,
                                     values=sensor_names, font=("Segoe UI", 18), 
                                     state="readonly", width=25)
        sensor_combo.pack(side=LEFT, ipady=8)
        
        # Botón para iniciar calibración - grande para tablet
        btn_start_cal = ttk.Button(select_frame, text="▶ INICIAR CALIBRAÇÃO",
                                    bootstyle="warning", padding=(25, 15),
                                    command=lambda: self._open_calibration_wizard(current_config))
        btn_start_cal.pack(side=RIGHT, padx=10)
        
        # Botón para cargar calibración existente - grande para tablet
        btn_load_cal = ttk.Button(select_frame, text="📂 CARREGAR SESSÃO",
                                   bootstyle="info", padding=(25, 15),
                                   command=self._load_calibration_session)
        btn_load_cal.pack(side=RIGHT, padx=10)
        
        # Frame de información sobre la calibración
        info_frame = ttk.Labelframe(parent, text="Informação de Calibração", padding=15)
        info_frame.pack(fill=BOTH, expand=YES, pady=10)
        
        info_text = """
    PROCEDIMENTO DE CALIBRAÇÃO:

1. Selecione o sensor que deseja calibrar
2. Clique em "INICIAR CALIBRAÇÃO"
3. Aplique os pesos padrão conforme indicado (0 a 200.000 kg)
4. Para cada peso, clique em "CAPTURAR" para gravar a leitura
5. Ao finalizar, o sistema calcula a curva de calibração
6. Exporte os dados para CSV para documentação

        """
        
        info_label = ttk.Label(info_frame, text=info_text, font=("Segoe UI", 12),
                               justify="left", wraplength=850)
        info_label.pack(anchor="w", fill=BOTH, expand=YES)
        
        # Lista de calibraciones guardadas
        saved_frame = ttk.Labelframe(parent, text="Sessões Salvas", padding=15)
        saved_frame.pack(fill=X, pady=10)
        
        self._cal_saved_list = ttk.Label(saved_frame, 
                                          text="Carregando lista de calibrações...",
                                          font=("Segoe UI", 11), foreground="#64748b")
        self._cal_saved_list.pack(anchor="w")
        
        # Cargar lista de sesiones guardadas
        self._refresh_saved_calibrations()
    
    def _refresh_saved_calibrations(self):
        """Actualiza la lista de calibraciones guardadas."""
        try:
            from modules.calibration import CalibrationManager
            from config import NODOS_CONFIG
            
            cal_manager = CalibrationManager(NODOS_CONFIG)
            sessions = cal_manager.list_saved_sessions()
            
            if sessions:
                text = "📁 Sessões encontradas:\n"
                for s in sessions[:5]:  # Mostrar máximo 5
                    text += f"   • {s['sensor_nombre']} - {s['fecha']} ({s['puntos']} pontos)\n"
                if len(sessions) > 5:
                    text += f"   ... e mais {len(sessions) - 5} sessões"
            else:
                text = "Nenhuma sessão de calibração salva"
            
            self._cal_saved_list.configure(text=text)
        except Exception as e:
            self._cal_saved_list.configure(text=f"Erro carregando sessões: {e}")
    
    def _load_calibration_session(self):
        """Abre diálogo para cargar una sesión de calibración."""
        from tkinter import filedialog
        import os
        
        cal_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibrations")
        
        # Crear directorio si no existe
        if not os.path.exists(cal_dir):
            os.makedirs(cal_dir, exist_ok=True)
        
        try:
            filepath = filedialog.askopenfilename(
                title="Selecionar Sessão de Calibração",
                initialdir=cal_dir,
                filetypes=[("JSON files", "*.json"), ("CSV files", "*.csv"), ("All files", "*.*")],
                parent=self
            )
            
            # Usuario canceló el diálogo
            if not filepath:
                return
            
            self.log_message(f"Carregando sessão: {filepath}")
            # TODO: Mostrar datos de la sesión cargada
            self.show_alert("Carregado", f"Sessão carregada:\n{os.path.basename(filepath)}", "success")
        except Exception as e:
            self.log_message(f"Erro ao carregar sessão: {e}")
    
    def _open_calibration_wizard(self, current_config):
        """Abre el wizard de calibración mejorado con gráfico en tiempo real."""
        sensor_name = self._cal_sensor_var.get()
        if not sensor_name:
            self.show_alert("Erro", "Selecione um sensor para calibrar", "error")
            return
        
        # Obtener ID del sensor
        sensor_config = current_config.get("nodes", {}).get(sensor_name, {})
        sensor_id = sensor_config.get("id", 0)
        
        if sensor_id == 0:
            self.show_alert("Erro", "Sensor não configurado corretamente", "error")
            return
        
        # Verificar matplotlib
        try:
            import matplotlib
            matplotlib.use('TkAgg')
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import numpy as np
        except ImportError:
            self.show_alert("Erro", "Matplotlib não instalado. Execute: pip install matplotlib", "error")
            return
        
        # Crear ventana del wizard
        wizard = ttk.Toplevel(self)
        wizard.overrideredirect(True)
        
        # Tamaño casi pantalla completa para tablet
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        wizard_w = screen_w - 40
        wizard_h = screen_h - 60
        x = 20
        y = 20
        wizard.geometry(f"{wizard_w}x{wizard_h}+{x}+{y}")
        
        wizard.lift()
        wizard.focus_force()
        
        # Guardar referencia al wizard
        self._cal_wizard = wizard
        self._cal_points = []  # Lista de puntos: [(peso_kg, mv_v), ...]
        
        # Función de cierre seguro
        def on_close():
            try:
                self._cal_wizard_active = False
                wizard.grab_release()
            except:
                pass
            try:
                wizard.destroy()
            except:
                pass
            self._cal_wizard = None
        
        # Borde
        border_frame = ttk.Frame(wizard, bootstyle="warning", padding=4)
        border_frame.pack(fill=BOTH, expand=YES)
        
        main_frame = ttk.Frame(border_frame, padding=15)
        main_frame.pack(fill=BOTH, expand=YES)
        
        # === HEADER ===
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill=X, pady=(0, 10))
        
        ttk.Label(title_frame, text=f"⚖ CALIBRAÇÃO: {sensor_name.upper()}", 
                  font=("Segoe UI", 24, "bold")).pack(side=LEFT)
        
        ttk.Button(title_frame, text="✕ FECHAR", bootstyle="danger",
                   command=on_close, padding=(20, 10)).pack(side=RIGHT)
        
        # === CONTENEDOR PRINCIPAL (2 columnas) ===
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=BOTH, expand=YES)
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=1)
        content_frame.rowconfigure(0, weight=1)
        
        # === COLUMNA IZQUIERDA: Lectura + Tabla + Acciones ===
        left_frame = ttk.Frame(content_frame)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        # Frame de lectura actual
        reading_frame = ttk.Labelframe(left_frame, text="📊 Leitura Atual", padding=15)
        reading_frame.pack(fill=X, pady=(0, 10))
        
        reading_container = ttk.Frame(reading_frame)
        reading_container.pack(fill=X)
        
        self._cal_current_mv = ttk.Label(reading_container, text="0.0000 mV/V", 
                                          font=("Consolas", 42, "bold"), foreground="#2563eb")
        self._cal_current_mv.pack(side=LEFT)
        
        self._cal_current_kg = ttk.Label(reading_container, text="(0.000 ton)", 
                                          font=("Segoe UI", 18), foreground="#64748b")
        self._cal_current_kg.pack(side=LEFT, padx=(20, 0))
        
        ttk.Button(reading_container, text="🔄", bootstyle="info-outline",
                   command=lambda: self._update_cal_reading(sensor_id),
                   padding=(12, 8)).pack(side=RIGHT)
        
        # Frame de acciones - entrada de peso
        action_frame = ttk.Labelframe(left_frame, text="➕ Adicionar Ponto", padding=15)
        action_frame.pack(fill=X, pady=(0, 10))
        
        input_row = ttk.Frame(action_frame)
        input_row.pack(fill=X, pady=(0, 10))
        
        ttk.Label(input_row, text="Peso real (kg):", font=("Segoe UI", 16)).pack(side=LEFT)
        self._cal_peso_entry = ttk.Entry(input_row, font=("Segoe UI", 18), width=12)
        self._cal_peso_entry.pack(side=LEFT, padx=10, ipady=8)
        
        ttk.Button(input_row, text="📥 CAPTURAR", bootstyle="success",
                   command=lambda: self._capture_cal_point_v2(sensor_id),
                   padding=(20, 12)).pack(side=LEFT, padx=5)
        
        ttk.Button(input_row, text="🗑 REMOVER", bootstyle="danger-outline",
                   command=self._remove_cal_point_v2,
                   padding=(15, 12)).pack(side=LEFT, padx=5)
        
        # Tabla de puntos capturados
        table_frame = ttk.Labelframe(left_frame, text="📋 Pontos de Calibração", padding=10)
        table_frame.pack(fill=BOTH, expand=YES, pady=(0, 10))
        
        columns = ("peso_real", "mv_v")
        self._cal_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        
        self._cal_tree.heading("peso_real", text="Peso Real (kg)")
        self._cal_tree.heading("mv_v", text="Leitura (mV/V)")
        
        self._cal_tree.column("peso_real", width=180, anchor="center")
        self._cal_tree.column("mv_v", width=180, anchor="center")
        
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self._cal_tree.yview)
        self._cal_tree.configure(yscrollcommand=scrollbar.set)
        
        self._cal_tree.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)
        
        # Botones de exportación
        export_frame = ttk.Frame(left_frame)
        export_frame.pack(fill=X)
        
        ttk.Button(export_frame, text="� EXPORTAR CSV", bootstyle="secondary",
                   command=self._export_calibration_csv_v2,
                   padding=(20, 12)).pack(side=LEFT, padx=5)
        
        ttk.Button(export_frame, text="� GUARDAR SESSÃO", bootstyle="success",
                   command=self._save_calibration_session_v2,
                   padding=(20, 12)).pack(side=LEFT, padx=5)
        
        # === COLUMNA DERECHA: Gráfico ===
        right_frame = ttk.Labelframe(content_frame, text="📈 Curva de Calibração", padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        
        # Crear figura de matplotlib con estilo moderno
        fig = Figure(figsize=(7, 6), dpi=100, facecolor='#f8fafc')
        self._cal_ax = fig.add_subplot(111)
        self._cal_ax.set_facecolor('#ffffff')
        self._cal_ax.set_xlabel('Peso Real (kg)', fontsize=12, fontweight='bold')
        self._cal_ax.set_ylabel('mV/V', fontsize=12, fontweight='bold')
        self._cal_ax.set_title('Curva de Calibração', fontsize=14, fontweight='bold', color='#1e293b')
        self._cal_ax.grid(True, linestyle='--', alpha=0.7)
        self._cal_ax.tick_params(labelsize=10)
        
        # Canvas de matplotlib en tkinter
        self._cal_canvas = FigureCanvasTkAgg(fig, master=right_frame)
        self._cal_canvas.draw()
        self._cal_canvas.get_tk_widget().pack(fill=BOTH, expand=YES)
        
        # Label de resultados debajo del gráfico
        self._cal_results_label = ttk.Label(right_frame, text="Adicione pontos para calcular a curva", 
                                             font=("Segoe UI", 12), foreground="#64748b")
        self._cal_results_label.pack(pady=(10, 0))
        
        # Iniciar calibration manager
        from modules.calibration import CalibrationManager
        from config import NODOS_CONFIG
        
        self._cal_manager = CalibrationManager(NODOS_CONFIG)
        self._cal_manager.start_session(sensor_id, sensor_name)
        
        # Iniciar actualización de lectura
        self._cal_wizard_active = True
        self._cal_sensor_id = sensor_id
        self._update_cal_reading_loop(wizard, sensor_id)
        
        wizard.protocol("WM_DELETE_WINDOW", on_close)
        wizard.transient(self)
    
    def _update_cal_reading(self, sensor_id):
        """Actualiza la lectura actual del sensor usando los últimos datos recibidos."""
        try:
            # Buscar sensor por ID en los últimos datos
            kg = 0.0
            for sensor_name, sensor_info in self._last_sensor_data.get('sensores', {}).items():
                if sensor_info.get('id') == sensor_id:
                    # El valor viene en toneladas, convertir a kg para consistencia
                    kg = sensor_info.get('raw', 0.0) * 1000  # raw está en toneladas
                    break
            
            ton = kg / 1000.0  # Volver a toneladas para mostrar
            
            # Calcular mV/V aproximado (sensibilidad típica 2 mV/V @ 50 ton)
            SENSIBILIDAD_MV_V = 2.0
            CARGA_NOMINAL_KG = 50000.0
            mv_v = (kg / CARGA_NOMINAL_KG) * SENSIBILIDAD_MV_V if kg != 0 else 0.0
            
            # Guardar valor mV/V actual para captura
            self._cal_current_mv_value = mv_v
            
            # Actualizar labels (mV/V prominente, ton secundario)
            self._cal_current_mv.configure(text=f"{mv_v:.4f} mV/V")
            self._cal_current_kg.configure(text=f"({ton:.3f} ton)")
        except Exception as e:
            self.log_message(f"Erro lendo sensor: {e}")
        except Exception as e:
            self.log_message(f"Erro lendo sensor: {e}")
    
    def _update_cal_reading_loop(self, wizard, sensor_id):
        """Loop de actualización de lectura del sensor."""
        if not self._cal_wizard_active:
            return
        
        try:
            if wizard.winfo_exists():
                self._update_cal_reading(sensor_id)
                wizard.after(500, lambda: self._update_cal_reading_loop(wizard, sensor_id))
        except:
            pass
    
    def _capture_cal_point(self, sensor_id):
        """Captura un punto de calibración usando la lectura actual."""
        # Función auxiliar para liberar grab antes de mostrar alertas
        def release_grab():
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
        
        try:
            peso_str = self._cal_peso_entry.get().strip().replace(",", "")
            if not peso_str:
                release_grab()
                self.show_alert("Erro", "Digite o peso aplicado", "error")
                return
            
            peso_kg = float(peso_str)
            
            # Obtener lectura actual directamente de los datos almacenados
            valor_sensor_kg = 0.0
            for sensor_name, sensor_info in self._last_sensor_data.get('sensores', {}).items():
                if sensor_info.get('id') == sensor_id:
                    # El valor 'raw' viene en toneladas desde el procesador
                    valor_sensor_kg = sensor_info.get('raw', 0.0) * 1000  # Convertir a kg
                    break
            
            if valor_sensor_kg == 0.0:
                release_grab()
                self.show_alert("Aviso", "Sem leitura do sensor. Verifique a conexão.", "info")
                return
            
            # Calcular mV/V aproximado
            SENSIBILIDAD_MV_V = 2.0
            CARGA_NOMINAL_KG = 50000.0
            mv_v = (valor_sensor_kg / CARGA_NOMINAL_KG) * SENSIBILIDAD_MV_V
            
            # Agregar punto manualmente
            from modules.calibration import CalibrationPoint
            from datetime import datetime
            
            point = CalibrationPoint(
                peso_aplicado_kg=peso_kg,
                valor_sensor_kg=valor_sensor_kg,
                valor_crudo_mv_v=mv_v,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Agregar a la sesión del manager
            if self._cal_manager.current_session:
                self._cal_manager.current_session.puntos.append(point)
            
            # Agregar a la tabla
            self._cal_tree.insert("", "end", values=(
                f"{point.peso_aplicado_kg:,.0f}",
                f"{point.valor_sensor_kg/1000:.3f}",  # Mostrar en toneladas
                f"{point.valor_crudo_mv_v:.4f}",
                f"{point.std_dev:.3f}",
                point.timestamp.split(" ")[1] if " " in point.timestamp else point.timestamp
            ))
            
            self.log_message(f"Ponto capturado: {peso_kg} kg → {valor_sensor_kg:.1f} kg lido")
            self._cal_peso_entry.delete(0, END)
                
        except ValueError:
            release_grab()
            self.show_alert("Erro", "Peso inválido. Use apenas números.", "error")
        except Exception as e:
            release_grab()
            self.show_alert("Erro", f"Erro ao capturar: {e}", "error")
    
    def _remove_cal_point(self):
        """Elimina el punto seleccionado de la tabla."""
        selected = self._cal_tree.selection()
        if selected:
            for item in selected:
                idx = self._cal_tree.index(item)
                self._cal_tree.delete(item)
                if hasattr(self, '_cal_manager') and self._cal_manager:
                    self._cal_manager.remove_point(idx)
            self.log_message("Ponto removido")
        else:
            # Liberar grab para mostrar alerta
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
            self.show_alert("Info", "Selecione um ponto para remover", "info")
    
    def _calculate_calibration_curve(self):
        """Calcula la curva de calibración."""
        if not hasattr(self, '_cal_manager') or not self._cal_manager.current_session or len(self._cal_manager.current_session.puntos) < 2:
            # Liberar grab para mostrar alerta
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
            self.show_alert("Erro", "Precisa de pelo menos 2 pontos para calcular", "error")
            return
        
        # Calcular regresiones
        slope, offset, r2 = self._cal_manager.calculate_linear_regression()
        
        # Detectar no-linealidad
        analysis = self._cal_manager.detect_nonlinearity()
        
        result_text = f"📊 Slope: {slope:.6f} | Offset: {offset:.1f} | R²: {r2:.6f}"
        
        if analysis.get("needs_polynomial"):
            poly_coeffs, poly_r2 = self._cal_manager.calculate_polynomial_regression(degree=2)
            result_text += f"\n⚠️ Detectada não-linearidade ({analysis['upper_third_avg_error']:.2f}% erro no extremo)"
            result_text += f"\n📈 Polinómio grau 2: R²={poly_r2:.6f}"
        
        self._cal_results_label.configure(text=result_text)
        self.log_message(f"Curva calculada: R²={r2:.6f}")
        
        # Liberar grab para mostrar diálogo con resultados
        if hasattr(self, '_cal_wizard') and self._cal_wizard:
            try:
                self._cal_wizard.grab_release()
            except:
                pass
        
        self.show_alert("Calibração Calculada", 
                        f"Resultados da calibração:\n\n"
                        f"Slope: {slope:.6f}\n"
                        f"Offset: {offset:.1f} kg\n"
                        f"R²: {r2:.6f}\n\n"
                        f"{'⚠️ Recomenda-se correção polinómica' if analysis.get('needs_polynomial') else '✅ Linearidade OK'}",
                        "success" if not analysis.get("needs_polynomial") else "info")
    
    def _export_calibration_csv(self):
        """Exporta la calibración a CSV."""
        if not hasattr(self, '_cal_manager') or not self._cal_manager.current_session:
            self.show_alert("Erro", "Não há sessão ativa para exportar", "error")
            return
        
        try:
            # Liberar grab temporalmente para permitir diálogos
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
            
            self._cal_manager.finish_session()
            filepath = self._cal_manager.export_to_csv()
            self.log_message(f"CSV exportado: {filepath}")
            self.show_alert("Exportado", f"Arquivo salvo:\n{filepath}", "success")
        except Exception as e:
            self.show_alert("Erro", f"Erro ao exportar: {e}", "error")
    
    def _save_calibration_session(self):
        """Guarda la sesión de calibración."""
        if not hasattr(self, '_cal_manager') or not self._cal_manager.current_session:
            self.show_alert("Erro", "Não há sessão ativa para guardar", "error")
            return
        
        try:
            # Liberar grab temporalmente para permitir diálogos
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
            
            self._cal_manager.finish_session()
            filepath = self._cal_manager.save_session()
            self.log_message(f"Sessão salva: {filepath}")
            self.show_alert("Salvo", f"Sessão guardada:\n{filepath}", "success")
            self._refresh_saved_calibrations()
        except Exception as e:
            self.show_alert("Erro", f"Erro ao guardar: {e}", "error")

    # ==================== NUEVAS FUNCIONES V2 PARA CALIBRACIÓN ====================
    
    def _capture_cal_point_v2(self, sensor_id):
        """Captura un punto de calibración y actualiza el gráfico en tiempo real."""
        def release_grab():
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
        
        try:
            peso_str = self._cal_peso_entry.get().strip().replace(",", "").replace(".", "")
            if not peso_str:
                release_grab()
                self.show_alert("Erro", "Digite o peso real aplicado", "error")
                return
            
            peso_kg = float(peso_str)
            
            # Obtener valor mV/V actual
            mv_v = getattr(self, '_cal_current_mv_value', 0.0)
            
            if mv_v == 0.0:
                release_grab()
                self.show_alert("Aviso", "Sem leitura do sensor. Verifique a conexão.", "info")
                return
            
            # Agregar punto a la lista
            self._cal_points.append((peso_kg, mv_v))
            
            # Agregar a la tabla
            self._cal_tree.insert("", "end", values=(
                f"{peso_kg:,.0f}",
                f"{mv_v:.4f}"
            ))
            
            # Agregar al manager también
            from modules.calibration import CalibrationPoint
            from datetime import datetime
            
            point = CalibrationPoint(
                peso_aplicado_kg=peso_kg,
                valor_crudo_mv_v=mv_v,
                valor_sensor_kg=peso_kg,  # Usamos el peso real
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            if self._cal_manager.current_session:
                self._cal_manager.current_session.puntos.append(point)
            
            self.log_message(f"Ponto capturado: {peso_kg:.0f} kg → {mv_v:.4f} mV/V")
            self._cal_peso_entry.delete(0, END)
            
            # Actualizar gráfico
            self._update_cal_graph()
                
        except ValueError:
            release_grab()
            self.show_alert("Erro", "Peso inválido. Use apenas números.", "error")
        except Exception as e:
            release_grab()
            self.show_alert("Erro", f"Erro ao capturar: {e}", "error")
    
    def _remove_cal_point_v2(self):
        """Elimina el punto seleccionado y actualiza el gráfico."""
        selected = self._cal_tree.selection()
        if selected:
            for item in selected:
                idx = self._cal_tree.index(item)
                self._cal_tree.delete(item)
                
                # Eliminar de la lista de puntos
                if 0 <= idx < len(self._cal_points):
                    self._cal_points.pop(idx)
                
                # Eliminar del manager
                if hasattr(self, '_cal_manager') and self._cal_manager:
                    self._cal_manager.remove_point(idx)
            
            self.log_message("Ponto removido")
            self._update_cal_graph()
        else:
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
            self.show_alert("Info", "Selecione um ponto para remover", "info")
    
    def _update_cal_graph(self):
        """Actualiza el gráfico de calibración con los puntos actuales."""
        try:
            import numpy as np
            
            # Limpiar el gráfico
            self._cal_ax.clear()
            self._cal_ax.set_xlabel('Peso Real (kg)', fontsize=12, fontweight='bold')
            self._cal_ax.set_ylabel('mV/V', fontsize=12, fontweight='bold')
            self._cal_ax.set_title('Curva de Calibração', fontsize=14, fontweight='bold', color='#1e293b')
            self._cal_ax.grid(True, linestyle='--', alpha=0.7)
            self._cal_ax.set_facecolor('#ffffff')
            
            if not self._cal_points:
                self._cal_results_label.configure(text="Adicione pontos para calcular a curva")
                self._cal_canvas.draw()
                return
            
            # Extraer datos
            pesos = np.array([p[0] for p in self._cal_points])
            mvs = np.array([p[1] for p in self._cal_points])
            
            # Dibujar puntos
            self._cal_ax.scatter(pesos, mvs, s=120, c='#2563eb', marker='o', 
                                  label='Pontos medidos', zorder=5, edgecolors='white', linewidth=2)
            
            # Si hay al menos 2 puntos, calcular y dibujar la curva
            if len(self._cal_points) >= 2:
                # Regresión lineal
                slope, intercept = np.polyfit(pesos, mvs, 1)
                
                # Calcular R²
                y_pred = slope * pesos + intercept
                ss_res = np.sum((mvs - y_pred) ** 2)
                ss_tot = np.sum((mvs - np.mean(mvs)) ** 2)
                r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
                
                # Línea de regresión
                x_line = np.linspace(min(pesos) * 0.9, max(pesos) * 1.1, 100)
                y_line = slope * x_line + intercept
                
                self._cal_ax.plot(x_line, y_line, 'r-', linewidth=2, 
                                   label=f'Linear: y = {slope:.6f}x + {intercept:.4f}', alpha=0.8)
                
                # Si hay 3+ puntos, intentar ajuste polinómico
                if len(self._cal_points) >= 3:
                    try:
                        poly_coeffs = np.polyfit(pesos, mvs, 2)
                        y_poly = np.polyval(poly_coeffs, x_line)
                        
                        # R² del polinomio
                        y_pred_poly = np.polyval(poly_coeffs, pesos)
                        ss_res_poly = np.sum((mvs - y_pred_poly) ** 2)
                        r2_poly = 1 - (ss_res_poly / ss_tot) if ss_tot > 0 else 0
                        
                        if r2_poly > r2 + 0.001:  # Solo mostrar si mejora significativamente
                            self._cal_ax.plot(x_line, y_poly, 'g--', linewidth=2, 
                                               label=f'Polinómio (R²={r2_poly:.4f})', alpha=0.7)
                    except:
                        pass
                
                # Actualizar label de resultados
                self._cal_results_label.configure(
                    text=f"📊 Slope: {slope:.6f} mV/V/kg | Offset: {intercept:.4f} mV/V | R²: {r2:.4f}"
                )
            else:
                self._cal_results_label.configure(text="Adicione mais pontos para calcular a curva")
            
            # Leyenda
            self._cal_ax.legend(loc='upper left', fontsize=10)
            
            # Ajustar límites
            if len(pesos) > 0:
                x_margin = (max(pesos) - min(pesos)) * 0.1 if max(pesos) != min(pesos) else 1000
                y_margin = (max(mvs) - min(mvs)) * 0.1 if max(mvs) != min(mvs) else 0.1
                self._cal_ax.set_xlim(min(pesos) - x_margin, max(pesos) + x_margin)
                self._cal_ax.set_ylim(min(mvs) - y_margin, max(mvs) + y_margin)
            
            # Redibujar
            self._cal_canvas.draw()
            
        except Exception as e:
            self.log_message(f"Erro ao atualizar gráfico: {e}")
    
    def _export_calibration_csv_v2(self):
        """Exporta la calibración a CSV (versión simplificada)."""
        if not self._cal_points:
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
            self.show_alert("Erro", "Não há pontos para exportar", "error")
            return
        
        try:
            # Liberar grab para el diálogo de archivo
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
            
            from tkinter import filedialog
            from datetime import datetime
            import os
            
            # Directorio de calibraciones
            cal_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibrations")
            os.makedirs(cal_dir, exist_ok=True)
            
            # Nombre por defecto
            sensor_name = self._cal_sensor_var.get() if hasattr(self, '_cal_sensor_var') else "sensor"
            default_name = f"calibracao_{sensor_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            filepath = filedialog.asksaveasfilename(
                title="Exportar Calibração CSV",
                initialdir=cal_dir,
                initialfile=default_name,
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                parent=self._cal_wizard if self._cal_wizard else self
            )
            
            if not filepath:
                return
            
            # Escribir CSV
            import csv
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Peso Real (kg)", "mV/V"])
                for peso, mv in self._cal_points:
                    writer.writerow([peso, f"{mv:.6f}"])
            
            self.log_message(f"CSV exportado: {filepath}")
            self.show_alert("Exportado", f"Arquivo salvo:\n{os.path.basename(filepath)}", "success")
            
        except Exception as e:
            self.show_alert("Erro", f"Erro ao exportar: {e}", "error")
    
    def _save_calibration_session_v2(self):
        """Guarda la sesión de calibración completa."""
        if not self._cal_points:
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
            self.show_alert("Erro", "Não há pontos para guardar", "error")
            return
        
        try:
            # Liberar grab para diálogos
            if hasattr(self, '_cal_wizard') and self._cal_wizard:
                try:
                    self._cal_wizard.grab_release()
                except:
                    pass
            
            if hasattr(self, '_cal_manager') and self._cal_manager.current_session:
                self._cal_manager.finish_session()
                filepath = self._cal_manager.save_session()
                self.log_message(f"Sessão salva: {filepath}")
                import os
                self.show_alert("Salvo", f"Sessão guardada:\n{os.path.basename(filepath)}", "success")
                self._refresh_saved_calibrations()
            else:
                self.show_alert("Erro", "Sessão não inicializada", "error")
                
        except Exception as e:
            self.show_alert("Erro", f"Erro ao guardar: {e}", "error")
