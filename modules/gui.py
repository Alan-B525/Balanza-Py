from config import APP_TITLE, APP_SIZE, THEME_NAME, NODOS_CONFIG
import os
import json
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox, filedialog
try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None
import queue
import time
import shutil

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
    # Mensaje de advertencia eliminado (solo log si es necesario)


BASE_WIDTH = 1280
BASE_HEIGHT = 800

class BalanzaGUI(ttk.Window):
    def _load_calibration_session(self, parent=None):
        """Carga los puntos de calibración desde disco y refresca la UI."""
        try:
            if hasattr(self, '_cal_manager') and self._cal_manager:
                self._cal_manager.load_points()
                self.log_message("Sesión de calibración cargada desde disco.")
                if hasattr(self, '_refresh_cal_wizard_table_ui'):
                    self._refresh_cal_wizard_table_ui()
                if hasattr(self, '_update_cal_wizard_graph'):
                    self._update_cal_wizard_graph()
            else:
                self.log_message("No existe un gestor de calibración activo.")
        except Exception as e:
            self.log_message(f"Error cargando sesión de calibración: {e}")

    def __init__(self, data_queue, command_queue, data_processor=None):
        super().__init__(themename=THEME_NAME)
        self.data_processor = data_processor
        self.title(APP_TITLE)

        real_screen_width = self.winfo_screenwidth()
        real_screen_height = self.winfo_screenheight()

        # Si la resolución es 1280x800, quitar barra superior
        if real_screen_width == 1280 and real_screen_height == 800:
            self.overrideredirect(True)
            self.geometry(f"{real_screen_width}x{real_screen_height}+0+0")
        else:
            # En otras resoluciones: ventana maximizada con barra
            try:
                self.state("zoomed")  # Solo en Windows
            except Exception:
                self.geometry(f"{real_screen_width}x{real_screen_height}+0+0")

        self._calculate_scale_factors(real_screen_width, real_screen_height)
        
        # Guardar referencia para mover ventana (drag)
        self._drag_data = {"x": 0, "y": 0}
        
        self.data_queue = data_queue
        self.command_queue = command_queue
        
        self.connected = False
        
        # Almacenar ltimos datos para calibracin
        self._last_sensor_data = {}
        
        # Almacenar nodos descubiertos
        self._discovered_nodes = []

        # Último timestamp visto por widget para cada sensor (mantener display hasta nueva muestra)
        self._widget_last_seen = {}
        # Último timestamp visto para el total (mantener total hasta nueva muestra)
        self._widget_last_total = 0.0
        
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
    
    def _calculate_scale_factors(self, screen_width, screen_height):
        """Calcula factores de escala basados en la resolución de pantalla."""
        # Factor de escala (relativo a la resolución base 1280x800)
        self.scale_x = screen_width / BASE_WIDTH
        self.scale_y = screen_height / BASE_HEIGHT
        
        # Factor de escala general (promedio geométrico para mantener proporciones)
        self.scale = min(self.scale_x, self.scale_y)
        
        # Factor específico para fuentes (no escalar demasiado en pantallas grandes)
        # Limitar entre 0.8 y 1.5 para mantener legibilidad
        self.font_scale = max(0.8, min(1.5, self.scale))
        
        # Log en archivo
        self.log_message(f"[GUI] Resolución detectada: {screen_width}x{screen_height}")
        self.log_message(f"[GUI] Factor de escala: {self.scale:.2f} (fuentes: {self.font_scale:.2f})")
    
    def scaled(self, value):
        """Escala un valor numérico según la resolución."""
        return int(value * self.scale)
    
    def scaled_font(self, size):
        """Escala el tamaño de fuente según la resolución."""
        return int(size * self.font_scale)

    def _fit_label_font(self, label, text, family, max_size, min_size=8, weight='bold', explicit_width=None):
        """Ajusta el tamaño de fuente de `label` para que `text` quepa en su ancho disponible.

        - `explicit_width`: si se proporciona (en píxeles), se usa en lugar de medir el widget.
        """
        try:
            import tkinter.font as tkfont
            # Forzar layout para obtener medidas reales
            try:
                self.update_idletasks()
            except Exception:
                pass

            # Determinar ancho disponible: preferir explicit_width si hay
            if explicit_width and isinstance(explicit_width, int) and explicit_width > 0:
                avail_w = explicit_width
            else:
                avail_w = label.winfo_width()
                if not avail_w or avail_w <= 1:
                    parent = label.master
                    avail_w = parent.winfo_width() or parent.winfo_reqwidth() or label.winfo_reqwidth()

            padding = 8  # margen de seguridad en píxeles
            avail_w = max(1, int(avail_w) - padding)

            chosen_size = min(max_size, max(min_size, int(max_size)))
            for size in range(chosen_size, min_size - 1, -1):
                f = tkfont.Font(family=family, size=size, weight=weight)
                w = f.measure(text)
                if w <= avail_w:
                    label.configure(font=(family, size, weight))
                    return

            # Si ninguno encaja, forzar el mínimo
            label.configure(font=(family, min_size, weight))
        except Exception:
            # Fallback silencioso
            try:
                label.configure(font=(family, min_size, weight))
            except Exception:
                pass

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
        
        # Fonts - Escalados según resolución
        FONT_MAIN = "Segoe UI"
        FONT_MONO = "Consolas"
        
        # Función helper local para escalar fuentes
        sf = self.scaled_font
        
        # Configure TFrame styles
        self.style.configure('Body.TFrame', background=BG_BODY)
        self.style.configure('Card.TFrame', background=BG_CARD, relief="solid", borderwidth=1)
        self.style.configure('CardNoBorder.TFrame', background=BG_CARD)
        
        # Configure Label styles - Escalados
        self.style.configure('CardTitle.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(16), "bold"))
        self.style.configure('CardValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MONO, sf(40), "bold"))
        self.style.configure('Unit.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(18)))
        self.style.configure('SensorStatus.TLabel', background=BG_CARD, foreground=SUCCESS, font=(FONT_MAIN, sf(13), "bold"))
        
        # Total Panel - MUY PROMINENTE para nfasis mximo
        self.style.configure('TotalPanel.TFrame', background=PRIMARY)
        self.style.configure('TotalLabel.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, sf(28), "bold"))
        self.style.configure('TotalValue.TLabel', background=PRIMARY, foreground="white", font=(FONT_MONO, sf(72), "bold"))
        self.style.configure('TotalUnit.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, sf(36)))
        
        # Total Panel DANGER - Cuando hay sensor desconectado (ROJO)
        self.style.configure('TotalPanelDanger.TFrame', background=DANGER)
        self.style.configure('TotalLabelDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MAIN, sf(24), "bold"))
        self.style.configure('TotalValueDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MONO, sf(72), "bold"))
        self.style.configure('TotalUnitDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MAIN, sf(20)))
        
        # Tara Info - Más visible
        self.style.configure('TareInfo.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(14), "bold"))
        # Estilo centrado y no negrita para el indicador de TARA (título)
        self.style.configure('TareCenter.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(14)))
        # Estilo de valor de Tara (monoespaciado, no negrita)
        self.style.configure('TareValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MONO, sf(40)))
        
        # Buttons - Escalados
        self.style.configure('TButton', font=(FONT_MAIN, sf(12), 'bold'))  # Default global BOLD
        self.style.configure('Tare.TButton', font=(FONT_MAIN, sf(16), 'bold'))
        self.style.configure('Reset.TButton', font=(FONT_MAIN, sf(14), 'bold'))
        self.style.configure('Header.TButton', font=(FONT_MAIN, sf(14), 'bold'))
        
        # Large Dialog Buttons
        self.style.configure('Large.success.TButton', font=(FONT_MAIN, sf(18), 'bold'))
        self.style.configure('Large.danger.TButton', font=(FONT_MAIN, sf(18), 'bold'))
        self.style.configure('Large.info.TButton', font=(FONT_MAIN, sf(18), 'bold'))
        self.style.configure('Large.warning.TButton', font=(FONT_MAIN, sf(18), 'bold'))

        # Tabs config - Pestañas gruesas, anchas y centradas
        self.style.configure('TNotebook.Tab', font=(FONT_MAIN, sf(16), 'bold'), padding=(self.scaled(40), self.scaled(15)))
        self.style.map('TNotebook.Tab', 
                      background=[('selected', PRIMARY)], 
                      foreground=[('selected', 'white')])

        # Combobox - Escalados
        self.style.configure('TCombobox', font=(FONT_MAIN, sf(14)), padding=self.scaled(8))
        # Aumentar altura del dropdown list
        self.option_add('*TCombobox*Listbox.font', (FONT_MAIN, sf(14)))
        self.option_add('*TCombobox*Listbox*selectBackground', PRIMARY)
        self.option_add('*TCombobox*Listbox*selectForeground', 'white')

        # Header
        self.style.configure('Header.TFrame', background=BG_CARD)
        # Reducir tamaño del título para que no ocupe tanto espacio en el footer
        self.style.configure('HeaderTitle.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MAIN, sf(16), "bold"))
        self.style.configure('HeaderSub.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(12)))
        # Logo label style to ensure visibility
        self.style.configure('Logo.TLabel', background=BG_CARD)

    def _setup_ui(self):
        # Main Container - padding escalado
        main_container = ttk.Frame(self, style='Body.TFrame', padding=self.scaled(10))
        main_container.pack(fill=BOTH, expand=YES)
        
        # --- Header (Barra personalizada para reemplazar barra de Windows) ---
        header_frame = ttk.Frame(main_container, style='Header.TFrame', padding=self.scaled(8))
        header_frame.pack(fill=X, pady=(0, self.scaled(10)))
        
        # Permitir arrastrar la ventana desde el header
        header_frame.bind("<Button-1>", self._start_drag)
        header_frame.bind("<B1-Motion>", self._on_drag)
        
        # Brand Area
        brand_frame = ttk.Frame(header_frame, style='Header.TFrame')
        brand_frame.pack(side=LEFT)
        brand_frame.bind("<Button-1>", self._start_drag)
        brand_frame.bind("<B1-Motion>", self._on_drag)
        
        # Intentar cargar un solo logo principal junto al título
        import os
        assets_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

        self.logo_img = None
        # Tamaño de logo (escalado)
        logo_height = self.scaled(80)
        # Guardar resample_method solo si PIL está disponible
        if Image is not None:
            try:
                resample_method = getattr(Image, 'Resampling', Image).LANCZOS
            except Exception:
                try:
                    resample_method = Image.LANCZOS
                except Exception:
                    resample_method = None
        else:
            resample_method = None

        def load_logo(path, height):
            """Cargar y redimensionar un logo."""
            # Log de diagnóstico
            try:
                self.log_message(f"Intentando cargar logo: {path} (PIL={'si' if Image is not None else 'no'})")
            except Exception:
                pass

            if Image is None or ImageTk is None:
                try:
                    self.log_message("Pillow (PIL) no disponible: el logo no puede cargarse.")
                except Exception:
                    pass
                return None

            if os.path.exists(path):
                try:
                    pil_img = Image.open(path)
                    w_percent = (height / float(pil_img.size[1]))
                    w_size = int((float(pil_img.size[0]) * float(w_percent)))
                    if resample_method is not None:
                        pil_img_resized = pil_img.resize((w_size, height), resample_method)
                    else:
                        pil_img_resized = pil_img.resize((w_size, height))
                    imgobj = ImageTk.PhotoImage(pil_img_resized)
                    try:
                        self.log_message(f"Logo cargado correctamente desde: {path}")
                    except Exception:
                        pass
                    return imgobj
                except Exception as e:
                    try:
                        self.log_message(f"Erro carregando logo {path}: {e}")
                    except Exception:
                        pass
            else:
                try:
                    self.log_message(f"Logo no encontrado en ruta: {path}")
                except Exception:
                    pass
            return None

        # Cargar logo principal (logo.png)
        logo_path = os.path.join(assets_path, "logo.png")
        self.logo_img = load_logo(logo_path, logo_height)
        
        # Logo junto al título (si existe) - mantener solo el logo en la barra superior
        if self.logo_img:
            # Do not use a Frame style for a Label (some themes may override image rendering).
            logo_lbl = ttk.Label(brand_frame, image=self.logo_img)
            logo_lbl.pack(side=LEFT, padx=(0, 12))
            try:
                self.log_message("Logo widget creado y empaquetado en header.")
            except Exception:
                pass
        
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

        # (Export/Import moved to Config -> CALIBRACAO tab)
        
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

        # Nota: el título y el estado se muestran en el pie (footer)
        # para evitar que compriman las secciones de acciones (TARA).

        # --- Separador visual ---
        ttk.Separator(main_container, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))

        # Footer frame fijo (creado antes del grid central para garantizar visibilidad en pantallas pequeñas)
        try:
            footer_frame = ttk.Frame(main_container, style='Header.TFrame')
            footer_frame.pack(side=BOTTOM, fill=X, pady=(4, 4))

            # Caja para título + estado (alineados a la izquierda)
            footer_left = ttk.Frame(footer_frame, style='CardNoBorder.TFrame')
            footer_left.pack(side=LEFT, anchor='w', padx=(12, 6), pady=(6, 4))

            # Título del sistema (ahora en el pie)
            ttk.Label(footer_left, text="Sistema de Pesagem", style='HeaderTitle.TLabel').pack(side=LEFT)

            # Estado del sistema junto al título (reusar nombre self.lbl_status para compatibilidad)
            # Si existe un lbl_status previo, reusar, sino crear.
            try:
                if hasattr(self, 'lbl_status') and isinstance(self.lbl_status, ttk.Label):
                    # Reposicionar label al footer
                    try:
                        self.lbl_status.master = footer_left
                    except Exception:
                        pass
                    self.lbl_status.configure(text="Desconectado", style='HeaderSub.TLabel')
                    self.lbl_status.pack(side=LEFT, padx=(12, 0), pady=(8, 0))
                else:
                    self.lbl_status = ttk.Label(footer_left, text="Desconectado", style='HeaderSub.TLabel')
                    self.lbl_status.pack(side=LEFT, padx=(12, 0), pady=(8, 0))
            except Exception:
                try:
                    self.lbl_status = ttk.Label(footer_left, text="Desconectado", style='HeaderSub.TLabel')
                    self.lbl_status.pack(side=LEFT, padx=(12, 0), pady=(8, 0))
                except Exception:
                    pass

            # Intentar cargar logo2 (escala reducida) y colocarlo a la derecha
            try:
                logo2_path = os.path.join(assets_path, "logo2.png")
                try:
                    max_h = self.scaled(48)
                except Exception:
                    max_h = 48
                logo2_height = min(int(logo_height * 0.5), max_h)
                self.logo2_img = load_logo(logo2_path, logo2_height)
                if self.logo2_img:
                    logo2_lbl = ttk.Label(footer_frame, image=self.logo2_img, style='Logo.TLabel')
                    logo2_lbl.pack(side=RIGHT, padx=(0, 12), pady=(6, 6))
            except Exception:
                pass
        except Exception:
            footer_frame = None

        # --- Main Grid (Layout Original: Sensores | Total | Sensores) ---
        grid_area = ttk.Frame(main_container, style='Body.TFrame')
        # Empaquetar el grid central normalmente (sin reservar padding fijo)
        grid_area.pack(fill=BOTH, expand=YES)
        try:
            # Forzar tamaño objetivo del área central para mantener layout estable
            grid_area.configure(width=self.scaled(1000), height=self.scaled(600))
            grid_area.pack_propagate(False)
        except Exception:
            pass
        
        # Columnas con tamao escalado según resolución
        try:
            is_tablet = getattr(self, 'scale', 1.0) <= 1.0
            if is_tablet:
                # En tablets dar más espacio al panel TOTAL (columna central)
                grid_area.columnconfigure(0, weight=1, minsize=self.scaled(220))
                grid_area.columnconfigure(1, weight=3, minsize=self.scaled(520))  # TOTAL más ancho en tablets
                grid_area.columnconfigure(2, weight=1, minsize=self.scaled(220))
            else:
                grid_area.columnconfigure(0, weight=1, minsize=self.scaled(250))
                grid_area.columnconfigure(1, weight=2, minsize=self.scaled(350))  # Centro ms ancho para el TOTAL
                grid_area.columnconfigure(2, weight=1, minsize=self.scaled(250))
        except Exception:
            grid_area.columnconfigure(0, weight=1, minsize=self.scaled(250))
            grid_area.columnconfigure(1, weight=2, minsize=self.scaled(350))
            grid_area.columnconfigure(2, weight=1, minsize=self.scaled(250))
        # Reducir más el minsize de filas de sensores para dejar espacio al footer
        # Ajustar más conservadoramente para pantallas pequeñas
        grid_area.rowconfigure(0, weight=1, minsize=self.scaled(100))
        grid_area.rowconfigure(1, weight=1, minsize=self.scaled(100))

        self.sensor_widgets = {} 

        # Helper to create cards mapped to config keys
        def create_sensor_card(key, title, row, col, parent=None):
            # Card con borde visible y tamaño uniforme
            card_w = self.scaled(300)
            card_h = self.scaled(200)
            if parent is None:
                parent = grid_area
            card = ttk.Frame(parent, style='Card.TFrame', padding=20)
            # If placed inside a viga group, row/col semantics are relative to parent
            card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
            # Forzar tamaño fijo del contenedor para que no cambie al modificar fuentes
            try:
                card.configure(width=card_w, height=card_h)
            except Exception:
                pass
            try:
                card.grid_propagate(False)
            except Exception:
                pass
            try:
                card.pack_propagate(False)
            except Exception:
                pass

            # Header con título y estado
            header = ttk.Frame(card, style='CardNoBorder.TFrame')
            header.pack(fill=X, pady=(0, 8))

            # Mostrar título de la tarjeta (p. ej. "CÉLULA 1")
            try:
                title_lbl = ttk.Label(header, text=title, style='CardTitle.TLabel')
                title_lbl.pack(side=LEFT, anchor='w')
            except Exception:
                try:
                    ttk.Label(header, text=title).pack(side=LEFT, anchor='w')
                except Exception:
                    pass

            # Indicador de estado (más visible)
            status_frame = ttk.Frame(header, style='CardNoBorder.TFrame')
            status_frame.pack(side=RIGHT)

            rssi_lbl = ttk.Label(status_frame, text="", font=("Segoe UI", 16), foreground="#94a3b8")
            rssi_lbl.pack(side=LEFT)
            status_lbl = ttk.Label(status_frame, text="Sem Sinal", font=("Segoe UI", 12, "bold"), foreground="#94a3b8")
            status_lbl.pack(side=LEFT, padx=(5, 0))

            # Separador
            ttk.Separator(card, orient=HORIZONTAL).pack(fill=X, pady=8)

            # Valor principal - Centrado - grande, la fuente se ajustará para caber
            value_container = ttk.Frame(card, style='CardNoBorder.TFrame')
            value_container.pack(fill=BOTH, expand=YES)
            try:
                value_container.pack_propagate(False)
            except Exception:
                pass

            value_lbl = ttk.Label(
                value_container,
                text="0.00",
                font=('Consolas', self.scaled_font(40), 'bold'),
                foreground="#1e293b",
                background="#ffffff",
                anchor="center",
            )
            value_lbl.pack(expand=YES)
            try:
                # target_width: ancho útil disponible para el texto dentro de la tarjeta
                value_lbl.target_width = max(1, card_w - self.scaled(40))
            except Exception:
                value_lbl.target_width = None

            # Unidad
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
            # Crear marcos que agrupen las celdas por viga
            left_group = ttk.Labelframe(grid_area, text="Viga 1", padding=8, borderwidth=self.scaled(3), relief='solid', labelanchor='n', style='Viga.TLabelframe')
            left_group.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=8, pady=8)
            left_group.columnconfigure(0, weight=1)
            left_group.rowconfigure(0, weight=1)
            left_group.rowconfigure(1, weight=1)

            right_group = ttk.Labelframe(grid_area, text="Viga 2", padding=8, borderwidth=self.scaled(3), relief='solid', labelanchor='n', style='Viga.TLabelframe')
            right_group.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=8, pady=8)
            right_group.columnconfigure(0, weight=1)
            right_group.rowconfigure(0, weight=1)
            right_group.rowconfigure(1, weight=1)

            create_sensor_card(keys[0], "CÉLULA 1", 0, 0, parent=left_group)
            create_sensor_card(keys[1], "CÉLULA 2", 0, 0, parent=right_group)
            create_sensor_card(keys[2], "CÉLULA 3", 1, 0, parent=left_group)
            create_sensor_card(keys[3], "CÉLULA 4", 1, 0, parent=right_group)
        elif len(keys) >= 2:
            # Fallback si solo hay 2 celdas configuradas
            # Agrupar en vigas también para 2 celdas
            left_group = ttk.Labelframe(grid_area, text="Viga 1", padding=8, borderwidth=self.scaled(3), relief='solid', labelanchor='n', style='Viga.TLabelframe')
            left_group.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=8, pady=8)
            right_group = ttk.Labelframe(grid_area, text="Viga 2", padding=8, borderwidth=self.scaled(3), relief='solid', labelanchor='n', style='Viga.TLabelframe')
            right_group.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=8, pady=8)
            create_sensor_card(keys[0], "CÉLULA 1", 0, 0, parent=left_group)
            create_sensor_card(keys[1], "CÉLULA 2", 0, 0, parent=right_group)

        # --- PANEL CENTRAL: TOTAL (MS GRANDE) ---
        control_panel = ttk.Frame(grid_area, style='Card.TFrame', padding=self.scaled(10))
        control_panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=self.scaled(6), pady=self.scaled(6))
        # Forzar tamaño fijo del panel central (TOTAL) para que no cambie con los textos
        try:
            is_tablet = locals().get('is_tablet', getattr(self, 'scale', 1.0) <= 1.0)
            if is_tablet:
                panel_w = self.scaled(520)
                panel_h = self.scaled(420)
            else:
                panel_w = self.scaled(420)
                panel_h = self.scaled(420)
            control_panel.configure(width=panel_w, height=panel_h)
        except Exception:
            if locals().get('is_tablet', False):
                panel_w = self.scaled(520)
                panel_h = self.scaled(420)
            else:
                panel_w = self.scaled(420)
                panel_h = self.scaled(420)
        try:
            control_panel.grid_propagate(False)
        except Exception:
            pass
        try:
            control_panel.pack_propagate(False)
        except Exception:
            pass
        
        # Sección TOTAL: crear contenedor antes de usarlo
        try:
            self.total_section = ttk.Frame(control_panel, style='TotalPanel.TFrame', padding=self.scaled(18))
            self.total_section.pack(fill=BOTH, expand=YES)
        except Exception:
            # Fallback mínimo
            self.total_section = ttk.Frame(control_panel)
            self.total_section.pack(fill=BOTH, expand=YES)

        self.lbl_total_title = ttk.Label(self.total_section, text="PESO TOTAL", style='TotalLabel.TLabel', anchor="center")
        self.lbl_total_title.pack(fill=X)
        self.lbl_total = ttk.Label(
            self.total_section, 
            text="0", 
            style='TotalValue.TLabel', 
            anchor="center",
        )
        self.lbl_total.pack(fill=X, pady=12)
        try:
            # target width: usar panel_w menos padding interior
            self.lbl_total.target_width = max(1, panel_w - self.scaled(60))
        except Exception:
            self.lbl_total.target_width = None
        try:
            self.total_section.pack_propagate(False)
        except Exception:
            pass
        self.lbl_total_unit = ttk.Label(self.total_section, text="t", style='TotalUnit.TLabel', anchor="center")
        self.lbl_total_unit.pack()
        
        # Separador dentro del panel
        ttk.Separator(control_panel, orient=HORIZONTAL).pack(fill=X, pady=self.scaled(10))
        
        # Seccin de Acciones debajo del total
        actions_section = ttk.Frame(control_panel, style='CardNoBorder.TFrame', padding=self.scaled(5))
        actions_section.pack(fill=X)
        
        # Info de Tara: un botón a la izquierda, texto en dos líneas en el centro, y un botón a la derecha
        taracont = ttk.Frame(actions_section, style='CardNoBorder.TFrame')
        taracont.pack(fill=X)

        # Configurar grid para 3 columnas: boton izquierdo, texto (expandible), boton derecho
        taracont.columnconfigure(0, weight=0)
        taracont.columnconfigure(1, weight=1)
        taracont.columnconfigure(2, weight=0)

        # Botón izquierdo (TARA)
        btn_tare_left = ttk.Button(
            taracont,
            text="TARA",
            command=self.do_tare,
            bootstyle="warning",
            style='Tare.TButton',
            width=10,
            padding=(self.scaled(12), self.scaled(8))
        )
        btn_tare_left.grid(row=0, column=0, sticky='w', padx=(0, 8))

        # Centro: título y valor apilados
        tare_text_col = ttk.Frame(taracont)
        tare_text_col.grid(row=0, column=1, sticky='nsew')
        tare_text_col.columnconfigure(0, weight=1)

        self.lbl_tare_title = ttk.Label(
            tare_text_col,
            text="Tara acumulada",
            style='TareCenter.TLabel',
            anchor="center",
            justify='center'
        )
        self.lbl_tare_title.pack(fill=X)

        self.lbl_tare_value = ttk.Label(
            tare_text_col,
            text="0 t",
            style='TareValue.TLabel',
            anchor="center",
            justify='center'
        )
        self.lbl_tare_value.pack(fill=X, pady=(4, 0))

        # Botón derecho (RESET)
        btn_reset_right = ttk.Button(
            taracont,
            text="RESET",
            command=self.reset_tare,
            bootstyle="secondary",
            style='Tare.TButton',
            width=10,
            padding=(self.scaled(12), self.scaled(8))
        )
        btn_reset_right.grid(row=0, column=2, sticky='e', padx=(8, 0))
        
        
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
        """Guarda mensajes y errores en el archivo log."""
        import datetime, os
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'balanza.log')
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass

    def _update_display(self, data):
        # Guardar datos para actualización cuando cambie modo decimales
        self._last_sensor_data = data
        
        # Atualizar Tara Acumulada em Toneladas
        if 'total_tare' in data:
            tara_ton = data['total_tare']
            # Actualizar el widget nuevo si existe, sino mantener compatibilidad
            tare_text = f"{self._format_weight(tara_ton)} t"
            if hasattr(self, 'lbl_tare_value'):
                try:
                    self.lbl_tare_value.configure(text=tare_text)
                except Exception:
                    pass
            elif hasattr(self, 'lbl_tare_info'):
                try:
                    self.lbl_tare_info.configure(text=f"Tara Acumulada: {tare_text}")
                except Exception:
                    pass
        
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
            # Actualizar total usando timestamp (permitiendo totals negativos).
            incoming_total_last = data.get('total_last_seen', 0.0) or 0.0
            # Ignoramos la comprobación 'total_raw>0' para que valores negativos
            # en las lecturas sean reflejados en la UI tal como llegan.
            # Actualizar solo si la muestra es nueva (strict >) para evitar
            # redibujos con el mismo timestamp que causaban parpadeos.
            if incoming_total_last > self._widget_last_total:
                peso_ton = data.get('total', 0.0)
                total_text = f"{self._format_weight(peso_ton)}"
                # Ajustar fuente del TOTAL según decimales y signo negativo
                try:
                    # Derivar tamaños base
                    normal_total = self.scaled_font(120)
                except Exception:
                    normal_total = 120
                total_small = max(40, int(normal_total * 0.9))
                total_extra_small = max(30, int(normal_total * 0.7))
                try:
                    # Ajustar el texto primero y luego adaptar la fuente para que quepa
                    self.lbl_total.configure(text=total_text, style='TotalValue.TLabel')
                    if self._show_decimals and str(total_text).strip().startswith("-"):
                        tgt = total_extra_small
                    elif self._show_decimals:
                        tgt = total_small
                    else:
                        tgt = normal_total
                    fixed_total_w = getattr(self.lbl_total, 'target_width', self.scaled(360))
                    self._fit_label_font(self.lbl_total, str(total_text), 'Consolas', max_size=tgt, min_size=total_extra_small, explicit_width=fixed_total_w)
                except Exception:
                    # Fallback conservador
                    try:
                        self.lbl_total.configure(text=total_text)
                    except Exception:
                        pass
                self._widget_last_total = incoming_total_last
            self.lbl_total_unit.configure(text="t", style='TotalUnit.TLabel')
        
        # Actualizar Sensores Individuales
        sensores = data['sensores']
        for key, widgets in self.sensor_widgets.items():
            if key in sensores:
                info = sensores[key]
                # Actualizar valor solo si la muestra es nueva (usar last_seen)
                valor_ton = info.get('valor', 0.0)
                incoming_last = info.get('last_seen', 0.0) or 0.0
                prev_last = self._widget_last_seen.get(key, 0.0)
                if incoming_last > prev_last:
                    display_text = self._format_weight(valor_ton)
                    widgets['value'].configure(text=display_text)
                    # Ajustar la fuente para que el texto encaje sin cambiar el contenedor
                    try:
                        try:
                            normal_cell = self.scaled_font(64)
                        except Exception:
                            normal_cell = 64
                        cell_small = max(10, int(normal_cell * 0.75))
                        cell_extra_small = max(8, int(normal_cell * 0.6))

                        if self._show_decimals and str(display_text).strip().startswith("-"):
                            tgt = cell_extra_small
                        elif self._show_decimals:
                            tgt = cell_small
                        else:
                            tgt = normal_cell

                        fixed_w = getattr(widgets['value'], 'target_width', self.scaled(260))
                        self._fit_label_font(widgets['value'], str(display_text), 'Consolas', max_size=tgt, min_size=cell_extra_small, explicit_width=fixed_w)
                    except Exception:
                        pass
                    self._widget_last_seen[key] = incoming_last
                
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
            self.lbl_status.configure(text="Conectado", foreground="#22c55e")
            # Manter dimenses ao mudar estilo
            self.btn_connect.configure(
                text="DESCONECTAR", 
                bootstyle="danger",
                style='Header.TButton',
                width=14,
                padding=(15, 12)
            )
            # Al conectarse, intentar cargar y aplicar calibraciones disponibles
            try:
                self._apply_saved_calibrations_on_connect()
            except Exception:
                pass
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
            # Permitir solo un '-' al inicio
            if d == "-":
                if current.startswith("-"):
                    return
                if current == "":
                    kp_value.set("-")
                else:
                    kp_value.set("-" + current)
                first_press[0] = False
                return
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
        
        def actualizar_gui(self):
            """Consume mensajes de la cola y actualiza la UI (sin registro visual)."""
            try:
                while True:
                    msg = self.data_queue.get_nowait()
                    if msg['type'] == 'DATA':
                        data = msg['payload']
                        self._last_sensor_data = data
                        self._update_display(data)
                    elif msg['type'] == 'STATUS':
                        self._update_status(msg['payload'])
                    elif msg['type'] == 'ERROR':
                        self.show_alert("Erro", msg['payload'], "error")
                        self.log_message(f"[ERRO] {msg['payload']}")
                    elif msg['type'] == 'LOG':
                        self.log_message(msg['payload'])
                    elif msg['type'] == 'CONNECTION_PROGRESS':
                        payload = msg['payload']
                        self._update_connection_progress(payload)
                    elif msg['type'] == 'SENSOR_DISCONNECT':
                        payload = msg['payload']
                        self._show_sensor_disconnect_dialog(payload)
                    elif msg['type'] == 'SENSOR_RECONNECTED':
                        payload = msg['payload']
                        self._handle_sensor_reconnected(payload)
                    elif msg['type'] == 'RECONNECT_PROGRESS':
                        payload = msg['payload']
                        self._update_reconnect_progress(payload)
                    elif msg['type'] == 'RECONNECT_FAILED':
                        payload = msg['payload']
                        self._handle_reconnect_failed(payload)
                    elif msg['type'] == 'DISCOVERED_NODES':
                        payload = msg['payload']
                        self._handle_discovered_nodes(payload)
            except queue.Empty:
                pass
            finally:
                self.after(50, self.actualizar_gui)
        # Entry para mostrar el valor digitado
        # Frame superior para layout grid
        keypad_frame = ttk.Frame(keypad)
        keypad_frame.pack(fill="both", expand=True)
        keypad_frame.rowconfigure(0, weight=2)
        keypad_frame.rowconfigure(1, weight=8)
        keypad_frame.columnconfigure(0, weight=1)

        # Entry grande en la primera fila
        entry_display = ttk.Entry(keypad_frame, textvariable=kp_value, font=("Consolas", 32), justify="center", state="readonly")
        entry_display.grid(row=0, column=0, sticky="nsew", padx=40, pady=(40, 20))

        # Frame de botones en la segunda fila
        all_btns = ttk.Frame(keypad_frame)
        all_btns.grid(row=1, column=0, sticky="nsew")
        for i in range(5):
            all_btns.rowconfigure(i, weight=1)
        for j in range(3):
            all_btns.columnconfigure(j, weight=1)

        pad_num = (18, 18)
        pad_act = (18, 22)

        def confirm_and_close():
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, kp_value.get())
            try:
                keypad.grab_release()
            except:
                pass
            keypad.destroy()
            self._active_keypad = None

        # Fila 0: 7 8 9
        ttk.Button(all_btns, text="7", command=lambda: press_digit("7"), bootstyle="light", padding=pad_num).grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="8", command=lambda: press_digit("8"), bootstyle="light", padding=pad_num).grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="9", command=lambda: press_digit("9"), bootstyle="light", padding=pad_num).grid(row=0, column=2, sticky="nsew", padx=4, pady=4)

        # Fila 1: 4 5 6
        ttk.Button(all_btns, text="4", command=lambda: press_digit("4"), bootstyle="light", padding=pad_num).grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="5", command=lambda: press_digit("5"), bootstyle="light", padding=pad_num).grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="6", command=lambda: press_digit("6"), bootstyle="light", padding=pad_num).grid(row=1, column=2, sticky="nsew", padx=4, pady=4)

        # Fila 2: 1 2 3
        ttk.Button(all_btns, text="1", command=lambda: press_digit("1"), bootstyle="light", padding=pad_num).grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="2", command=lambda: press_digit("2"), bootstyle="light", padding=pad_num).grid(row=2, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="3", command=lambda: press_digit("3"), bootstyle="light", padding=pad_num).grid(row=2, column=2, sticky="nsew", padx=4, pady=4)

        # Fila 3: . 0 DEL
        ttk.Button(all_btns, text=".", command=lambda: press_digit("."), bootstyle="secondary", padding=pad_num).grid(row=3, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="0", command=lambda: press_digit("0"), bootstyle="light", padding=pad_num).grid(row=3, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="DEL", command=press_backspace, bootstyle="warning", padding=pad_act).grid(row=3, column=2, sticky="nsew", padx=4, pady=4)

        # Fila 4: - | OK (OK ocupa 2 columnas)
        ttk.Button(all_btns, text="-", command=lambda: press_digit("-"), bootstyle="secondary", padding=pad_act).grid(row=4, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="OK", command=confirm_and_close, bootstyle="success", padding=pad_act).grid(row=4, column=1, columnspan=2, sticky="nsew", padx=4, pady=4)

        # Evitar grab_set() para no bloquear la app en tablets; usar focus/lift
        try:
            keypad.focus_set()
            keypad.lift()
        except Exception:
            pass

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
        # Toggle flag only; keep the button label as '0.00'
        self._show_decimals = not self._show_decimals
        # Simplified: only two font states exist now - with decimals and without decimals.
        try:
            normal_cell = self.scaled_font(64)
        except Exception:
            normal_cell = 64
        try:
            normal_total = self.scaled_font(120)
        except Exception:
            normal_total = 120

        if self._show_decimals:
            sensor_target = max(12, int(normal_cell * 0.85))
            total_target = max(40, int(normal_total * 0.85))
        else:
            sensor_target = normal_cell
            total_target = normal_total

        min_sensor = max(8, int(sensor_target * 0.6))
        min_total = max(20, int(total_target * 0.6))

        # Aplicar tamaño de fuente a widgets individuales sin cambiar el tamaño del contenedor
        for key, widgets in getattr(self, 'sensor_widgets', {}).items():
            try:
                txt = widgets['value'].cget('text') or "0"
                fixed_w = getattr(widgets['value'], 'target_width', self.scaled(260))
                self._fit_label_font(widgets['value'], str(txt), 'Consolas', max_size=sensor_target, min_size=min_sensor, explicit_width=fixed_w)
            except Exception:
                pass

        # Ajustar TOTAL sin alterar contenedor central (dos estados solamente)
        try:
            if hasattr(self, 'lbl_total') and self.lbl_total:
                txt_total = self.lbl_total.cget('text') or "0"
                fixed_total_w = getattr(self.lbl_total, 'target_width', self.scaled(360))
                self._fit_label_font(self.lbl_total, str(txt_total), 'Consolas', max_size=total_target, min_size=min_total, explicit_width=fixed_total_w)
        except Exception:
            pass

        # Forzar actualización visual inmediata de todos los valores
        self.after(10, self._refresh_all_displays)
    
    def _apply_saved_calibrations_on_connect(self):
        """Busca y aplica calibraciones desde el directorio de calibraciones cuando se conecta el sistema.
        Para cada composite -> serial en el DataProcessor intenta cargar:
          - {CALIBRATIONS_DIR}/{serial}.json
          - {CALIBRATIONS_DIR}/{nodeid_ch}.json (fallback)
        y llama a `data_processor.set_calibration_segments(points, serial=serial, composite=composite)` si existe.
        """
        try:
            from config import CALIBRATIONS_DIR
        except Exception:
            return

        if not hasattr(self, 'data_processor') or not self.data_processor:
            return

        # First: support single-file CSVs. Prefer `curvas_celdas.csv` (wide unified format)
        try:
            import csv as _csv
            applied = set()
            # Prefer unified curvas_celdas.csv
            unified_path = os.path.join(CALIBRATIONS_DIR, 'curvas_celdas.csv')
            if os.path.exists(unified_path):
                try:
                    with open(unified_path, 'r', encoding='utf-8') as f:
                        reader = _csv.reader(f)
                        try:
                            headers = next(reader)
                        except StopIteration:
                            headers = []
                        targets = [h.strip() for h in headers[1:]]
                        cols = {t: [] for t in targets}
                        for row in reader:
                            if not row:
                                continue
                            try:
                                w = float(row[0])
                            except Exception:
                                continue
                            for idx, t in enumerate(targets):
                                if idx + 1 >= len(row):
                                    continue
                                val = row[idx + 1].strip()
                                if val == '':
                                    continue
                                try:
                                    r = float(val)
                                except Exception:
                                    continue
                                cols[t].append((w, r))

                    # Apply each non-empty column
                    if hasattr(self.data_processor, 'set_calibration_segments'):
                        for target, pts in cols.items():
                            if not pts:
                                continue
                            serial_r = None
                            composite_r = None
                            if ':' in target:
                                composite_r = target
                            elif '_' in target:
                                composite_r = target.replace('_', ':')
                            else:
                                serial_r = target
                            try:
                                self.data_processor.set_calibration_segments(pts, serial=serial_r, composite=composite_r)
                                self.log_message(f"Calibración aplicada desde {os.path.basename(unified_path)} a target={target} puntos={len(pts)}")
                                applied.add((serial_r, composite_r))
                            except Exception as e:
                                self.log_message(f"Fallo aplicando calibración unificada para target={target}: {e}")
                    else:
                        # fallback: set attributes
                        for target, pts in cols.items():
                            if not pts:
                                continue
                            try:
                                self.data_processor.calibration_segments = pts
                                self.data_processor.calibration_method = 'segments'
                                applied.add((None, None))
                            except Exception as e:
                                self.log_message(f"Fallo aplicando calibración unificada (fallback) para target={target}: {e}")

                    if applied:
                        return
                except Exception as e:
                    self.log_message(f"Error leyendo {unified_path}: {e}")

            # Fallback: legacy calibrations.csv (may be wide or long format)
            csv_path = os.path.join(CALIBRATIONS_DIR, 'calibrations.csv')
            if os.path.exists(csv_path):
                try:
                    with open(csv_path, 'r', encoding='utf-8') as f:
                        sample = f.read(2048)
                        f.seek(0)
                        first_line = f.readline()
                        f.seek(0)
                        hdr_lower = first_line.strip().lower()
                        rows_by_target = {}
                        if hdr_lower.startswith('carga') or 'carga' in hdr_lower or 'carga real' in hdr_lower:
                            # wide format
                            reader = _csv.reader(f)
                            try:
                                headers = next(reader)
                            except StopIteration:
                                headers = []
                            targets = [h.strip() for h in headers[1:]]
                            for row in reader:
                                if not row:
                                    continue
                                try:
                                    w = float(row[0])
                                except Exception:
                                    continue
                                for idx, target in enumerate(targets):
                                    if idx + 1 >= len(row):
                                        continue
                                    val = row[idx + 1].strip()
                                    if val == '':
                                        continue
                                    try:
                                        r = float(val)
                                    except Exception:
                                        continue
                                    serial_r = None
                                    composite_r = None
                                    if ':' in target:
                                        composite_r = target
                                    elif '_' in target:
                                        composite_r = target.replace('_', ':')
                                    else:
                                        serial_r = target
                                    key = (serial_r, composite_r)
                                    rows_by_target.setdefault(key, []).append((w, r))
                        else:
                            # long format
                            f.seek(0)
                            reader = _csv.DictReader(f)
                            for row in reader:
                                serial_r = (row.get('serial') or '').strip() or None
                                composite_r = (row.get('composite') or '').strip() or None
                                try:
                                    w = float(row.get('weight', '0'))
                                    r = float(row.get('reading', '0'))
                                except Exception:
                                    continue
                                key = (serial_r, composite_r)
                                rows_by_target.setdefault(key, []).append((w, r))

                    # Apply groups
                    for (serial_k, composite_k), pts in rows_by_target.items():
                        try:
                            if hasattr(self.data_processor, 'set_calibration_segments'):
                                self.data_processor.set_calibration_segments(pts, serial=serial_k, composite=composite_k)
                                self.log_message(f"Calibración aplicada desde {os.path.basename(csv_path)} a serial={serial_k} composite={composite_k}")
                            else:
                                self.data_processor.calibration_segments = pts
                                self.data_processor.calibration_method = 'segments'
                                self.log_message(f"Calibración (fallback) cargada desde CSV para serial={serial_k} composite={composite_k}")
                            applied.add((serial_k, composite_k))
                        except Exception as e:
                            self.log_message(f"Fallo aplicando calibración CSV para serial={serial_k} composite={composite_k}: {e}")

                    if applied:
                        return
                except Exception:
                    pass
        except Exception:
            # If any unexpected error occurs, continue to JSON fallback below
            pass
        except Exception:
            # If CSV parsing fails, continue to JSON fallback below
            pass

        mapping = getattr(self.data_processor, '_composite_to_serial', {}) or {}
        if not mapping and hasattr(self.data_processor, 'nodos_config'):
            try:
                for nombre, cfg in self.data_processor.nodos_config.items():
                    nid = cfg.get('id')
                    ch = cfg.get('ch', 'ch1')
                    composite = f"{nid}:{ch}"
                    mapping[composite] = cfg.get('serial')
            except Exception:
                pass

        for composite, serial in list(mapping.items()):
            candidates = []
            if serial and str(serial).strip():
                candidates.append(os.path.join(CALIBRATIONS_DIR, f"{serial}.json"))
            safe_comp = composite.replace(':', '_')
            candidates.append(os.path.join(CALIBRATIONS_DIR, f"{safe_comp}.json"))

            for path in candidates:
                try:
                    if not path or not os.path.exists(path):
                        continue
                    with open(path, 'r', encoding='utf-8') as f:
                        import json as _json
                        data = _json.load(f)
                    pts = []
                    if isinstance(data, list):
                        for item in data:
                            if not isinstance(item, dict):
                                continue
                            w = item.get('weight')
                            r = item.get('reading')
                            if w is None or r is None:
                                continue
                            pts.append((float(w), float(r)))
                    if pts:
                        if hasattr(self.data_processor, 'set_calibration_segments'):
                            try:
                                self.data_processor.set_calibration_segments(pts, serial=serial, composite=composite)
                                self.log_message(f"Calibración aplicada desde {os.path.basename(path)} a {composite}")
                            except Exception as e:
                                self.log_message(f"Fallo aplicando calibración {path}: {e}")
                        else:
                            try:
                                self.data_processor.calibration_segments = pts
                                self.data_processor.calibration_method = 'segments'
                                self.log_message(f"Calibración (fallback) cargada para {composite}")
                            except Exception as e:
                                self.log_message(f"Fallo al establecer calibración fallback: {e}")
                        break
                except Exception as e:
                    try:
                        self.log_message(f"Error cargando calibración {path}: {e}")
                    except:
                        pass
                
    
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

    def export_calibrations_gui(self):
        """Exporta todas las calibraciones JSON a un único CSV en el directorio de calibraciones."""
        try:
            from config import CALIBRATIONS_DIR
        except Exception:
            self.log_message("No se encontró CALIBRATIONS_DIR en config.")
            return

        # Reuse the logic from scripts/export_calibrations_to_csv.py but inline
        try:
            import csv as _csv
            rows = []
            for fn in os.listdir(CALIBRATIONS_DIR):
                if not fn.lower().endswith('.json'):
                    continue
                path = os.path.join(CALIBRATIONS_DIR, fn)
                serial = None
                composite = None
                name = os.path.splitext(fn)[0]
                if ':' in name:
                    composite = name
                elif '_' in name:
                    parts = name.split('_')
                    if len(parts) >= 2:
                        composite = f"{parts[0]}:{parts[1]}"
                else:
                    serial = name

                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    continue

                if isinstance(data, list):
                    for it in data:
                        if not isinstance(it, dict):
                            continue
                        try:
                            w = float(it.get('weight', 0))
                            r = float(it.get('reading', 0))
                            ts = it.get('timestamp', '')
                        except Exception:
                            continue
                        rows.append({'serial': serial or '', 'composite': composite or '', 'weight': w, 'reading': r, 'timestamp': ts})

            out_path = os.path.join(CALIBRATIONS_DIR, 'calibrations.csv')
            with open(out_path, 'w', encoding='utf-8', newline='') as f:
                writer = _csv.DictWriter(f, fieldnames=['serial', 'composite', 'weight', 'reading', 'timestamp'])
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)

            self.log_message(f"Exportadas {len(rows)} filas a {out_path}")
            messagebox.showinfo("Exportación completa", f"Exportadas {len(rows)} filas a:\n{out_path}")
        except Exception as e:
            self.log_message(f"Error exportando calibraciones: {e}")
            messagebox.showerror("Error", f"Error exportando calibraciones: {e}")

    def import_calibrations_gui(self, parent=None):
        """Permite al usuario seleccionar un CSV de calibraciones e importarlo al CALIBRATIONS_DIR."""
        try:
            from config import CALIBRATIONS_DIR
        except Exception:
            self.log_message("No se encontró CALIBRATIONS_DIR en config.")
            return

        # Abrir filedialog con parent si fue proporcionado para mantener la ventana de config encima
        try:
            if parent:
                path = filedialog.askopenfilename(parent=parent, title="Seleccionar CSV de calibraciones", filetypes=[("CSV files", "*.csv")])
            else:
                path = filedialog.askopenfilename(title="Seleccionar CSV de calibraciones", filetypes=[("CSV files", "*.csv")])
        finally:
            # Restaurar foco en la ventana padre si se proporcionó
            if parent:
                try:
                    parent.lift()
                    parent.focus_force()
                except Exception:
                    pass

        if not path:
            return

        try:
            # Copiar / reemplazar el archivo adecuado según formato detectado.
            import shutil, csv as _csv
            # Leer primer bloque para detectar formato ancho (Carga Real) vs largo
            with open(path, 'r', encoding='utf-8') as f:
                sample = f.read(4096)
            is_wide = False
            try:
                first_line = sample.splitlines()[0].strip().lower() if sample else ''
                if 'carga' in first_line or 'carga real' in first_line:
                    is_wide = True
            except Exception:
                is_wide = False

            applied_report = []
            if is_wide:
                # Replace curvas_celdas.csv and apply each column as a calibration
                dest = os.path.join(CALIBRATIONS_DIR, 'curvas_celdas.csv')
                shutil.copy2(path, dest)
                self.log_message(f"CSV de curvas importado a {dest} (formato ancho)")

                # Parse and apply
                try:
                    with open(dest, 'r', encoding='utf-8') as f:
                        reader = _csv.reader(f)
                        try:
                            headers = next(reader)
                        except StopIteration:
                            headers = []
                        targets = [h.strip() for h in headers[1:]]
                        cols = {t: [] for t in targets}
                        weights = []
                        for row in reader:
                            if not row:
                                continue
                            try:
                                w = float(row[0])
                            except Exception:
                                continue
                            weights.append(w)
                            for idx, t in enumerate(targets):
                                if idx + 1 >= len(row):
                                    continue
                                val = row[idx + 1].strip()
                                if val == '':
                                    continue
                                try:
                                    r = float(val)
                                except Exception:
                                    continue
                                cols[t].append((w, r))

                    # Apply each non-empty column
                    if hasattr(self, 'data_processor') and self.data_processor:
                        for target, pts in cols.items():
                            if not pts:
                                continue
                            serial_r = None
                            composite_r = None
                            if ':' in target:
                                composite_r = target
                            elif '_' in target:
                                composite_r = target.replace('_', ':')
                            else:
                                serial_r = target
                            try:
                                if hasattr(self.data_processor, 'set_calibration_segments'):
                                    self.data_processor.set_calibration_segments(pts, serial=serial_r, composite=composite_r)
                                    applied_report.append((target, len(pts)))
                                    self.log_message(f"Calibración aplicada desde import (curvas) a target={target} puntos={len(pts)}")
                                else:
                                    self.data_processor.calibration_segments = pts
                                    self.data_processor.calibration_method = 'segments'
                                    applied_report.append((target, len(pts)))
                            except Exception as e:
                                self.log_message(f"Fallo aplicando calibración importada para target={target}: {e}")
                except Exception as e:
                    self.log_message(f"Error procesando CSV importado (ancho): {e}")
                    messagebox.showerror("Error", f"CSV importado, pero no se pudo procesar: {e}")
            else:
                # Legacy / long format: copy to calibrations.csv and reuse existing loader
                dest = os.path.join(CALIBRATIONS_DIR, 'calibrations.csv')
                shutil.copy2(path, dest)
                self.log_message(f"CSV de calibraciones importado a {dest} (formato largo)")
                try:
                    # Reuse existing logic that parses long format and applies
                    self._apply_saved_calibrations_on_connect()
                    self.log_message("Calibraciones aplicadas desde CSV importado (largo).")
                except Exception as e:
                    self.log_message(f"Error aplicando calibraciones desde CSV importado: {e}")
                    messagebox.showwarning("Advertencia", f"CSV importado pero no se pudieron aplicar las calibraciones: {e}")

            # Mostrar informe resumido al usuario si hubo aplicaciones
            try:
                if applied_report:
                    lines = [f"{t}: {n} puntos" for (t, n) in applied_report]
                    msg = "Se aplicaron las siguientes curvas:\n" + "\n".join(lines)
                    messagebox.showinfo("Importación completa", msg)
                else:
                    # Si no aplicó nada y no hubo error, mostrar confirmación de copia
                    if not is_wide:
                        messagebox.showinfo("Importación", f"CSV importado a:\n{dest}")
                    else:
                        if not applied_report:
                            messagebox.showinfo("Importación", f"CSV importado a:\n{dest}\nPero no se aplicaron curvas (archivo vacío o valores inválidos).")
            except Exception:
                pass
        except Exception as e:
            self.log_message(f"Fallo importando CSV: {e}")
            messagebox.showerror("Error", f"Fallo importando CSV: {e}")

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
        self.log_message("Solicitando limpar tara...")
        # Usar after para permitir que a UI seja atualizada
        self.after(100, self._show_reset_confirmation)

    def _show_reset_confirmation(self):
        resposta = self.show_large_confirmation("Confirmação", "Tem certeza que deseja limpar a tara?")
        self.log_message(f"Resposta diálogo: {resposta}")
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
        # Estilo para labels seleccionados en calibración
        sf = self.scaled_font
        self.style.configure('SelectedSensor.TLabel', background=PRIMARY, foreground='white', font=("Segoe UI", sf(26), 'bold'))
        self.style.configure('SelectedSensorSerial.TLabel', background=PRIMARY, foreground='white', font=("Segoe UI", sf(14)))
        self.style.configure('SelectedSensorStatus.TLabel', background=PRIMARY, foreground='white', font=("Segoe UI", sf(12), 'bold'))
        
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
        from config import SETTINGS_FILE
        config_path = SETTINGS_FILE
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

        # Crear ventana modal - FULLSCREEN (sin barra de título)
        dialog = ttk.Toplevel(self)
        dialog.overrideredirect(True)
        # Pantalla completa real
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        dialog.geometry(f"{screen_w}x{screen_h}+0+0")
        # Detectar pantallas pequeñas (tablet 1280x800) para ajustar paddings
        small_screen = (screen_w == 1280 and screen_h == 800)
        dialog.lift()
        dialog.focus_force()
        # Ocupar toda la pantalla (Tkinter fullscreen)
        try:
            dialog.attributes('-fullscreen', True)
        except Exception:
            pass

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
        # Empaquetar main_frame sin padding inferior; la barra de botones
        # se coloca con place() en pantallas pequeñas para evitar solapamientos
        main_frame.pack(fill=BOTH, expand=YES)
        
        # Variable para almacenar referencia a save_config (se define después)
        save_config_ref = [None]
        
        def do_save():
            if save_config_ref[0]:
                save_config_ref[0]()

        # ==================== BOTONES ABAJO (MOVIDOS AQUÍ) - COMPACTOS ====================
        # On small screens (1280x800) pin the button bar to the dialog bottom
        small_screen = (screen_w == 1280 and screen_h == 800)
        # Compactar paddings para ahorrar espacio vertical
        bottom_padding = (0, 5) if not small_screen else (0, 4)
        btn_parent = dialog if small_screen else main_frame
        btn_bottom_frame = ttk.Frame(btn_parent, padding=bottom_padding)
        if small_screen:
            # Use place to guarantee it's at the very bottom and not occluded
            try:
                btn_bottom_frame.place(relx=0, rely=1.0, anchor='sw', relwidth=1.0, height=self.scaled(70))
            except Exception:
                btn_bottom_frame.pack(fill=X, side=BOTTOM, pady=(4, 8))
            try:
                btn_bottom_frame.lift()
            except Exception:
                pass
        else:
            btn_bottom_frame.pack(fill=X, side=BOTTOM, pady=(2, 5))

        ttk.Separator(btn_bottom_frame, orient="horizontal").pack(fill=X, pady=(0, 5))

        btn_container = ttk.Frame(btn_bottom_frame)
        # Centrar el contenedor para que los botones no se peguen a la izquierda
        btn_container.pack(anchor='center')

        # Buttons size adjustments for small screens (más compactos)
        if small_screen:
            btn_width = 14
            btn_padding = (14, 8)
        else:
            btn_width = 15
            btn_padding = (20, 10)

        btn_salvar = ttk.Button(btn_container, text="SALVAR",
                       bootstyle="success",
                       command=do_save,
                       width=btn_width,
                       padding=btn_padding)
        btn_salvar.configure(style='Large.success.TButton')
        btn_salvar.pack(side=LEFT, padx=10)

        btn_cancelar = ttk.Button(btn_container, text="CANCELAR",
                       bootstyle="secondary",
                       command=safe_close_dialog,
                       width=btn_width,
                       padding=btn_padding)
        btn_cancelar.configure(style='Large.warning.TButton')
        btn_cancelar.pack(side=LEFT, padx=10)

        # Separador visual
        ttk.Frame(btn_container, width=self.scaled(20)).pack(side=LEFT)

        btn_fechar = ttk.Button(btn_container, text="FECHAR",
                       bootstyle="danger-outline",
                       command=safe_close_dialog,
                       width=btn_width,
                       padding=btn_padding)
        btn_fechar.configure(style='Large.danger.TButton')
        btn_fechar.pack(side=LEFT, padx=10)
        # ==================== FIN BOTONES ABAJO (COMPACTOS) ====================
        
        # Header: Solo Tabs (ocupa solo el ancho, no debe expandir verticalmente)
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=BOTH, expand=True, pady=(0, 5))

        # Notebook/Tabs (compacto en alto)
        notebook = ttk.Notebook(header_frame, style='BigTab.TNotebook')
        notebook.pack(fill=BOTH, expand=True)

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

        # Import/Export moved to the CALIBRACAO tab (see _setup_calibration_tab)
        
        node_entries = {}
        
        # === CONTENEDOR PRINCIPAL: Dos columnas lado a lado (ocupa todo el espacio) ===
        main_content = ttk.Frame(tab_nodes)
        # Si estamos en pantalla pequeña, reservar espacio inferior igual
        # a la altura de la barra de botones para que no la solape.
        if small_screen:
            # Reservar menos espacio inferior en tablets para evitar recortes
            main_content.pack(fill=BOTH, expand=True, pady=(15, self.scaled(30)))
        else:
            main_content.pack(fill=BOTH, expand=True, pady=(15, 0))
        # Tres columnas: Descoberta más ancha, Viga 1 y Viga 2 iguales
        main_content.columnconfigure(0, weight=12)
        main_content.columnconfigure(1, weight=10)
        main_content.columnconfigure(2, weight=10)
        # Fila 0: headers; Fila 1: contenido principal
        main_content.rowconfigure(0, weight=0)
        main_content.rowconfigure(1, weight=1)

        # === COLUMNA IZQUIERDA: Búsqueda de Nodos ===
        discover_frame = ttk.Labelframe(main_content, text="Descoberta de Nós", padding=15, borderwidth=self.scaled(3), relief='solid', labelanchor='n', style='Viga.TLabelframe')
        discover_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 5))
        try:
            discover_frame.grid_propagate(True)
        except Exception:
            pass
        # Estilo para las Vigas / Descoberta: etiqueta en negrita y fuente ligeramente mayor
        try:
            style = ttk.Style()
            style.configure('Viga.TLabelframe.Label', font=("Segoe UI", self.scaled(13), 'bold'))
        except Exception:
            try:
                style.configure('Viga.TLabelframe.Label', font=("Segoe UI", 13, 'bold'))
            except Exception:
                pass
        
        discover_btn_frame = ttk.Frame(discover_frame)
        discover_btn_frame.pack(anchor="n", fill=X, pady=(0, 10))
        
        # Variable para almacenar nodos descubiertos
        self._discovered_nodes = []
        self._discovered_nodes_var = tk.StringVar(value="Pressione 'Buscar' para descobrir nós")
        
        def discover_nodes_action():
            """Inicia descubrimiento de nodos."""
            self._discovered_nodes_var.set(" Procurando nós na rede...")
            self.command_queue.put({'cmd': 'DISCOVER_NODES'})

        
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
        ).pack(anchor="n", fill=X, pady=(10, 5))
        
        # Treeview para mostrar nodos descubiertos
        disc_columns = ("node_id", "serial", "channel", "rssi", "status")
        self._disc_tree = ttk.Treeview(discover_frame, columns=disc_columns, show="headings")
        
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
        
        # === COLUMNA DERECHA: Asignación de Células dividida en 2 vigas ===
        # Colocamos las vigas como columnas independientes en main_content
        viga1 = ttk.Labelframe(main_content, text="Viga 1", padding=5, borderwidth=self.scaled(2), relief='solid', labelanchor='n', style='Viga.TLabelframe')
        viga1.grid(row=1, column=1, rowspan=1, sticky="nsew", padx=8, pady=8)
        viga1.columnconfigure(0, weight=1)
        viga1.rowconfigure(0, weight=1)
        viga1.rowconfigure(1, weight=1)

        viga2 = ttk.Labelframe(main_content, text="Viga 2", padding=5, borderwidth=self.scaled(2), relief='solid', labelanchor='n', style='Viga.TLabelframe')
        viga2.grid(row=1, column=2, rowspan=1, sticky="nsew", padx=8, pady=8)
        viga2.columnconfigure(0, weight=1)
        viga2.rowconfigure(0, weight=1)
        viga2.rowconfigure(1, weight=1)
        
        positions = [
            (0, 0, 1, "ATRÁS ESQUERDA"),
            (0, 1, 2, "ATRÁS DIREITA"),
            (1, 0, 3, "FRENTE ESQUERDA"),
            (1, 1, 4, "FRENTE DIREITA"),
        ]
        
        for row, col, celda_num, pos_name in positions:
            key = f"celda_{celda_num}"
            current_node_data = current_config["nodes"].get(key, {"id": 0, "ch": "ch1", "nombre": f"Celda {celda_num}", "serial": ""})
            
            # Frame de cada celda con borde más visible, dentro de la viga correspondiente
            parent_viga = viga1 if col == 0 else viga2
            # Mostrar sólo la etiqueta simple CÉLULA N (no mostrar posición frente/atrás/izq/der)
            cell_frame = ttk.Labelframe(parent_viga, text=f"CÉLULA {celda_num}", padding=15)
            cell_frame.grid(row=row, column=0, sticky="nsew", padx=8, pady=8)
            # Permitir que el frame propague cambios de tamaño para evitar recortes
            try:
                cell_frame.grid_propagate(True)
            except Exception:
                pass
            try:
                cell_frame.pack_propagate(True)
            except Exception:
                pass
            
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

                
                # Mostrar el mensaje de éxito anclado a la ventana de configuración
                from tkinter import messagebox
                messagebox.showinfo("Salvo", "Configuração salva e aplicada.", parent=dialog)
                # Asegurar que la ventana de configuración permanezca al frente y con foco
                dialog.lift()
                dialog.focus_force()
            except Exception as e:
                try:
                    dialog.grab_release()
                except:
                    pass
                self.show_alert("Erro", f"Não foi possível salvar: {e}", "error", parent=self)
        
        # Asignar la función a la referencia del header
        save_config_ref[0] = save_config

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
        
        # Mapeo de nombres internos a nombres en portugués para display
        def get_display_name(internal_name):
            """Convierte nombre interno a nombre legible en portugués."""
            display_map = {
                'celda_1': 'Célula 1',
                'celda_2': 'Célula 2', 
                'celda_3': 'Célula 3',
                'celda_4': 'Célula 4',
            }
            return display_map.get(internal_name, internal_name.replace('_', ' ').title())
        
        # Guardar mapeo inverso para recuperar nombre interno
        self._sensor_display_to_internal = {}
        
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
            # Crear mapeo de display a interno
            for name in sensor_names:
                display_name = get_display_name(name)
                self._sensor_display_to_internal[display_name] = name
            
            # Variable para controlar la seleccion (usa nombre interno)
            self._cal_sensor_selected = tk.StringVar(value=sensor_names[0])
            
            # Grid layout para botones de sensores (Max 2 por fila para ser enormes)
            row = 0
            col = 0
            MAX_COLS = 2
            
            for name in sensor_names:
                display_name = get_display_name(name)
                serial_number = str(current_config["nodes"].get(name, {}).get("serial", ""))

                def select_sensor(s_name=name):
                    self._cal_sensor_selected.set(s_name)
                    self._update_sensor_buttons_visuals(inner_container)

                btn_frame = ttk.Frame(inner_container, style='Card.TFrame', cursor="hand2")
                btn_frame.grid(row=row, column=col, sticky="nsew", padx=12, pady=10)
                # permitir que el alto se ajuste según contenido (no forzar altura fija)
                try:
                    btn_frame.grid_propagate(True)
                except Exception:
                    pass
                btn_frame.bind("<Button-1>", lambda e, n=name: select_sensor(n))

                content_frame = ttk.Frame(btn_frame, style='CardNoBorder.TFrame')
                content_frame.pack(expand=YES, fill=BOTH, padx=5, pady=5)
                content_frame.bind("<Button-1>", lambda e, n=name: select_sensor(n))

                # Nombre del Sensor
                lbl_name = ttk.Label(content_frame, text=display_name, font=("Segoe UI", 26, "bold"))
                lbl_name.pack(expand=YES, side=TOP, pady=(12, 2))
                lbl_name.bind("<Button-1>", lambda e, n=name: select_sensor(n))

                # Número de serie debajo del nombre, si existe
                if serial_number:
                    lbl_serial = ttk.Label(content_frame, text=f"Nº Serie: {serial_number}", font=("Segoe UI", 14), foreground="#64748b")
                    lbl_serial.pack(side=TOP, pady=(0, 8))
                    lbl_serial.bind("<Button-1>", lambda e, n=name: select_sensor(n))
                    lbl_serial.tag = "serial"

                # Indicador Estado
                lbl_status = ttk.Label(content_frame, text="Clicar para selecionar", font=("Segoe UI", 12))
                lbl_status.pack(side=BOTTOM, pady=(0, 20))
                lbl_status.bind("<Button-1>", lambda e, n=name: select_sensor(n))

                btn_frame.sensor_name = name
                lbl_name.tag = "name"
                lbl_status.tag = "status"
                inner_container.columnconfigure(col, weight=1)
                col += 1
                if col >= MAX_COLS:
                    col = 0
                    row += 1

            # Metodo para resaltar seleccionado
            self._update_sensor_buttons_visuals(inner_container)

            # === BOTONES DE ACCION ===
            action_frame = ttk.Frame(parent)
            # Reduce vertical padding to keep bottom dialog action buttons visible on smaller screens
            action_frame.pack(fill=X, pady=self.scaled(6))

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

            # Nota: crearemos el botón INICIAR después de medir los botones secundarios
            # Se definió la función start_calibration_action arriba; la usaremos al crear INICIAR.

            # Frame para los botones de Exportar/Importar que deben estar debajo de INICIAR
            below_frame = ttk.Frame(action_frame)
            # Colocar el contenedor con ancho completo y luego centrar internamente los botones
            # Mantener separación vertical moderada para evitar empujar los botones de acción abajo
            below_frame.pack(fill=X, pady=(0, self.scaled(20)))

            # Subframe centrado que contiene los botones para evitar que se corten
            # No lo empaquetamos todavía: primero crearemos los botones, mediremos y luego empaquetaremos
            center_buttons = ttk.Frame(below_frame)

            # Determinar ancho en 'caracteres' escalado para los botones secundarios
            try:
                width_chars = max(12, int(24 * self.scale))
            except Exception:
                width_chars = 24

            # Mantener dimensiones consistentes para los botones secundarios
            secondary_ipady = self.scaled(8)
            secondary_padx = 0
            secondary_pady = (0, 0)

            # Botón EXPORTAR CURVAS (CSV)
            def export_curves_csv():
                import os, json, csv
                from tkinter import filedialog
                calib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'calibrations')
                files = [f for f in os.listdir(calib_dir) if f.endswith('.json')]
                data = {}
                pesos = set()
                for fname in files:
                    serial = fname.replace('.json','')
                    with open(os.path.join(calib_dir, fname), 'r', encoding='utf-8') as f:
                        puntos = json.load(f)
                        for p in puntos:
                            pesos.add(p['weight'])
                        data[serial] = {p['weight']: p['reading'] for p in puntos}
                pesos = sorted(pesos)
                serials = sorted(data.keys())
                # Diálogo para elegir ubicación y nombre del archivo
                out_path = None
                try:
                    # Usar dialogo con parent si existe para evitar que la ventana de config se vaya al fondo
                    if config_dialog:
                        out_path = filedialog.asksaveasfilename(
                            parent=config_dialog,
                            title="Exportar curvas de calibración",
                            defaultextension=".csv",
                            filetypes=[("Archivos CSV", "*.csv")],
                            initialdir=calib_dir,
                            initialfile="curvas_celdas.csv"
                        )
                    else:
                        out_path = filedialog.asksaveasfilename(
                            title="Exportar curvas de calibración",
                            defaultextension=".csv",
                            filetypes=[("Archivos CSV", "*.csv")],
                            initialdir=calib_dir,
                            initialfile="curvas_celdas.csv"
                        )
                finally:
                    # Siempre intentar restaurar la ventana de configuración
                    if config_dialog:
                        try:
                            config_dialog.lift()
                            config_dialog.focus_force()
                        except Exception:
                            pass
                if not out_path:
                    return
                with open(out_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Carga Real'] + serials)
                    for peso in pesos:
                        row = [peso] + [data[s].get(peso, '') for s in serials]
                        writer.writerow(row)

                # Restaurar ventana de configuración si existe
                if config_dialog:
                    try:
                        config_dialog.lift()
                        config_dialog.focus_force()
                    except Exception:
                        pass
            # Preparar fuente y estilos para los botones de calibración (más grandes)
            try:
                # Slightly smaller font for calibration buttons to save vertical space
                btn_font = ("Segoe UI", self.scaled_font(20), 'bold')
            except Exception:
                btn_font = ("Segoe UI", 20, 'bold')

            # Crear estilos específicos para los botones de calibración que incluyan la fuente y padding
            try:
                # Reduce padding to avoid pushing bottom dialog buttons off-screen
                self.style.configure('Calib.Info.TButton', font=btn_font, padding=(self.scaled(10), self.scaled(8)))
                self.style.configure('Calib.Secondary.TButton', font=btn_font, padding=(self.scaled(10), self.scaled(8)))
                self.style.configure('Calib.Start.TButton', font=("Segoe UI", self.scaled_font(24), 'bold'), padding=(self.scaled(12), self.scaled(10)))
                # Main unified style for both primary calibration actions
                self.style.configure('Calib.Main.TButton', font=("Segoe UI", self.scaled_font(22), 'bold'), padding=(self.scaled(12), self.scaled(10)))
            except Exception:
                pass

            # Crear función modal de import/export que muestre SOLO tres botones grandes
            def show_import_export_choice_calib():
                dlg = ttk.Toplevel(self)
                dlg.overrideredirect(True)
                dlg.transient(self)

                dlg.resizable(False, False)
                dlg.lift()
                dlg.attributes('-topmost', True)

                # Use the same bordered dialog structure as show_large_confirmation
                outer_frame = ttk.Frame(dlg, bootstyle="dark", padding=4)
                outer_frame.pack(fill=BOTH, expand=YES)

                frame = ttk.Frame(outer_frame, padding=40)
                frame.pack(fill=BOTH, expand=YES)

                # Row: IMPORTAR | EXPORTAR
                row_frame = ttk.Frame(frame)
                row_frame.pack(fill=X)
                row_frame.columnconfigure(0, weight=1)
                row_frame.columnconfigure(1, weight=1)

                def do_import():
                    try:
                        dlg.destroy()
                        self.import_calibrations_gui(parent=config_dialog)
                    except Exception:
                        pass

                def do_export():
                    try:
                        dlg.destroy()
                        export_curves_csv()
                    except Exception:
                        pass

                # Import/Export side by side with a small horizontal gap
                btn_import = ttk.Button(row_frame, text="IMPORTAR", bootstyle="info", command=do_import)
                btn_import.grid(row=0, column=0, sticky='ew', padx=(0, 8), ipadx=12, ipady=self.scaled(16))
                try:
                    btn_import.configure(style='Large.info.TButton')
                except Exception:
                    pass

                btn_export = ttk.Button(row_frame, text="EXPORTAR", bootstyle="success", command=do_export)
                btn_export.grid(row=0, column=1, sticky='ew', padx=(8, 0), ipadx=12, ipady=self.scaled(16))
                try:
                    btn_export.configure(style='Large.success.TButton')
                except Exception:
                    pass

                # Cancel full width below; match spacing of confirmation dialog
                cancel_frame = ttk.Frame(frame)
                cancel_frame.pack(fill=X, pady=(16, 0))
                btn_cancel = ttk.Button(cancel_frame, text="CANCELAR", bootstyle="danger", command=dlg.destroy)
                try:
                    btn_cancel.configure(style='Large.danger.TButton')
                except Exception:
                    pass
                btn_cancel.pack(fill=X, ipadx=12, ipady=self.scaled(18))

                # Calculate minimal required size and center the dialog
                try:
                    dlg.update_idletasks()
                    req_w = outer_frame.winfo_reqwidth()
                    req_h = outer_frame.winfo_reqheight()
                    margin_x = self.scaled(24)
                    margin_y = self.scaled(12)
                    final_w = max(req_w + margin_x, self.scaled(420))
                    final_h = req_h + margin_y
                    sx = self.winfo_screenwidth()
                    sy = self.winfo_screenheight()
                    x = max(0, (sx - final_w) // 2)
                    y = max(0, (sy - final_h) // 2)
                    dlg.geometry(f"{final_w}x{final_h}+{x}+{y}")
                except Exception:
                    pass

                try:
                    dlg.grab_set()
                except Exception:
                    pass

            # Single combined button to open the import/export modal (moved to calibration section)
            btn_imp_exp = ttk.Button(
                center_buttons,
                text=" IMPORTAR / EXPORTAR ",
                bootstyle="secondary",
                command=show_import_export_choice_calib
            )
            btn_imp_exp.configure(style='Calib.Main.TButton')

            # Configurar grid: INICIAR en la fila 0 (colspan=2), export/import en fila 1
            center_buttons.grid_columnconfigure(0, weight=1)
            center_buttons.grid_columnconfigure(1, weight=1)

            btn_start = ttk.Button(
                center_buttons,
                text=" INICIAR CALIBRAÇÃO ",
                bootstyle="warning",
                command=start_calibration_action
            )
            # Ensure the warning bootstyle is applied and keep our custom Calib.Start style
            btn_start.configure(style='Calib.Main.TButton', bootstyle='warning')

            # Colocar los dos botones en la misma fila, con separación consistene
            btn_start.grid(row=0, column=0, padx=(0, self.scaled(12)), pady=(0, self.scaled(8)), sticky='ew')
            btn_imp_exp.grid(row=0, column=1, padx=(self.scaled(12), 0), pady=(0, self.scaled(8)), sticky='ew')

            # Empacar el contenedor para ocupar todo el ancho y alinear cada botón
            # Usar el mismo padding horizontal que las tarjetas de sensor para que coincida visualmente
            center_buttons.pack(fill=X, pady=(self.scaled(8), 0), padx=15)

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
        
        # APLICAR CONSTANTES DE COLOR (usar antes de configurar estilos)
        PRIMARY = "#2563eb"
        BG_CARD = "#ffffff"
        TEXT_MAIN = "#1e293b"
        TEXT_MUTED = "#64748b"

        # Preparar estilos (fallback silencioso si style no existe)
        try:
            # Marcos: el estilo intenta definir borde/relief, pero muchos temas lo ignoran,
            # por eso también aplicamos un fallback directo a los widgets más abajo.
            self.style.configure('Card.TFrame', background=BG_CARD, relief='solid', borderwidth=1)
            self.style.configure('SelectedCard.TFrame', background=COLOR_SELECTED_BG, relief='solid', borderwidth=2)
            # Labels: preferimos configurar foreground directamente en los widgets
        except Exception:
            pass

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
                try: widget.configure(style='SelectedCard.TFrame')
                except: pass
                if content_frame:
                    try: content_frame.configure(style='SelectedCard.TFrame')
                    except: pass
                # Forzar color de fondo y borde visible (fallback si el tema no pinta el frame)
                try:
                    widget.configure(background=COLOR_SELECTED_BG, relief='solid', borderwidth=3,
                                     highlightthickness=2, highlightbackground=COLOR_SELECTED_BG)
                except Exception:
                    pass
                try:
                    content_frame.configure(background=COLOR_SELECTED_BG)
                except Exception:
                    pass
                for sub in content_frame.winfo_children():
                    if isinstance(sub, ttk.Label):
                        # Aplica estilos personalizados según el tipo de label
                        try:
                            if hasattr(sub, 'tag') and sub.tag == "name":
                                sub.configure(foreground=COLOR_SELECTED_FG, font=("Segoe UI", self.scaled_font(26), 'bold'), background=COLOR_SELECTED_BG)
                            elif hasattr(sub, 'tag') and sub.tag == "serial":
                                sub.configure(foreground=COLOR_SELECTED_FG, font=("Segoe UI", self.scaled_font(14)), background=COLOR_SELECTED_BG)
                            elif hasattr(sub, 'tag') and sub.tag == "status":
                                sub.configure(foreground=COLOR_SELECTED_FG, font=("Segoe UI", self.scaled_font(12), 'bold'), background=COLOR_SELECTED_BG)
                        except Exception:
                            pass
                if lbl_status:
                    lbl_status.configure(text="SELECIONADO")
            else:
                # == NORMAL / NO SELECCIONADO ==
                try: widget.configure(style='Card.TFrame')
                except: pass
                if content_frame:
                    try: content_frame.configure(style='Card.TFrame')
                    except: pass
                # Restaurar fondo y aplicar borde leve para delimitar la tarjeta
                try:
                    widget.configure(background=BG_CARD, relief='solid', borderwidth=1,
                                     highlightthickness=1, highlightbackground="#e2e8f0")
                except Exception:
                    pass
                try:
                    content_frame.configure(background=BG_CARD)
                except Exception:
                    pass
                for sub in content_frame.winfo_children():
                    if isinstance(sub, ttk.Label):
                        # Aplica estilos normales (evitar configurar 'background' en ttk.Label)
                        try:
                            if hasattr(sub, 'tag') and sub.tag == "name":
                                sub.configure(foreground=TEXT_MAIN, font=("Segoe UI", self.scaled_font(26), "bold"), background=BG_CARD)
                            elif hasattr(sub, 'tag') and sub.tag == "serial":
                                sub.configure(foreground=TEXT_MUTED, font=("Segoe UI", self.scaled_font(14)), background=BG_CARD)
                            elif hasattr(sub, 'tag') and sub.tag == "status":
                                sub.configure(foreground=TEXT_MUTED, font=("Segoe UI", self.scaled_font(12)), background=BG_CARD)
                        except Exception:
                            pass
                if lbl_status:
                    lbl_status.configure(text="Clicar para selecionar")
    
    def _open_calibration_wizard(self, current_config, sensor_name_override=None, config_dialog=None):
        """
        Wizard de Calibração Avançado.
        Permite entrada manual ou captura, múltiplos pontos, e seleção de curva.
        """
        # Permitir abrir el asistente aunque no haya data_processor conectado
        if not self.data_processor:

            # Crear un mock mínimo para permitir cargar puntos
            class DummyDP:
                def get_last_total_raw(self):
                    return 0
                nodos_config = {}
            self.data_processor = DummyDP()

        # Guardar referencia al diálogo de config para restaurar grab
        self._config_dialog_ref = config_dialog

        # Obtener celda y serial para persistencia
        from modules.calibration import CalibrationManager
        celda_id = None
        serial = None
        if hasattr(self, '_cal_sensor_selected'):
            internal_name = self._cal_sensor_selected.get()
            if internal_name.startswith("celda_"):
                celda_id = internal_name.split("_")[-1]
            # Buscar serial en config
            try:
                if hasattr(self.data_processor, 'nodos_config'):
                    nodos_cfg = self.data_processor.nodos_config
                    if internal_name in nodos_cfg:
                        serial = nodos_cfg[internal_name].get('serial', None)
            except Exception:
                pass


        self._cal_manager = CalibrationManager(self.data_processor, celda_id=celda_id, serial=serial)
        # Forzar recarga de puntos desde disco
        self._cal_manager.load_points()
        # Mostrar si existe el archivo de calibración
        try:
            path = self._cal_manager._get_csv_path()
            if path and os.path.exists(path):
                pass
        except Exception:
            pass

        # Debug: imprimir puntos cargados

        # ...existing code...
        # (mover refresco de tabla y gráfico al final del método, después de crear los widgets)

        # Variables UI
        self._cal_method_var = tk.StringVar(value="Linear (y=mx+b)")
        self._cal_unit_var = tk.StringVar(value="Bits (Raw)")
        self._cal_input_weight = tk.StringVar(value="")
        self._cal_input_reading = tk.StringVar(value="")
        self._cal_wizard_active = True

        # Crear Ventana - Pantalla completa con estado fullscreen
        wizard = ttk.Toplevel(self)
        # Obtener número de celda y número de serie para mostrar en el título
        celda_num = "?"
        serial_num = "?"
        if hasattr(self, '_cal_sensor_selected'):
            internal_name = self._cal_sensor_selected.get()
            # Buscar número de celda (asume formato 'celda_X')
            if internal_name.startswith("celda_"):
                celda_num = internal_name.split("_")[-1]
            # Buscar número de serie en la configuración de nodos_config
            try:
                if hasattr(self.data_processor, 'nodos_config'):
                    nodos_cfg = self.data_processor.nodos_config
                    if internal_name in nodos_cfg:
                        serial_num = nodos_cfg[internal_name].get('serial', '?')
            except Exception:
                pass
        wizard.title(f"Curva da Célula {celda_num} (Nº Série {serial_num})")
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
            # Obtener sensor seleccionado (nombre interno, ej. 'celda_1')
            selected = None
            if hasattr(self, '_cal_sensor_selected'):
                selected = self._cal_sensor_selected.get()

            # Priorizar lectura RAW por sensor seleccionado
            try:
                raw = 0.0
                if selected:
                    raw = float(self.data_processor.get_last_raw_for(selected))
                else:
                    raw = float(self.data_processor.get_last_total_raw())
            except Exception:
                raw = float(self.data_processor.get_last_total_raw())

            if unit == "Bits (Raw)":
                return raw

            # Si la unidad es peso (t o kg), intentar leer el valor procesado del sensor
            if unit == "t":
                try:
                    proc = getattr(self, '_last_sensor_data', None)
                    if proc and 'sensores' in proc and selected in proc['sensores']:
                        val = proc['sensores'][selected].get('valor')
                        if val is not None:
                            return val
                except Exception:
                    pass
                # Fallback: intentar convertir la lectura CRUDA a toneladas
                try:
                    raw_f = float(self.data_processor.get_last_raw_for(selected))
                except Exception:
                    try:
                        raw_f = float(raw)
                    except Exception:
                        raw_f = 0.0

                # Aplicar multiplicador/inversión por sensor (mismo comportamiento que DataProcessor)
                mult = 1.0
                try:
                    cfg = None
                    if hasattr(self.data_processor, 'nodos_config'):
                        cfg = self.data_processor.nodos_config.get(selected)
                        # Si selected no es clave directa, buscar por coincidencia
                        if cfg is None:
                            for k, v in self.data_processor.nodos_config.items():
                                if k == selected:
                                    cfg = v
                                    break
                    if cfg:
                        if 'sign' in cfg:
                            mult = float(cfg.get('sign', 1.0))
                        elif cfg.get('invert', False):
                            mult = -1.0
                except Exception:
                    mult = 1.0

                raw_applied = raw_f * mult

                # Aplicar coeficientes del sistema y convertir a toneladas
                try:
                    slope = float(getattr(self.data_processor, 'system_slope', 1.0))
                    offset = float(getattr(self.data_processor, 'system_offset', 0.0))
                    peso = (raw_applied * slope) + offset
                except Exception:
                    peso = raw_applied

                # El sistema ahora asume que las lecturas crudas y los coeficientes
                # están en toneladas; por tanto `peso` ya está en toneladas.
                try:
                    return float(peso)
                except Exception:
                    return 0.0

            if unit == "kg":
                try:
                    proc = getattr(self, '_last_sensor_data', None)
                    if proc and 'sensores' in proc and selected in proc['sensores']:
                        val = proc['sensores'][selected].get('valor')
                        if val is not None:
                            return val * 1000
                except Exception:
                    pass
                return raw

            if unit == "mV/V":
                # Conversión aproximada desde RAW bits a mV/V
                try:
                    mv_per_v = (raw / 16777216.0) * 2.5
                    return mv_per_v
                except Exception:
                    return 0.0

            # Default: raw
            return raw
            
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
            elif unit == "Bits (Raw)":
                # Preservar decimales en RAW para calibración (3 decimales)
                try:
                    self._cal_input_reading.set(f"{val:.3f}")
                except Exception:
                    self._cal_input_reading.set(f"{val:.0f}")
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
            # Guardar puntos explícitamente al finalizar
            if hasattr(self._cal_manager, 'save_points'):
                self._cal_manager.save_points()
            self.show_alert("Sucesso", f"Calibração salva com {len(sorted_points)} pontos.", "success", parent=wizard)
            close_wizard()

        # === UI LAYOUT ===
        

        # HEADER - Mejorado visualmente
        header = ttk.Frame(wizard, bootstyle="primary")
        header.pack(fill=X)

        header_inner = ttk.Frame(header, padding=(20, 15))
        header_inner.pack(fill=X)

        # Icono y título
        # Usar el mismo texto que el título de la ventana
        label_titulo = f"Curva da Célula {celda_num} (Nº Série {serial_num})"
        ttk.Label(header_inner, text=label_titulo,
                  font=("Segoe UI", 22, "bold"),
                  foreground="#1e293b").pack(side=LEFT)
        
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
        h_frame = ttk.Frame(left, bootstyle="dark", padding=8)
        h_frame.pack(fill=X)
        h_frame.columnconfigure(0, weight=1)
        h_frame.columnconfigure(1, weight=1)
        h_frame.columnconfigure(2, weight=0)
        ttk.Label(h_frame, text="PESO (t)", font=("Segoe UI", 10, "bold"), 
            bootstyle="inverse-dark", anchor="center").grid(row=0, column=0, sticky="ew")
        ttk.Label(h_frame, text="LEITURA", font=("Segoe UI", 10, "bold"),
            bootstyle="inverse-dark", anchor="center").grid(row=0, column=1, sticky="ew")
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

        # Unit selector (oculto)
        # ...existing code...

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
                self.log_message(f"Error matplotlib: {e}")
                ttk.Label(g_frame, text="Erro ao inicializar gráfico", 
                          font=("Segoe UI", 12)).pack(expand=YES)
        else:
            ttk.Label(g_frame, text="Matplotlib não disponível\nInstale com: pip install matplotlib", 
                      font=("Segoe UI", 12), justify="center").pack(expand=YES)

        # Refrescar tabla y gráfico con puntos precargados (si existen)
        self._refresh_cal_wizard_table_ui()
        self._update_cal_wizard_graph()
        # Forzar refresco visual del gráfico tras inicialización completa
        if hasattr(self, '_cal_canvas') and self._cal_canvas:
            wizard.after(300, lambda: self._update_cal_wizard_graph())
        
        # === RIGHT: Graph & Config ===
        right = ttk.Labelframe(main, text="Análise e Ajuste  ", padding=15, bootstyle="warning")
        right.grid(row=0, column=1, sticky="nsew")
        
        # Config Frame - Solo unidad
        f_cfg = ttk.Frame(right)
        f_cfg.pack(fill=X, pady=(0, 10))
        
        # Forzar método internamente (sin mostrar texto)
        self._cal_method_var.set("Interpolação Segmentos")
        
        # Unit selector
        # Sección de selección de unidad OCULTA por requerimiento. La lógica y variable se mantienen para posible uso futuro.
        # f_unit = ttk.Frame(f_cfg)
        # f_unit.pack(fill=X)
        # ttk.Label(f_unit, text="Unidade de Leitura:", font=("Segoe UI", 12)).pack(anchor="w")
        # units = ["Bits (Raw)", "mV/V", "kg", "t"]
        # ttk.Combobox(f_unit, textvariable=self._cal_unit_var, values=units, 
        #              state="readonly", font=("Segoe UI", 14)).pack(fill=X, ipady=6)
        
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

            # Peso: sin decimales si es entero, lectura: 3 decimales si no es entero
            def fmt_peso(val):
                if isinstance(val, float) and val.is_integer():
                    return f"{int(val)}"
                if isinstance(val, int):
                    return str(val)
                return f"{val:.3f}"
            def fmt_lec(val):
                if isinstance(val, float) and val.is_integer():
                    return f"{int(val)}"
                if isinstance(val, int):
                    return str(val)
                return f"{val:.3f}"

            v_w = tk.StringVar(value=fmt_peso(peso))
            v_r = tk.StringVar(value=fmt_lec(lectura))
            
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
                        try:
                            # Persist change immediately
                            if hasattr(self._cal_manager, 'save_points'):
                                self._cal_manager.save_points()
                        except Exception:
                            pass
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
            # self.log_message(f"Graficando puntos: {points}")
            if not points:
                self._cal_ax.set_title("Sem dados", fontsize=11, color='gray')
                self._cal_canvas.draw_idle()
                return

            # Ordenar puntos por valor de lectura (x)
            sorted_points = sorted(points, key=lambda p: p[1])
            x = np.array([p[1] for p in sorted_points])
            y = np.array([p[0] for p in sorted_points])

            # self.log_message(f"x (lectura): {x}")
            # self.log_message(f"y (peso): {y}")

            # Scatter - puntos más grandes y visibles
            self._cal_ax.scatter(x, y, c='#2563eb', s=80, zorder=5, edgecolors='white', linewidth=1)

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
            self.log_message(f"Erro atualizando gráfico: {e}")
