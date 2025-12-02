import queue
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
        
        # Configure Label styles - MÁS GRANDES para mejor visibilidad
        self.style.configure('CardTitle.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 16, "bold"))
        self.style.configure('CardValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MONO, 48, "bold"))
        self.style.configure('Unit.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 18))
        self.style.configure('SensorStatus.TLabel', background=BG_CARD, foreground=SUCCESS, font=(FONT_MAIN, 13, "bold"))
        
        # Total Panel - MUY PROMINENTE para énfasis máximo
        self.style.configure('TotalPanel.TFrame', background=PRIMARY)
        self.style.configure('TotalLabel.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, 28, "bold"))
        self.style.configure('TotalValue.TLabel', background=PRIMARY, foreground="white", font=(FONT_MONO, 140, "bold"))
        self.style.configure('TotalUnit.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, 32))
        
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
                text="toneladas", 
                font=('Segoe UI', 15), 
                foreground="#64748b",
                background="#ffffff"
            ).pack(pady=(5, 0))
            
            self.sensor_widgets[key] = {
                'value': value_lbl,
                'rssi': rssi_lbl,
                'status': status_lbl
            }

        # Crear sensores en posiciones: izquierda y derecha (SENSOR en vez de CÉLULA)
        keys = list(NODOS_CONFIG.keys())
        if len(keys) >= 4:
            create_sensor_card(keys[0], "SENSOR SUP. ESQUERDO", 0, 0)
            create_sensor_card(keys[1], "SENSOR SUP. DIREITO", 0, 2)
            create_sensor_card(keys[2], "SENSOR INF. ESQUERDO", 1, 0)
            create_sensor_card(keys[3], "SENSOR INF. DIREITO", 1, 2)

        # --- PANEL CENTRAL: TOTAL (MÁS GRANDE) ---
        control_panel = ttk.Frame(grid_area, style='Card.TFrame', padding=15)
        control_panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=8)
        control_panel.grid_propagate(False)  # Tamaño fijo
        
        # Sección TOTAL con fondo azul - MUY GRANDE Y PROMINENTE
        total_section = ttk.Frame(control_panel, style='TotalPanel.TFrame', padding=35)
        total_section.pack(fill=BOTH, expand=YES)
        
        ttk.Label(total_section, text="PESO TOTAL", style='TotalLabel.TLabel', anchor="center").pack(fill=X)
        self.lbl_total = ttk.Label(
            total_section, 
            text="0.00", 
            style='TotalValue.TLabel', 
            anchor="center",
            width=10  # Ancho fijo para evitar cambios
        )
        self.lbl_total.pack(fill=X, pady=20)
        ttk.Label(total_section, text="toneladas", style='TotalUnit.TLabel', anchor="center").pack()
        
        # Separador dentro del panel
        ttk.Separator(control_panel, orient=HORIZONTAL).pack(fill=X, pady=15)
        
        # Sección de Acciones debajo del total
        actions_section = ttk.Frame(control_panel, style='CardNoBorder.TFrame', padding=10)
        actions_section.pack(fill=X)
        
        # Info de Tara - MÁS GRANDE Y VISIBLE
        self.lbl_tare_info = ttk.Label(
            actions_section, 
            text="Tara Acumulada: 0.00 t", 
            style='TareInfo.TLabel',
            anchor="center"
        )
        self.lbl_tare_info.pack(pady=(0, 20))
        
        # Frame para botones lado a lado
        btn_row = ttk.Frame(actions_section, style='CardNoBorder.TFrame')
        btn_row.pack(fill=X)
        
        # Botón TARA - Grande y prominente
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
        
        # Botón Reset Tara - MISMO TAMAÑO que TARA
        btn_reset = ttk.Button(
            btn_row, 
            text="RESET TARA", 
            command=self.reset_tare, 
            bootstyle="secondary", 
            style='Tare.TButton',  # Mismo estilo que TARA
            width=12, 
            padding=(25, 18)  # Mismo padding que TARA
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
                    self._update_display(data)
                elif msg['type'] == 'STATUS':
                    self._update_status(msg['payload'])
                elif msg['type'] == 'ERROR':
                    self.show_alert("Erro", msg['payload'], "error")
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
        """Mostra um diálogo modal personalizado SEM barra de título, com fontes e botões grandes."""
        result = {'value': False}
        
        # Criar janela secundária SIN BARRA DE TÍTULO
        dialog = ttk.Toplevel(self)
        dialog.overrideredirect(True)  # Quitar barra de Windows
        dialog.geometry("550x320")
        
        # Centralizar em relação à janela principal
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 275
            y = self.winfo_y() + (self.winfo_height() // 2) - 160
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
        
        def on_yes():
            result['value'] = True
            dialog.destroy()
            
        def on_no():
            dialog.destroy()
            
        btn_yes = ttk.Button(btn_frame, text="SIM", style="Large.success.TButton", width=14, 
                             command=on_yes, padding=(20, 15))
        btn_yes.pack(side=LEFT, padx=20, expand=YES)
        
        btn_no = ttk.Button(btn_frame, text="NÃO", style="Large.danger.TButton", width=14, 
                            command=on_no, padding=(20, 15))
        btn_no.pack(side=RIGHT, padx=20, expand=YES)

        dialog.transient(self)
        # Usar after para grab_set (evita conflicto con overrideredirect)
        dialog.after(10, lambda: dialog.grab_set())
        self.wait_window(dialog)
        
        return result['value']

    def show_alert(self, title, message, alert_type="info", parent=None):
        """Mostra um alerta SEM barra de título, com estilo grande."""
        target = parent or self
        
        # Criar janela SIN BARRA DE TÍTULO
        dialog = ttk.Toplevel(target)
        dialog.overrideredirect(True)
        dialog.geometry("500x250")
        
        # Centralizar
        try:
            x = target.winfo_x() + (target.winfo_width() // 2) - 250
            y = target.winfo_y() + (target.winfo_height() // 2) - 125
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
        
        # Botón OK
        btn_ok = ttk.Button(frame, text="OK", bootstyle=bootstyle, width=12,
                            command=dialog.destroy, padding=(20, 12))
        btn_ok.pack()
        
        dialog.transient(target)
        dialog.after(10, lambda: dialog.grab_set())
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
        """Abre um diálogo para configurar conexão, modo e nós."""
        import json
        import os
        
        # Verificar disponibilidade do MSCL
        try:
            from modules.factory import check_mscl_installation, get_available_modes
            mscl_info = check_mscl_installation()
            available_modes = get_available_modes()
        except:
            mscl_info = {"installed": False}
            available_modes = {"MOCK": {"available": True}, "MSCL_MOCK": {"available": False}, "REAL": {"available": False}}
        
        # Carregar configuração atual ou usar defaults
        # Usar caminho absoluto para garantir que funcione de qualquer diretório
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "settings.json")
        current_config = {
            "execution_mode": "MOCK",
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

        # Criar janela modal - SIN BARRA DE TÍTULO (frameless)
        dialog = ttk.Toplevel(self)
        dialog.overrideredirect(True)  # Quitar barra de Windows
        
        # Tamaño adaptativo según pantalla
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        dialog_w = min(1000, screen_w - 100)
        dialog_h = min(850, screen_h - 100)
        
        # Centrar en pantalla
        x = (screen_w - dialog_w) // 2
        y = (screen_h - dialog_h) // 2
        dialog.geometry(f"{dialog_w}x{dialog_h}+{x}+{y}")
        
        # Forzar que aparezca arriba
        dialog.lift()
        dialog.focus_force()

        # Estilos personalizados para abas MUY GRANDES (touch-friendly)
        style = ttk.Style()
        style.configure('BigTab.TNotebook.Tab', 
                        font=('Segoe UI', 22, 'bold'), 
                        padding=(50, 25))  # Muy grande para tocar con el dedo
        style.configure('BigRadio.TRadiobutton', font=('Segoe UI', 14))

        # === BORDE FUERTE para delimitar la ventana ===
        border_frame = ttk.Frame(dialog, bootstyle="dark", padding=4)
        border_frame.pack(fill=BOTH, expand=YES)
        
        # Container principal con título propio (dentro del borde)
        main_frame = ttk.Frame(border_frame, padding=20)
        main_frame.pack(fill=BOTH, expand=YES)
        
        # Título personalizado (reemplaza la barra de Windows)
        title_frame = ttk.Frame(main_frame, style='Header.TFrame', padding=10)
        title_frame.pack(fill=X, pady=(0, 15))
        
        ttk.Label(title_frame, text="⚙  CONFIGURAÇÃO DO SISTEMA", 
                  font=("Segoe UI", 20, "bold"), 
                  foreground="#1e293b", 
                  background="#ffffff").pack(side=LEFT)
        
        # Botón X para cerrar - MÁS GRANDE
        btn_close = ttk.Button(title_frame, text="✕ FECHAR", 
                               bootstyle="danger", 
                               command=dialog.destroy,
                               width=10,
                               padding=(15, 10))
        btn_close.pack(side=RIGHT)

        # --- Contenedor con SCROLL ---
        from ttkbootstrap.scrolled import ScrolledFrame
        scroll_container = ScrolledFrame(main_frame, autohide=True)
        scroll_container.pack(fill=BOTH, expand=YES)
        
        # --- Abas com estilo grande (dentro del scroll) ---
        notebook = ttk.Notebook(scroll_container, style='BigTab.TNotebook')
        notebook.pack(fill=BOTH, expand=YES)
        
        # ==================== Tab MODO ====================
        tab_mode = ttk.Frame(notebook, padding=30)
        notebook.add(tab_mode, text="   🔧 MODO   ")
        
        ttk.Label(tab_mode, text="Modo de Execução", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 20))
        
        # Info sobre MSCL
        mscl_frame = ttk.Labelframe(tab_mode, text="Status da Biblioteca MSCL", padding=20)
        mscl_frame.pack(fill=X, pady=(0, 25))
        
        if mscl_info["installed"]:
            mscl_status = "✅ MSCL Instalado e Disponível"
            mscl_color = "#22c55e"
        else:
            mscl_status = "❌ MSCL Não Encontrado (modos REAL e MSCL_MOCK indisponíveis)"
            mscl_color = "#ef4444"
        
        ttk.Label(mscl_frame, text=mscl_status, font=("Segoe UI", 14), foreground=mscl_color).pack(anchor="w")
        
        # Selector de modo
        mode_var = tk.StringVar(value=current_config.get("execution_mode", "MOCK"))
        
        modes_frame = ttk.Frame(tab_mode)
        modes_frame.pack(fill=X, pady=15)
        
        # MOCK Mode
        mode_mock_frame = ttk.Labelframe(modes_frame, text="", padding=20)
        mode_mock_frame.pack(fill=X, pady=10)
        
        rb_mock = ttk.Radiobutton(
            mode_mock_frame,
            text="   MOCK - Simulação Simples",
            variable=mode_var,
            value="MOCK",
            style='BigRadio.TRadiobutton'
        )
        rb_mock.pack(anchor="w", ipady=8)
        ttk.Label(
            mode_mock_frame, 
            text="     Simulação básica para desenvolvimento. Não requer hardware nem MSCL.",
            font=("Segoe UI", 11),
            foreground="#64748b"
        ).pack(anchor="w", padx=(30, 0))
        
        # MSCL_MOCK Mode
        mode_mscl_mock_frame = ttk.Labelframe(modes_frame, text="", padding=20)
        mode_mscl_mock_frame.pack(fill=X, pady=10)
        
        rb_mscl_mock = ttk.Radiobutton(
            mode_mscl_mock_frame,
            text="   MSCL_MOCK - Simulação com Estruturas MSCL",
            variable=mode_var,
            value="MSCL_MOCK",
            style='BigRadio.TRadiobutton',
            state="normal" if available_modes.get("MSCL_MOCK", {}).get("available", False) else "disabled"
        )
        rb_mscl_mock.pack(anchor="w", ipady=8)
        ttk.Label(
            mode_mscl_mock_frame, 
            text="     Teste de integração usando estruturas MSCL simuladas. Requer biblioteca MSCL.",
            font=("Segoe UI", 11),
            foreground="#64748b"
        ).pack(anchor="w", padx=(30, 0))
        
        # REAL Mode
        mode_real_frame = ttk.Labelframe(modes_frame, text="", padding=20)
        mode_real_frame.pack(fill=X, pady=10)
        
        rb_real = ttk.Radiobutton(
            mode_real_frame,
            text="   REAL - Hardware MicroStrain",
            variable=mode_var,
            value="REAL",
            style='BigRadio.TRadiobutton',
            state="normal" if available_modes.get("REAL", {}).get("available", False) else "disabled"
        )
        rb_real.pack(anchor="w", ipady=8)
        ttk.Label(
            mode_real_frame, 
            text="     Conexão real com BaseStation e nós SG-Link. Requer hardware e MSCL.",
            font=("Segoe UI", 11),
            foreground="#64748b"
        ).pack(anchor="w", padx=(30, 0))

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
        
        # === MATRIZ 2x2 VISUAL para indicar posición de sensores ===
        ttk.Label(tab_nodes, text="Disposição dos Sensores (vista superior):", font=("Segoe UI", 14)).pack(anchor="w", pady=(10, 15))
        
        # Contenedor de la matriz visual
        matrix_frame = ttk.Frame(tab_nodes)
        matrix_frame.pack(fill=BOTH, expand=YES, padx=20)
        
        # Configurar grid 2x2
        matrix_frame.columnconfigure(0, weight=1)
        matrix_frame.columnconfigure(1, weight=1)
        matrix_frame.rowconfigure(0, weight=1)
        matrix_frame.rowconfigure(1, weight=1)
        
        # Función para crear cada celda del sensor
        def create_sensor_config_cell(key, label_short, row, col):
            cell_frame = ttk.Labelframe(matrix_frame, text=label_short, padding=15)
            cell_frame.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
            
            current_node_data = current_config["nodes"].get(key, {"id": 0, "ch": "ch1"})
            
            # Node ID
            id_frame = ttk.Frame(cell_frame)
            id_frame.pack(fill=X, pady=5)
            ttk.Label(id_frame, text="Node ID:", font=("Segoe UI", 12)).pack(side=LEFT)
            e_id = ttk.Entry(id_frame, font=("Segoe UI", 14), width=10)
            e_id.insert(0, str(current_node_data["id"]))
            e_id.pack(side=RIGHT, ipady=6)
            
            # Channel
            ch_frame = ttk.Frame(cell_frame)
            ch_frame.pack(fill=X, pady=5)
            ttk.Label(ch_frame, text="Canal:", font=("Segoe UI", 12)).pack(side=LEFT)
            e_ch = ttk.Entry(ch_frame, font=("Segoe UI", 14), width=10)
            e_ch.insert(0, str(current_node_data["ch"]))
            e_ch.pack(side=RIGHT, ipady=6)
            
            node_entries[key] = {"id": e_id, "ch": e_ch}
        
        # Crear matriz 2x2 con posiciones claras (SENSOR en vez de célula)
        create_sensor_config_cell("celda_sup_izq", "⬉ SENSOR SUP. ESQ.", 0, 0)
        create_sensor_config_cell("celda_sup_der", "⬈ SENSOR SUP. DIR.", 0, 1)
        create_sensor_config_cell("celda_inf_izq", "⬋ SENSOR INF. ESQ.", 1, 0)
        create_sensor_config_cell("celda_inf_der", "⬊ SENSOR INF. DIR.", 1, 1)
        
        # Indicador visual de la balanza
        ttk.Label(tab_nodes, text="↑ Frente da balança ↑", font=("Segoe UI", 11, "italic"), foreground="#64748b").pack(pady=(15, 5))

        # ==================== Tab TESTES (Solo en modo MOCK) ====================
        tab_tests = ttk.Frame(notebook, padding=30)
        notebook.add(tab_tests, text="   🧪 TESTES   ")
        
        ttk.Label(tab_tests, text="Simulação de Cenários", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 15))
        
        ttk.Label(tab_tests, 
                  text="Use estes controles para simular falhas e condições de teste.\nDisponível apenas em modo MOCK/MSCL_MOCK.",
                  font=("Segoe UI", 12), foreground="#64748b").pack(anchor="w", pady=(0, 20))
        
        # Frame para escenarios de fallo
        fail_frame = ttk.Labelframe(tab_tests, text="Falhas de Sensores", padding=20)
        fail_frame.pack(fill=X, pady=(0, 15))
        
        # Botones para cada sensor (grid 2x2)
        sensor_btns_frame = ttk.Frame(fail_frame)
        sensor_btns_frame.pack(fill=X)
        sensor_btns_frame.columnconfigure(0, weight=1)
        sensor_btns_frame.columnconfigure(1, weight=1)
        
        self._test_sensor_states = {key: tk.BooleanVar(value=False) for key in NODOS_CONFIG.keys()}
        
        def toggle_sensor_offline(key):
            is_offline = self._test_sensor_states[key].get()
            node_id = NODOS_CONFIG[key]['id']
            if is_offline:
                self.command_queue.put({'cmd': 'TEST_SENSOR_OFFLINE', 'node_id': node_id})
            else:
                self.command_queue.put({'cmd': 'TEST_SENSOR_ONLINE', 'node_id': node_id})
        
        sensor_labels = {
            "celda_sup_izq": "Sensor Sup. Esq.",
            "celda_sup_der": "Sensor Sup. Dir.",
            "celda_inf_izq": "Sensor Inf. Esq.",
            "celda_inf_der": "Sensor Inf. Dir."
        }
        
        positions = [("celda_sup_izq", 0, 0), ("celda_sup_der", 0, 1), 
                     ("celda_inf_izq", 1, 0), ("celda_inf_der", 1, 1)]
        
        for key, row, col in positions:
            btn = ttk.Checkbutton(
                sensor_btns_frame,
                text=f"❌ {sensor_labels[key]} Offline",
                variable=self._test_sensor_states[key],
                command=lambda k=key: toggle_sensor_offline(k),
                bootstyle="danger-outline-toolbutton",
                width=25,
                padding=(15, 12)
            )
            btn.grid(row=row, column=col, padx=10, pady=8, sticky="ew")
        
        # Frame para escenarios de carga
        load_frame = ttk.Labelframe(tab_tests, text="Simulação de Carga", padding=20)
        load_frame.pack(fill=X, pady=(0, 15))
        
        load_btns = ttk.Frame(load_frame)
        load_btns.pack(fill=X)
        
        def send_test_command(cmd, **kwargs):
            self.command_queue.put({'cmd': cmd, **kwargs})
        
        ttk.Button(load_btns, text="📈 Rampa +50t", bootstyle="info", padding=(20, 12),
                   command=lambda: send_test_command('TEST_RAMP_UP', weight=50.0)).pack(side=LEFT, padx=5)
        
        ttk.Button(load_btns, text="📉 Descarga", bootstyle="info-outline", padding=(20, 12),
                   command=lambda: send_test_command('TEST_RAMP_DOWN')).pack(side=LEFT, padx=5)
        
        ttk.Button(load_btns, text="💥 Impacto 10t", bootstyle="warning", padding=(20, 12),
                   command=lambda: send_test_command('TEST_SPIKE', magnitude=10.0)).pack(side=LEFT, padx=5)
        
        ttk.Button(load_btns, text="⚡ Alto Ruído", bootstyle="warning-outline", padding=(20, 12),
                   command=lambda: send_test_command('TEST_NOISE')).pack(side=LEFT, padx=5)
        
        # Frame para control
        ctrl_frame = ttk.Labelframe(tab_tests, text="Controle", padding=20)
        ctrl_frame.pack(fill=X, pady=(0, 15))
        
        ctrl_btns = ttk.Frame(ctrl_frame)
        ctrl_btns.pack(fill=X)
        
        def reset_all_tests():
            for key in self._test_sensor_states:
                self._test_sensor_states[key].set(False)
            send_test_command('TEST_RESET_ALL')
        
        ttk.Button(ctrl_btns, text="🔄 Reset Todos os Testes", bootstyle="success", padding=(25, 15),
                   command=reset_all_tests).pack(side=LEFT, padx=5)
        
        # Status de escenarios activos
        self._test_status_var = tk.StringVar(value="Nenhum cenário ativo")
        ttk.Label(ctrl_btns, textvariable=self._test_status_var, 
                  font=("Segoe UI", 11), foreground="#64748b").pack(side=LEFT, padx=20)

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
                "execution_mode": mode_var.get(),
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
                
                self.show_alert("Salvo", "Configuração salva.\nReinicie a aplicação para aplicar as alterações.", "success", parent=dialog)
                dialog.destroy()
            except Exception as e:
                self.show_alert("Erro", f"Não foi possível salvar: {e}", "error", parent=dialog)

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
            command=dialog.destroy,
            padding=(50, 18)
        )
        btn_cancelar.pack(side=RIGHT, padx=25, ipadx=20, ipady=5)

        # Modal behavior - usar after para evitar conflictos con overrideredirect
        dialog.transient(self)
        dialog.after(10, lambda: dialog.grab_set())
        self.wait_window(dialog)
