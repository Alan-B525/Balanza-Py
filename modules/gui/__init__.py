from config import APP_TITLE, APP_SIZE, THEME_NAME, NODOS_CONFIG, RECONNECT_ATTEMPTS, CONNECTION_ATTEMPT_TIMEOUT_S, load_settings, save_settings, BASE_DIR
import os
import sys
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
            self.log_message(f"Erro ao carregar sessão de calibração: {e}")

    def _load_profiles(self):
        """Carrega perfis de manutenção a partir de settings.json.
        Garante que existam exatamente 5 perfis fixos (slots)."""
        from config import load_settings, save_settings
        
        # Estructura base con keys estables
        base_profiles = {
            "slot_1": {"name": "Perfil 1", "min": 400, "max": 800},
            "slot_2": {"name": "Perfil 2", "min": 0, "max": 0},
            "slot_3": {"name": "Perfil 3", "min": 0, "max": 0},
            "slot_4": {"name": "Perfil 4", "min": 0, "max": 0},
            "slot_5": {"name": "Perfil 5", "min": 0, "max": 0}
        }
        
        data = {"profiles": base_profiles, "active_profile": "slot_1"}
        
        try:
            # Leer settings.json
            settings = load_settings()
            loaded_profs = settings.get("profiles_data", {}).get("profiles", {})
            loaded_active = settings.get("profiles_data", {}).get("active_profile")
            
            if isinstance(loaded_profs, dict):
                for k in base_profiles.keys():
                    if k in loaded_profs:
                        base_profiles[k].update(loaded_profs[k])
                
                if loaded_active and loaded_active in base_profiles:
                    data["active_profile"] = loaded_active
                    
            data["profiles"] = base_profiles
            
            # Guardar de vuelta en settings.json
            self._save_profiles(data)
            
        except Exception as e:
            print(f"Erro ao carregar perfis: {e}")
            
        return data

    def _save_profiles(self, profiles_data):
        """Salva perfis de manutenção dentro de settings.json."""
        from config import load_settings, save_settings
        try:
            settings = load_settings()
            settings["profiles_data"] = profiles_data
            save_settings(settings)
            return True
        except Exception as e:
            print(f"Erro ao salvar perfis: {e}")
            return False

    def _get_active_profile_limits(self):
        """Retorna os limites (min, max) do perfil ativo ou None."""
        data = self._load_profiles()
        active_name = data.get("active_profile")
        if active_name and active_name in data.get("profiles", {}):
            return data["profiles"][active_name]
        return None

    def __init__(self, data_queue, command_queue, data_processor=None):
        super().__init__(themename=THEME_NAME)
        self.data_processor = data_processor
        self.title(APP_TITLE)

        real_screen_width = self.winfo_screenwidth()
        real_screen_height = self.winfo_screenheight()

        # Mostrar la ventana ocupando 50% del ancho (centrada) y 100% del alto (barra superior visible)
        try:
            # 50% del ancho y 90% de la altura (reducido 10%) centrado verticalmente
            desired_w = max(300, int(real_screen_width * 0.5))
            desired_h = max(200, int(real_screen_height * 0.9))
            x = (real_screen_width - desired_w) // 2
            y = (real_screen_height - desired_h) // 2
            # Asegurar decorations visibles (no overredirect)
            try:
                if getattr(self, 'overrideredirect', None):
                    self.overrideredirect(False)
            except Exception:
                pass
            self.geometry(f"{desired_w}x{desired_h}+{x}+{y}")
        except Exception:
            try:
                self.state("zoomed")
            except Exception:
                self.geometry(f"{real_screen_width}x{real_screen_height}+0+0")
        except Exception:
            try:
                self.state("zoomed")
            except Exception:
                self.geometry(f"{real_screen_width}x{real_screen_height}+0+0")

        self._calculate_scale_factors(real_screen_width, real_screen_height)
        # Si la app corre en una PC normal (no tablet), reducir ligeramente las fuentes
        try:
            if real_screen_width >= 1024 and not (real_screen_width == 1280 and real_screen_height == 800):
                # Comprimir la escala de fuentes un 10% para evitar tamaños excesivos
                self.font_scale = max(0.7, self.font_scale * 0.9)
        except Exception:
            pass
        
        # Guardar referencia para mover ventana (drag)
        self._drag_data = {"x": 0, "y": 0}
        
        self.data_queue = data_queue
        self.command_queue = command_queue
        
        self.connected = False
        
        # Almacenar ltimos datos para calibracin
        self._last_sensor_data = {}
        
        # Último timestamp visto por widget para cada sensor (mantener display hasta nueva muestra)
        self._widget_last_seen = {}
        # Último timestamp visto para el total (mantener total hasta nueva muestra)
        self._widget_last_total = 0.0
        
        # Control de visualización de decimales (por defecto: SIN decimales)
        self._show_decimals = False

        
        # Variables para conexin asncrona
        self._connection_thread = None
        self._cancel_connection = False
        # Límite de mensajes procesados por tick para evitar congelar la UI
        self._gui_max_msgs_per_tick = 40
        # Grace period after successful connection (seconds) to wait for sensors to send data
        self._post_connect_grace_s = 6.0
        self._conn_success_time = 0.0
        # Indica si ya recibimos la primera muestra tras conectar
        self._first_sample_received = False
        # Throttle de logs repetidos para reducir I/O de disco en ráfagas
        self._last_log_message = None
        self._last_log_ts = 0.0
        # Cola y hilo daemon para escribir logs sin bloquear el hilo GUI
        import queue as _queue_mod
        import threading as _threading_mod
        self._log_write_queue = _queue_mod.Queue()
        def _log_writer_worker():
            import datetime, os
            try:
                import config as _cfg_mod
                log_path = os.path.join(_cfg_mod.get_writable_dir(), 'log.log')
            except Exception:
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'log.log')
            while True:
                try:
                    entry = self._log_write_queue.get()
                    if entry is None:
                        break
                    try:
                        with open(log_path, 'a', encoding='utf-8') as _f:
                            _f.write(entry)
                    except Exception:
                        pass
                    finally:
                        self._log_write_queue.task_done()
                except Exception:
                    pass
        _t = _threading_mod.Thread(target=_log_writer_worker, daemon=True, name="LogWriter")
        _t.start()
        
        # Handle window close event
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        
        # Iniciar maximizado (con barra de título visible)
        try:
            self.state('zoomed')
        except Exception:
            self.attributes('-zoomed', True)
        
        self._configure_styles()
        self._setup_ui()
        
        # Start update loop
        self.after(70, self.actualizar_gui)
        
        # Iniciar conexión automática al arrancar (mostrar diálogo de conexión)
        try:
            # Lanzar tras breve retardo para permitir que la UI termine de inicializar
            self.after(500, self._auto_connect_on_startup)
        except Exception:
            pass
    
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

    def _apply_window_icon(self, window):
        """Aplica icono de la app a ventanas con barra de título."""
        try:
            assets_path = os.path.join(BASE_DIR, "assets")
            ico_path = os.path.join(assets_path, "icon.ico")
            png_path = os.path.join(assets_path, "icon.png")

            applied = False
            if os.path.exists(ico_path):
                try:
                    window.iconbitmap(ico_path)
                    applied = True
                except Exception:
                    applied = False

            if not applied and os.path.exists(png_path):
                try:
                    if not hasattr(self, '_window_icon_photo') or self._window_icon_photo is None:
                        self._window_icon_photo = tk.PhotoImage(file=png_path)
                    window.iconphoto(False, self._window_icon_photo)
                except Exception:
                    pass
        except Exception:
            pass

    def _center_toplevel(self, window, width, height):
        """Centra una ventana con tamaño fijo de forma robusta."""
        try:
            sw = int(self.winfo_screenwidth())
            sh = int(self.winfo_screenheight())
            x = max(0, (sw - int(width)) // 2)
            y = max(0, (sh - int(height)) // 2)
            window.geometry(f"{int(width)}x{int(height)}+{x}+{y}")
        except Exception:
            try:
                window.geometry(f"{int(width)}x{int(height)}+100+100")
            except Exception:
                pass

    def _fit_label_font(self, label, text, family, max_size, min_size=8, weight='bold', explicit_width=None):
        """Ajusta el tamaño de fuente de `label` para que `text` quepa en su ancho disponible.

        - `explicit_width`: si se proporciona (en píxeles), se usa en lugar de medir el widget.
        """
        try:
            import tkinter.font as tkfont
            # Si el label tiene un estilo configurado, intentar extraer la tipografía real del estilo
            style_name = label.cget('style')
            style_font_family = family
            if style_name:
                try:
                    style_font = self.style.lookup(style_name, 'font')
                    if style_font:
                        if isinstance(style_font, str):
                            parts = style_font.split()
                            if parts:
                                style_font_family = parts[0].strip('{}')
                        elif isinstance(style_font, (list, tuple)) and len(style_font) > 0:
                            style_font_family = style_font[0]
                except Exception:
                    pass
            family = style_font_family

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
        
        # Fonts - Escalados según resolución (unificar tipografías)
        FONT_MAIN = "Segoe UI"
        FONT_MONO = "Segoe UI"
        FONT_NUMBERS = "Segoe UI"
        
        # Función helper local para escalar fuentes
        sf = self.scaled_font
        
        # Configure TFrame styles
        self.style.configure('Body.TFrame', background=BG_BODY)
        self.style.configure('Card.TFrame', background=BG_CARD, relief="solid", borderwidth=1)
        self.style.configure('CardNoBorder.TFrame', background=BG_CARD)
        
        # Configure Label styles - Escalados
        self.style.configure('CardTitle.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(16), "bold"))
        self.style.configure('CardValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_NUMBERS, sf(40), "bold"))
        self.style.configure('Unit.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(18)))
        self.style.configure('SensorStatus.TLabel', background=BG_CARD, foreground=SUCCESS, font=(FONT_MAIN, sf(13), "bold"))
        
        # Total Panel - MUY PROMINENTE para nfasis mximo
        self.style.configure('TotalPanel.TFrame', background=PRIMARY)
        # Ajustes para mostrar un único valor grande (modo single-node)
        # Reducir ligeramente las fuentes para un PC normal (no tablet)
        self.style.configure('TotalLabel.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, sf(30), "bold"))
        # Valor principal: fuente grande pero comprimida
        self.style.configure('TotalValue.TLabel', background=PRIMARY, foreground="white", font=(FONT_NUMBERS, sf(94), "bold"))
        # Unidad: tamaño grande pero menor que el valor
        self.style.configure('TotalUnit.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, sf(32), "bold"))
        # Ticks de la barra
        self.style.configure('TotalTick.TLabel', background=PRIMARY, foreground="white", font=(FONT_MAIN, sf(12), "bold"))
        
        # Total Panel DANGER - Cuando hay sensor desconectado (ROJO)
        # IMPORTANTE: usar mismos tamaños de fuente que los estilos normales
        # para evitar reflow/parpadeo al cambiar entre estados.
        self.style.configure('TotalPanelDanger.TFrame', background=DANGER)
        self.style.configure('TotalLabelDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MAIN, sf(30), "bold"))
        self.style.configure('TotalValueDanger.TLabel', background=DANGER, foreground="white", font=(FONT_NUMBERS, sf(94), "bold"))
        self.style.configure('TotalUnitDanger.TLabel', background=DANGER, foreground="white", font=(FONT_MAIN, sf(32), "bold"))
        
        # Tara Info - Más visible
        self.style.configure('TareInfo.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(14), "bold"))
        # Estilo centrado para el indicador de TARA (título) — usar fondo PRIMARY para integrarlo
        self.style.configure('TareCenter.TLabel', background=PRIMARY, foreground='white', font=(FONT_MAIN, sf(16), 'bold'))
        # Estilo de valor de Tara (monoespaciado, BOLD) — integrado con fondo PRIMARY
        self.style.configure('TareValue.TLabel', background=PRIMARY, foreground='white', font=(FONT_MONO, sf(36), 'bold'))
        # Estilos específicos para la sección de Tara dentro de MANUTENÇÃO (fondo blanco, texto negro)
        self.style.configure('TareMaint.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MAIN, sf(14), 'bold'))
        self.style.configure('TareMaintValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MONO, sf(24), 'bold'))
        # Ángulo (card secundaria)
        self.style.configure('AngleCard.TFrame', background=BG_CARD, relief="solid", borderwidth=1)
        self.style.configure('AngleTitle.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MAIN, sf(36), "bold"))
        self.style.configure('AngleValue.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_NUMBERS, sf(36), "bold"))
        self.style.configure('AngleTile.TFrame', background='#eef2ff', relief='solid', borderwidth=1)
        self.style.configure('AngleTileTitle.TLabel', background='#eef2ff', foreground=TEXT_MUTED,
                             font=(FONT_MAIN, sf(16), 'bold'))
        self.style.configure('AngleTileValue.TLabel', background='#eef2ff', foreground='#1e1b4b',
                             font=(FONT_NUMBERS, sf(34), 'bold'))
        
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
        self.style.configure('Large.secondary.Outline.TButton', font=(FONT_MAIN, sf(18), 'bold'))

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
        # Status Badge styles — fondo neutro, solo el LED cambia de color
        self.style.configure('StatusBadge.TFrame', background=BG_CARD, relief='flat')
        self.style.configure('StatusBadgeLabel.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(13), "bold"))
        self.style.configure('HeaderStatus.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(16), "bold"))
        # Logo label style to ensure visibility
        self.style.configure('Logo.TLabel', background=BG_CARD)

        # Botón TARA (Amarillo) — usar mismo tamaño de fuente que Header.TButton
        self.style.configure('TareYellow.TButton', 
                    font=(FONT_MAIN, sf(14), 'bold'), 
                    background=WARNING, 
                    foreground='white')
        # Efecto al presionar (amarillo más oscuro)
        self.style.map('TareYellow.TButton', background=[('active', '#d97706')]) 

        # Botón RESET (Rojo + Fuente 28)
        self.style.configure('TareRed.TButton', 
                            font=(FONT_MAIN, sf(28), 'bold'), 
                            background=DANGER, 
                            foreground='white')
        # Efecto al presionar (rojo más oscuro)
        self.style.map('TareRed.TButton', background=[('active', '#dc2626')])

        # Botones Connect - estilos dedicados para forzar color verde/rojo
        self.style.configure('ConnectSuccess.TButton', font=(FONT_MAIN, sf(14), 'bold'), background=SUCCESS, foreground='white')
        self.style.map('ConnectSuccess.TButton', background=[('active', '#16a34a')])
        self.style.configure('ConnectDanger.TButton', font=(FONT_MAIN, sf(14), 'bold'), background=DANGER, foreground='white')
        self.style.map('ConnectDanger.TButton', background=[('active', '#dc2626')])

        # Estilo para hora en footer (más grande)
        self.style.configure('FooterTime.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, sf(24), "bold"))

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
        import os, sys
        assets_path = os.path.join(BASE_DIR, "assets")

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
        
        # Header: mostrar título y estado en la parte superior (no en el footer)
        try:
            title_text = "Controle de Carga"
            title_lbl = ttk.Label(brand_frame, text=title_text, style='HeaderTitle.TLabel', font=("Segoe UI", self.scaled_font(19), "bold"))
            title_lbl.pack(side=LEFT, padx=(10, 14))

            # Agrupar estado y LEDs para una jerarquía visual más limpia
            status_frame = ttk.Frame(brand_frame, style='Header.TFrame')
            status_frame.pack(side=LEFT, padx=(0, 0))

            # --- Indicadores de estado (dots profesionales) ---
            dot_size = max(16, self.scaled(22))
            chip_pad_x = self.scaled(8)
            chip_pad_y = self.scaled(5)

            self._status_text = ttk.Label(status_frame, text="Desconectado", style='HeaderStatus.TLabel', font=("Segoe UI", self.scaled_font(18), "bold"), width=14, anchor='w')
            self._status_text.pack(side=LEFT, padx=(0, self.scaled(10)))

            led_group = ttk.Frame(status_frame, style='Header.TFrame')
            led_group.pack(side=LEFT, padx=(0, 0))

            # --- NÓ ---
            node_chip = ttk.Frame(led_group, style='Header.TFrame', padding=(chip_pad_x, chip_pad_y))
            node_chip.pack(side=LEFT, padx=(0, self.scaled(4)))

            dot = self._create_status_dot(node_chip, dot_size)
            self._status_led = dot['canvas']
            self._status_led_outer = dot['ring']
            self._status_led_inner = dot['fill']

            self._node_led_label = ttk.Label(node_chip, text="NÓ", style='StatusBadgeLabel.TLabel')
            self._node_led_label.pack(side=LEFT)

            # --- MB ---
            modbus_chip = ttk.Frame(led_group, style='Header.TFrame', padding=(chip_pad_x, chip_pad_y))
            modbus_chip.pack(side=LEFT)

            mb_dot = self._create_status_dot(modbus_chip, dot_size)
            self._modbus_status_led = mb_dot['canvas']
            self._modbus_led_outer = mb_dot['ring']
            self._modbus_led_inner = mb_dot['fill']

            self._modbus_led_label = ttk.Label(modbus_chip, text="MB", style='StatusBadgeLabel.TLabel')
            self._modbus_led_label.pack(side=LEFT)

            try:
                self._update_status_led('disconnected')
            except Exception:
                pass
            try:
                self._update_modbus_led('idle')
            except Exception:
                pass
            # Compatibilidad con código existente que usa self.lbl_status
            self.lbl_status = self._status_text
        except Exception:
            pass

        # Establecer icono de la aplicación (barra de tareas + título)
        try:
            ico_path = os.path.join(assets_path, "icon.ico")
            png_path = os.path.join(assets_path, "icon.png")
            # Preferir .ico en Windows (se ve mejor en la barra de tareas)
            if os.path.exists(ico_path):
                try:
                    # iconbitmap suele funcionar bien en Windows
                    self.iconbitmap(ico_path)
                except Exception:
                    try:
                        # Alternativa: usar wm_iconbitmap
                        self.wm_iconbitmap(ico_path)
                    except Exception:
                        pass
            elif os.path.exists(png_path) and Image is not None and ImageTk is not None:
                try:
                    pil = Image.open(png_path)
                    # Crear un iconphoto; mantener referencia para evitar GC
                    self._icon_img = ImageTk.PhotoImage(pil)
                    try:
                        self.iconphoto(True, self._icon_img)
                    except Exception:
                        try:
                            self.wm_iconphoto(True, self._icon_img)
                        except Exception:
                            pass
                except Exception:
                    pass
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
            text="0,00", 
            bootstyle="primary", 
            command=self.toggle_decimals, 
            style='Header.TButton',
            width=8,
            padding=(15, 12)
        )
        # Ocultar el botón de decimales en todas las resoluciones: no hacer pack()

        # (Export/Import moved to Config -> CALIBRACAO tab)
        
        # Botón de TARA en el header (mismo formato, color amarillo)
        try:
            self.btn_tare = ttk.Button(
                actions_frame,
                text="TARA",
                bootstyle="warning",
                command=self.do_tare,
                style='TareYellow.TButton',
                width=14,
                padding=(15, 12)
            )
            self.btn_tare.pack(side=LEFT, padx=5)
        except Exception:
            pass

        # Botn de Configuracin - Color info (azul)
        self.btn_config = ttk.Button(
            actions_frame, 
            text="CONFIG", 
            bootstyle="info", 
            command=self.show_configuration_dialog, 
            style='Header.TButton',
            width=14,
            padding=(15, 12)
        )
        self.btn_config.pack(side=LEFT, padx=5)
        
        # Botn Conectar/Desconectar - Color success (verde)
        self.btn_connect = ttk.Button(
            actions_frame,
            text="CONECTAR",
            command=self.toggle_connection,
            style='ConnectSuccess.TButton',
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
        # Removed as requested
        # ttk.Separator(main_container, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))

        # Footer frame fijo (creado antes del grid central para garantizar visibilidad en pantallas pequeñas)
        try:
            footer_frame = ttk.Frame(main_container, style='Header.TFrame')
            footer_frame.pack(side=BOTTOM, fill=X, pady=(4, 4))

            # Caja para título + estado (alineados a la izquierda)
            footer_left = ttk.Frame(footer_frame, style='CardNoBorder.TFrame')
            footer_left.pack(side=LEFT, anchor='w', padx=(12, 6), pady=(6, 4))

            # Título del sistema (mostrar en el pie)
            try:
                from config import APP_TITLE
            except Exception:
                APP_TITLE = "Controle de Carga"
            try:
                # No mostrar título duplicado aquí; mantener compatibilidad con self.lbl_status
                # Si no existe self.lbl_status (header), crear una referencia mínima sin pack.
                if not hasattr(self, 'lbl_status'):
                    if hasattr(self, '_status_text'):
                        self.lbl_status = self._status_text
                    else:
                        self.lbl_status = ttk.Label(footer_left, text="Desconectado", style='HeaderSub.TLabel')
                # No reempacar ni reparentar para evitar mover widgets del header.
            except Exception:
                pass

            # Cargar ambos logos en el footer con el mismo tamaño
            try:
                try:
                    footer_logo_h = self.scaled(48)
                except Exception:
                    footer_logo_h = 48

                # Cargar solo el logo principal (logo.png) en el footer
                try:
                    logo_path = os.path.join(assets_path, "logo.png")
                    self.footer_logo_img = load_logo(logo_path, footer_logo_h)
                    if self.footer_logo_img:
                        logo_lbl = ttk.Label(footer_frame, image=self.footer_logo_img, style='Logo.TLabel')
                        logo_lbl.pack(side=RIGHT, padx=(0, 12), pady=(6, 6))
                    # Reloj en footer (alineado a la derecha, antes del logo)
                    try:
                        self.footer_time = ttk.Label(footer_left, text="", style='FooterTime.TLabel')
                        self.footer_time.pack(side=LEFT, padx=(6, 12), pady=(6, 6))
                        # Iniciar actualización periódica
                        try:
                            self._update_footer_time()
                        except Exception:
                            pass
                    except Exception:
                        self.footer_time = None
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            footer_frame = None

        # =====================================================================
        # GRID CENTRAL: LOAD (Value + Bar) & ANGLE
        # =====================================================================
        grid_area = ttk.Frame(main_container, style='Body.TFrame')
        grid_area.pack(fill=BOTH, expand=YES)
        
        # Single column centered
        grid_area.columnconfigure(0, weight=1)
        # Give Equal weight to both sections for better distribution
        grid_area.rowconfigure(0, weight=1) # Load Section
        grid_area.rowconfigure(1, weight=1) # Angle Section

        # --- SECCIÓN CARGA (MAIN) ---
        # Reduced padding to 10 to save space
        load_card = ttk.Frame(grid_area, style='TotalPanel.TFrame', padding=self.scaled(10))
        load_card.grid(row=0, column=0, sticky="nsew", padx=20, pady=(5, 5))
        
        # Guardar referencia para cambiar color (aunque TotalPanel ya es azul)
        self.total_section = load_card
        
        # Título
        self.lbl_total_title = ttk.Label(load_card, text="CARGA", style='TotalLabel.TLabel')
        self.lbl_total_title.pack(pady=(5, 2))
        
        # Container for centering horizontal content (Value + Unit)
        load_center_frame = ttk.Frame(load_card, style='TotalPanel.TFrame')
        load_center_frame.pack(expand=YES, fill=BOTH)
        
        # Layout: 3 columnas — spacer | número | kg + spacer
        # uniform="spacer" fuerza cols 0 y 2 al mismo ancho → número centrado exacto
        load_center_frame.columnconfigure(0, weight=1, uniform="spacer")
        load_center_frame.columnconfigure(1, weight=0)
        load_center_frame.columnconfigure(2, weight=1, uniform="spacer")
        load_center_frame.rowconfigure(0, weight=1)

        # Valor Numérico Grande — centrado (columna 1, tamaño natural)
        self.lbl_total = ttk.Label(load_center_frame, text="0", style='TotalValue.TLabel')
        self.lbl_total.grid(row=0, column=1)
        
        # Unidad "kgf" justo después del número (columna 2, pegada a la izquierda)
        self.lbl_total_unit = ttk.Label(load_center_frame, text="kgf", style='TotalUnit.TLabel')
        self.lbl_total_unit.grid(row=0, column=2, sticky='sw', padx=(self.scaled(8), 0), pady=(0, self.scaled(12)))

        # --- BARRA DE COLOR (0 - 1200) ---
        try:
            bar_height = self.scaled(50) # Increased height
        except Exception:
            bar_height = 50
            
        # Aumentar espacio vertical para la barra
        self.load_bar_canvas = tk.Canvas(load_card, height=bar_height, bg="#e2e8f0", highlightthickness=2, highlightbackground="#475569")
        self.load_bar_canvas.pack(fill=X, padx=40, pady=(20, 10)) # More top padding
        
        # Rectángulo de llenado inicial
        try:
            self._load_bar_fill = self.load_bar_canvas.create_rectangle(0, 0, 0, bar_height, fill="#2563eb", width=0)
        except Exception:
            self._load_bar_fill = None
        # Borde visible de la barra (rectángulo completo)
        try:
            self._load_bar_border = self.load_bar_canvas.create_rectangle(0, 0, 0, bar_height, outline="#475569", width=2)
        except Exception:
            self._load_bar_border = None
        
        # Escala / Ticks
        ticks_frame = ttk.Frame(load_card, style='TotalPanel.TFrame')
        ticks_frame.pack(fill=X, padx=40, pady=(0, 20)) # More bottom padding
        
        # Ticks: 0, 200, 400 ... 1200
        # Usar grid evita artefactos de render subpíxel en el centro (ej. "600")
        tick_values = list(range(0, 1201, 200))
        for idx in range(len(tick_values)):
            try:
                ticks_frame.columnconfigure(idx, weight=1)
            except Exception:
                pass

        for idx, value in enumerate(tick_values):
            lbl = ttk.Label(ticks_frame, text=str(value), style='TotalTick.TLabel')
            sticky = 'n'
            if idx == 0:
                sticky = 'nw'
            elif idx == len(tick_values) - 1:
                sticky = 'ne'
            lbl.grid(row=0, column=idx, sticky=sticky)
        
        # Espacio para los ticks - Aumentado
        try:
            ticks_frame.rowconfigure(1, minsize=self.scaled(40))
        except Exception:
            pass

        # --- SECCIÓN ÁNGULO (REEMPLAZA TARA) ---
        # Aumentar padding vertical drásticamente para evitar cortes
        # Change sticky to nsew to fill the allotted vertical space from rowconfigure
        # --- SECCIÓN ÁNGULO (REEMPLAZA TARA) ---
        # Aumentar padding vertical drásticamente para evitar cortes
        # Change sticky to nsew to fill the allotted vertical space from rowconfigure
        # Use CardNoBorder to remove unwanted lines
        angle_card = ttk.Frame(grid_area, style='AngleCard.TFrame', padding=self.scaled(6))
        angle_card.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 5))

        # Mosaico de ângulos — sem título superior, centralizado, fonte maior
        tiles_frame = ttk.Frame(angle_card, style='CardNoBorder.TFrame')
        tiles_frame.pack(expand=True, fill=BOTH, pady=4)

        for col in range(5):
            tiles_frame.columnconfigure(col, weight=1, uniform="group_angles")
        tiles_frame.rowconfigure(0, weight=1)

        self.lbl_angles = []
        for idx in range(5):
            tile = ttk.Frame(tiles_frame, style='AngleTile.TFrame', padding=(self.scaled(10), self.scaled(8)))
            tile.grid(row=0, column=idx, padx=5, pady=5, sticky='nsew')
            tile.columnconfigure(0, weight=1)
            tile.rowconfigure(0, weight=1)
            tile.rowconfigure(1, weight=2)

            ttk.Label(
                tile,
                text=f"Ângulo {idx + 1}",
                style='AngleTileTitle.TLabel',
                anchor='center',
                width=10
            ).grid(row=0, column=0, sticky='ew', pady=(2, 0))

            value_lbl = ttk.Label(
                tile,
                text="0,0°",
                style='AngleTileValue.TLabel',
                anchor='center',
                width=10
            )
            value_lbl.grid(row=1, column=0, sticky='nsew', pady=(0, 4))
            self.lbl_angles.append(value_lbl)

        self.lbl_angle = None
        
        # Clean up old refs to avoid errors
        self.lbl_viga1_sum = None
        self.lbl_viga2_sum = None
        self.lbl_left_sum = None
        self.lbl_right_sum = None
        # Inicializar diccionario vacío de widgets de sensores individuales
        self.sensor_widgets = {}
        # Valor actual de tara conocida (toneladas)
        self._current_tare = 0.0
        # -------------------------------------------------------------
        # Sección principal: CONTROL DE TARA (debajo de las tarjetas)
        # Diseño: grid con 3 columnas (botón izq | centro con título+valor | botón der)
        # -------------------------------------------------------------
        try:
            tare_frame = ttk.Frame(grid_area, style='Card.TFrame', padding=0)
            tare_frame.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=10, pady=(0, 10))
            try:
                # Ocultar la sección de TARA en la interfaz principal (botón en header)
                tare_frame.grid_remove()
            except Exception:
                pass
            try:
                tare_frame.grid_propagate(False)
            except Exception:
                pass

            # Inner panel con fondo blanco (mantener la tarjeta externa) y padding
            # Reducir espacio vertical en pantallas de laptop o mayores
            try:
                screen_w = self.winfo_screenwidth()
                screen_h = self.winfo_screenheight()
                is_laptop = (screen_w > 1280 or screen_h > 800)
            except Exception:
                is_laptop = False

            # Reducir padding interno para compactar verticalmente la sección de TARA
            inner_pad = self.scaled(6)
            if is_laptop:
                # Usar aún menos padding vertical en pantallas grandes
                inner_pad = max(1, int(self.scaled(6) * 0.7))

            tare_inner = ttk.Frame(tare_frame, style='CardNoBorder.TFrame', padding=inner_pad)
            tare_inner.pack(fill=BOTH, expand=YES)

            # Usar grid para controlar posiciones
            # Reducir los minsize laterales para que la columna central tenga más espacio
            tare_inner.columnconfigure(0, weight=0, minsize=self.scaled(80))  # columna fija izquierda
            tare_inner.columnconfigure(1, weight=1, minsize=self.scaled(220)) # columna central expansible
            tare_inner.columnconfigure(2, weight=0, minsize=self.scaled(80))  # columna fija derecha

            # Evitar que la fila se expanda verticalmente para que los botones no se estiren
            try:
                tare_inner.rowconfigure(0, weight=0)
            except Exception:
                pass

            # Botón izquierdo: TARE (amarillo sólido), diseño grande y con padding interior
            try:
                btn_tare = ttk.Button(
                    tare_inner,
                    text="TARA",
                    style="TareYellow.TButton",
                    command=self.do_tare,
                    padding=(self.scaled(20), self.scaled(12)),
                    width=12
                )
            except Exception:
                btn_tare = ttk.Button(tare_inner, text="TARA", command=self.do_tare)
            # Colocar el botón TARA en la columna central para centrarlo
            try:
                # Mostrar siempre el botón TARA (incluso en single-node)
                # Reducir el padding vertical del botón para que la sección ocupe menos altura
                btn_tare.grid(row=0, column=1, sticky='n', padx=self.scaled(10), pady=(self.scaled(8), self.scaled(8)))
                self.btn_tare_main = btn_tare
            except Exception:
                try:
                    btn_tare.grid(row=0, column=1, sticky='nsew', padx=0, pady=0)
                    self.btn_tare_main = btn_tare
                except Exception:
                    self.btn_tare_main = None

            # Botón derecho: RESET (rojo), consistente en tamaño y padding
            try:
                btn_reset = ttk.Button(
                    tare_inner,
                    text="RESET",
                    style='TareRed.TButton',
                    command=self.reset_tare,
                    padding=(self.scaled(30), self.scaled(8)),
                    width=4
                )
            except Exception:
                btn_reset = ttk.Button(tare_inner, text="RESET", command=self.reset_tare)
            # Ocultar el botón RESET en la vista principal (se crea pero no se muestra)
            self.btn_reset_tare_main = btn_reset

            # Centro: volver a añadir título pequeño de estado y 'Tara Aplicada' + valor
            # Usar fondo blanco y texto negro
            # Centro: se elimina la etiqueta 'Tara Aplicada' y se mantiene
            # un contenedor oculto para compatibilidad con el widget de valor.
            center_frame = ttk.Frame(tare_inner, style='CardNoBorder.TFrame')
            # No gridear center_frame para mantenerlo oculto; usamos la columna central
            center_frame.columnconfigure(0, weight=1)

            # Valor de tara aplicado más compacto (visibilidad asegurada)
            try:
                val_font = ("Consolas", self.scaled_font(32), 'bold')
            except Exception:
                val_font = ("Consolas", 32, 'bold')
            self.lbl_tare_value_main = ttk.Label(center_frame, text="0 kgf", style='TareMaintValue.TLabel', font=val_font, anchor='center')
            # Ocultar el valor de la tara en la vista principal (se mantiene el widget para compatibilidad)
            try:
                # No grid() para mantener oculto en la vista principal
                pass
            except Exception:
                pass
            try:
                self.lbl_tare_value_main.target_width = self.scaled(300)
            except Exception:
                self.lbl_tare_value_main.target_width = None
        except Exception:
            # En caso de fallo, ignorar para no romper la UI principal
            pass
        
        
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

    def _create_status_dot(self, parent, size):
        """Crea un indicador de estado profesional: punto sólido con borde fino."""
        bg = '#ffffff'
        canvas = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg)
        canvas.pack(side=LEFT, padx=(0, self.scaled(6)))

        # Anillo exterior fino
        bw = max(1, int(size * 0.07))
        ring = canvas.create_oval(bw, bw, size - bw, size - bw, outline='#cbd5e1', width=bw, fill='')

        # Relleno sólido
        inset = max(3, int(size * 0.18))
        fill = canvas.create_oval(inset, inset, size - inset, size - inset, fill='#94a3b8', outline='')

        return {'canvas': canvas, 'ring': ring, 'fill': fill}

    def _update_status_led(self, state):
        """Actualiza el indicador de estado del nodo."""
        try:
            if not hasattr(self, '_status_led') or not self._status_led:
                return
            s = (state or '').lower()
            if s in ('connected', 'conectado', 'on'):
                self._set_led_canvas_state(self._status_led, self._status_led_outer, self._status_led_inner, 'connected')
                if hasattr(self, '_status_text') and self._status_text:
                    self._status_text.configure(foreground='#16a34a')
            elif s in ('error', 'fail', 'failed', 'desconectado_error'):
                self._set_led_canvas_state(self._status_led, self._status_led_outer, self._status_led_inner, 'error')
                if hasattr(self, '_status_text') and self._status_text:
                    self._status_text.configure(foreground='#b91c1c')
            else:
                self._set_led_canvas_state(self._status_led, self._status_led_outer, self._status_led_inner, 'idle')
                if hasattr(self, '_status_text') and self._status_text:
                    self._status_text.configure(foreground='#64748b')
        except Exception:
            pass

    def _set_led_canvas_state(self, canvas, ring_item, fill_item, state):
        """Actualiza colores del indicador de estado."""
        try:
            if not canvas:
                return
            s = (state or '').lower()
            if s in ('connected', 'ok', 'on'):
                fill_color = '#22c55e'
                ring_color = '#16a34a'
            elif s in ('error', 'fail', 'failed', 'alarm'):
                fill_color = '#ef4444'
                ring_color = '#b91c1c'
            else:
                fill_color = '#94a3b8'
                ring_color = '#cbd5e1'
            canvas.itemconfigure(ring_item, outline=ring_color)
            canvas.itemconfigure(fill_item, fill=fill_color)
        except Exception:
            pass

    def _update_modbus_led(self, state):
        """Actualiza el indicador de estado Modbus."""
        try:
            if not hasattr(self, '_modbus_status_led') or not self._modbus_status_led:
                return
            self._set_led_canvas_state(self._modbus_status_led, self._modbus_led_outer, self._modbus_led_inner, state)
        except Exception:
            pass

    def _reposition_kg_unit(self):
        """Reposiciona 'kg' justo después del texto del número, alineado abajo."""
        try:
            import tkinter.font as tkfont
            # Obtener la fuente actual del label
            font_info = self.lbl_total.cget('font')
            if isinstance(font_info, str) and font_info:
                try:
                    f = tkfont.nametofont(font_info)
                except Exception:
                    f = tkfont.Font(font=font_info)
            else:
                f = tkfont.Font(font=font_info)
            text = self.lbl_total.cget('text') or "0"
            text_width = f.measure(text)
            
            container_width = self.lbl_total.winfo_width()
            if container_width <= 1:
                return  # aún no se renderizó
            
            # El texto está centrado → empieza en (ancho - texto) / 2
            text_end_x = (container_width + text_width) // 2
            
            # Altura: alinear "kg" al fondo del número
            container_height = self.lbl_total.winfo_height()
            kg_height = self.lbl_total_unit.winfo_reqheight()
            # Posicionar en la base del label, con un pequeño offset hacia arriba
            kg_y = container_height - kg_height - self.scaled(4)
            
            self.lbl_total_unit.place(
                in_=self.lbl_total,
                x=text_end_x + self.scaled(6),
                y=kg_y
            )
        except Exception:
            pass

    def _update_footer_time(self):
        """Actualiza `self.footer_time` cada segundo con fecha y hora en formato DD/MM/YYYY HH:MM:SS."""
        try:
            import datetime
            now = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            if hasattr(self, 'footer_time') and self.footer_time:
                try:
                    self.footer_time.configure(text=now)
                except Exception:
                    pass
            elif hasattr(self, 'lbl_footer_time') and self.lbl_footer_time:
                try:
                    self.lbl_footer_time.configure(text=now)
                except Exception:
                    pass
            # Repetir cada segundo
            try:
                self.after(1000, self._update_footer_time)
            except Exception:
                pass
        except Exception:
            pass

    def actualizar_gui(self):
        """Consume mensajes de la cola y actualiza la UI."""
        latest_data = None
        processed = 0
        max_msgs = getattr(self, '_gui_max_msgs_per_tick', 80)
        try:
            while processed < max_msgs:
                # Leer de la cola sin bloquear
                msg = self.data_queue.get_nowait()
                processed += 1
                
                if msg['type'] == 'DATA':
                    # Conservar solo la muestra más reciente para este tick
                    latest_data = msg['payload']
                elif msg['type'] == 'STATUS':
                    self._update_status(msg['payload'])
                elif msg['type'] == 'ERROR':
                    self.show_alert("Erro", msg['payload'], "error")
                    self.log_message(f"[ERRO] {msg['payload']}")
                elif msg['type'] == 'MODBUS_STATUS':
                    try:
                        self._update_modbus_led(msg['payload'])
                    except Exception:
                        pass
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
        except queue.Empty:
            pass
        finally:
            try:
                if latest_data is not None:
                    self._last_sensor_data = latest_data  # Guardar para calibración
                    self._update_display(latest_data)
            except Exception:
                pass
            # Reprogramar a atualizao
            self.after(70, self.actualizar_gui)

    def log_message(self, message):
        """Guarda mensajes y errores en el archivo log (I/O en hilo de fondo)."""
        import datetime
        import time
        try:
            msg = str(message)
        except Exception:
            msg = message
        # Evitar escrituras duplicadas en ráfaga (mismo mensaje en <500ms)
        try:
            now_ts = time.time()
            if msg == self._last_log_message and (now_ts - float(self._last_log_ts or 0.0)) < 0.5:
                return
            self._last_log_message = msg
            self._last_log_ts = now_ts
        except Exception:
            pass
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry = f"[{timestamp}] {msg}\n"
        try:
            self._log_write_queue.put_nowait(entry)
        except Exception:
            pass

    def _update_modbus_status_from_log(self, message):
        """Actualiza indicador de Modbus en el header a partir de mensajes de log."""
        try:
            if not hasattr(self, '_modbus_status_led') or not self._modbus_status_led:
                return
            msg = str(message or '').strip()
            msg_l = msg.lower()
            if 'modbus rtu' not in msg_l:
                return

            if ('iniciado em' in msg_l) or ('iniciado en' in msg_l):
                self._update_modbus_led('connected')
            elif ('não iniciado' in msg_l) or ('no iniciado' in msg_l):
                self._update_modbus_led('idle')
            elif ('erro' in msg_l) or ('falha' in msg_l):
                self._update_modbus_led('error')
            else:
                self._update_modbus_led('idle')
        except Exception:
            pass

    def _update_display(self, data):
        # Guardar datos para actualización cuando cambie modo decimales
        self._last_sensor_data = data
        # Marcar que recibimos la primera muestra si hay datos útiles
        try:
            if not getattr(self, '_first_sample_received', False):
                has_total = bool(data.get('total_last_seen')) or ('total' in data and data.get('total') is not None)
                sensores = data.get('sensores', {})
                has_sensor_values = False
                if sensores:
                    for s in sensores.values():
                        if s and (s.get('connected', False) or s.get('values')):
                            has_sensor_values = True
                            break
                if has_total or has_sensor_values:
                    self._first_sample_received = True
        except Exception:
            pass

        
        # Atualizar Tara Acumulada em Toneladas
        if 'total_tare' in data:
            tara_ton = data['total_tare']
            # Guardar estado actual de tara para lógicas de confirmación
            try:
                self._current_tare = float(tara_ton or 0.0)
            except Exception:
                try:
                    self._current_tare = 0.0
                except Exception:
                    pass
            # Actualizar el widget nuevo si existe, sino mantener compatibilidad
            tare_text = f"{self._format_weight(tara_ton)} kgf"
            # Actualizar label en pestaña de mantenimiento
            try:
                if hasattr(self, 'lbl_tare_value') and self.lbl_tare_value:
                    if self.lbl_tare_value.cget('text') != tare_text:
                        self.lbl_tare_value.configure(text=tare_text)
            except Exception:
                pass
            # Actualizar label en vista principal (si existe)
            try:
                if hasattr(self, 'lbl_tare_value_main') and self.lbl_tare_value_main:
                    if self.lbl_tare_value_main.cget('text') != tare_text:
                        self.lbl_tare_value_main.configure(text=tare_text)
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

        # Si acabamos de conectarnos, dar un pequeño periodo de gracia antes de
        # mostrar error de comunicación para que los sensores tengan tiempo de
        # enviar sus primeras muestras.
        try:
            import time
            if any_disconnected and getattr(self, 'connected', False):
                conn_time = getattr(self, '_conn_success_time', 0.0) or 0.0
                grace = getattr(self, '_post_connect_grace_s', 0.0) or 0.0
                # No mostrar error si aún estamos dentro del periodo de gracia
                # o si aun no hemos recibido la primera muestra útil.
                first_received = getattr(self, '_first_sample_received', False)
                if conn_time and ((time.time() - conn_time) < float(grace) or not first_received):
                    any_disconnected = False
        except Exception:
            pass
        
        # Mudar cor do painel TOTAL segundo estado de sensores - FAIL-SAFE
        if any_disconnected:
            # VERMELHO - UI simplificada: solo estado de error
            try:
                if self.total_section.cget('style') != 'TotalPanelDanger.TFrame':
                    self.total_section.configure(style='TotalPanelDanger.TFrame')
            except Exception:
                pass
            try:
                if self.lbl_total_title.cget('text') != "ERROR" or self.lbl_total_title.cget('style') != 'TotalLabelDanger.TLabel':
                    self.lbl_total_title.configure(text="ERROR", style='TotalLabelDanger.TLabel')
            except Exception:
                pass
            try:
                if self.lbl_total.cget('text') != "ERROR" or self.lbl_total.cget('style') != 'TotalValueDanger.TLabel':
                    self.lbl_total.configure(text="ERROR", style='TotalValueDanger.TLabel')
            except Exception:
                pass
            try:
                if self.lbl_total_unit.cget('text') != "" or self.lbl_total_unit.cget('style') != 'TotalUnitDanger.TLabel':
                    self.lbl_total_unit.configure(text="", style='TotalUnitDanger.TLabel')
            except Exception:
                pass
            # Mantener paridad visual en la pestaña de mantenimiento si existe
            try:
                if hasattr(self, 'lbl_maint_total') and self.lbl_maint_total:
                    if self.lbl_maint_total.cget('text') != "ERROR" or self.lbl_maint_total.cget('style') != 'TotalValueDanger.TLabel':
                        self.lbl_maint_total.configure(text="ERROR", style='TotalValueDanger.TLabel')
                if hasattr(self, 'lbl_maint_total_title') and self.lbl_maint_total_title:
                    if self.lbl_maint_total_title.cget('text') != "ERROR" or self.lbl_maint_total_title.cget('style') != 'TotalLabelDanger.TLabel':
                        self.lbl_maint_total_title.configure(text="ERROR", style='TotalLabelDanger.TLabel')
                if hasattr(self, 'lbl_maint_total_unit') and self.lbl_maint_total_unit:
                    if self.lbl_maint_total_unit.cget('text') != "" or self.lbl_maint_total_unit.cget('style') != 'TotalUnitDanger.TLabel':
                        self.lbl_maint_total_unit.configure(text="", style='TotalUnitDanger.TLabel')
            except Exception:
                pass
        else:
            # AZUL - Todos os sensores conectados (normal)
            try:
                if self.total_section.cget('style') != 'TotalPanel.TFrame':
                    self.total_section.configure(style='TotalPanel.TFrame')
            except Exception:
                pass
            try:
                if self.lbl_total_title.cget('text') != "CARGA" or self.lbl_total_title.cget('style') != 'TotalLabel.TLabel':
                    self.lbl_total_title.configure(text="CARGA", style='TotalLabel.TLabel')
            except Exception:
                pass
            # Actualizar total usando timestamp (permitiendo totals negativos).
            incoming_total_last = data.get('total_last_seen', 0.0) or 0.0
            # Ignoramos la comprobación 'total_raw>0' para que valores negativos
            # en las lecturas sean reflejados en la UI tal como llegan.
            # Actualizar solo si la muestra es nueva (strict >) para evitar
            # redibujos con el mismo timestamp que causaban parpadeos.
            if incoming_total_last > self._widget_last_total:
                peso_ton = data.get('total', 0.0)
                total_text = f"{self._format_weight(peso_ton)}"
                # Solo actualizar texto; la fuente permanece fija (definida por el estilo)
                # para evitar parpadeos y cambios de tamaño durante la operación.
                try:
                    if self.lbl_total.cget('text') != total_text or self.lbl_total.cget('style') != 'TotalValue.TLabel':
                        self.lbl_total.configure(text=total_text, style='TotalValue.TLabel')
                except Exception:
                    try:
                        self.lbl_total.configure(text=total_text)
                    except Exception:
                        pass
                # Actualizar también la vista de mantenimiento si existe
                try:
                    if hasattr(self, 'lbl_maint_total') and self.lbl_maint_total:
                        try:
                            if self.lbl_maint_total.cget('text') != total_text or self.lbl_maint_total.cget('style') != 'TotalValue.TLabel':
                                self.lbl_maint_total.configure(text=total_text, style='TotalValue.TLabel')
                        except Exception:
                            try:
                                if self.lbl_maint_total.cget('text') != total_text:
                                    self.lbl_maint_total.configure(text=total_text)
                            except Exception:
                                pass
                    if hasattr(self, 'lbl_maint_total_unit') and self.lbl_maint_total_unit:
                        if self.lbl_maint_total_unit.cget('text') != "kgf":
                            self.lbl_maint_total_unit.configure(text="kgf", style='TotalUnit.TLabel')
                    if hasattr(self, 'lbl_maint_total_title') and self.lbl_maint_total_title:
                        if self.lbl_maint_total_title.cget('text') != "CARGA":
                            self.lbl_maint_total_title.configure(text="CARGA", style='TotalLabel.TLabel')
                except Exception:
                    pass
                self._widget_last_total = incoming_total_last
                # Actualizar la barra de carga (0..1200)
                try:
                    val = float(peso_ton or 0.0)
                    min_v = 0.0
                    max_v = 1200.0
                    
                    # Verificar Perfil Ativo
                    profile_limits = self._get_active_profile_limits()
                    color = None
                    pct = 0.0
                    
                    try:
                        c_w = self.load_bar_canvas.winfo_width() or self.load_bar_canvas.target_width or self.scaled(360)
                    except Exception:
                        c_w = self.scaled(360)
                    
                    if profile_limits:
                        # === LÓGICA DE PERFIL ===
                        p_min = float(profile_limits.get('min', 0))
                        p_max = float(profile_limits.get('max', 100))
                        
                        # Auto-swap si el usuario puso min > max
                        if p_min > p_max:
                            p_min, p_max = p_max, p_min
                        
                        # Escala dinâmica (FIXA em 1200 para coincidir con background)
                        max_v = 1200.0
                        pct = max(0.0, min(1.0, (val - min_v) / (max_v - min_v)))
                        
                        if val < p_min or val > p_max:
                            color = "#ef4444" # Vermelho (Fora do intervalo)
                        else:
                            color = "#22c55e" # Verde (Dentro do intervalo)
                            
                        # Calcular posiciones de marcadores
                        try:
                            c_h = self.load_bar_canvas.winfo_height() or self.scaled(40)
                            marker_min_x = int(c_w * (p_min / max_v))
                            marker_max_x = int(c_w * (p_max / max_v))
                        except Exception:
                            marker_min_x, marker_max_x = -1, -1
                    else:
                        # === LÓGICA PADRÃO (GRADIENTE) ===
                        max_v = 1200.0
                        pct = max(0.0, min(1.0, (val - min_v) / (max_v - min_v)))
                        marker_min_x, marker_max_x = -1, -1

                        def interp_color(v0, v1, t):
                            return tuple(int(v0[i] + (v1[i] - v0[i]) * t) for i in range(3))

                        blue = (37, 99, 235)
                        light_blue = (56, 189, 248)
                        green = (34, 197, 94)
                        yellow = (245, 158, 11)
                        orange = (249, 115, 22)
                        red = (239, 68, 68)

                        if val <= 0:
                            rgb = blue
                        elif val <= 300:
                            t = val / 300.0
                            rgb = interp_color(blue, light_blue, t)
                        elif val <= 600:
                            t = (val - 300) / 300.0
                            rgb = interp_color(light_blue, green, t)
                        elif val <= 800:
                            t = (val - 600) / 200.0
                            rgb = interp_color(green, yellow, t)
                        elif val <= 1000:
                            t = (val - 800) / 200.0
                            rgb = interp_color(yellow, orange, t)
                        elif val <= 1200:
                            t = (val - 1000) / 200.0
                            rgb = interp_color(orange, red, t)
                        else:
                            rgb = red
                        color = '#%02x%02x%02x' % rgb

                    fill_w = int(c_w * pct)

                    try:
                        if self.load_bar_canvas.winfo_exists():
                            if getattr(self, '_load_bar_fill', None):
                                self.load_bar_canvas.coords(self._load_bar_fill, 0, 0, fill_w, self.load_bar_canvas.winfo_height())
                                self.load_bar_canvas.itemconfig(self._load_bar_fill, fill=color)
                            
                            # Marcadores de limites
                            if not hasattr(self, '_marker_min'):
                                self._marker_min = self.load_bar_canvas.create_line(0, 0, 0, 0, fill="black", width=self.scaled(4), dash=(2, 4))
                                self._marker_max = self.load_bar_canvas.create_line(0, 0, 0, 0, fill="black", width=self.scaled(4), dash=(2, 4))
                            
                            if marker_min_x >= 0:
                                c_h_real = self.load_bar_canvas.winfo_height()
                                self.load_bar_canvas.coords(self._marker_min, marker_min_x, 0, marker_min_x, c_h_real)
                                self.load_bar_canvas.coords(self._marker_max, marker_max_x, 0, marker_max_x, c_h_real)
                                self.load_bar_canvas.itemconfig(self._marker_min, state='normal')
                                self.load_bar_canvas.itemconfig(self._marker_max, state='normal')
                                self.load_bar_canvas.tag_raise(self._marker_min)
                                self.load_bar_canvas.tag_raise(self._marker_max)
                            else:
                                self.load_bar_canvas.itemconfig(self._marker_min, state='hidden')
                                self.load_bar_canvas.itemconfig(self._marker_max, state='hidden')

                            if getattr(self, '_load_bar_border', None):
                                full_w = self.load_bar_canvas.winfo_width() or c_w
                                self.load_bar_canvas.coords(self._load_bar_border, 0, 0, full_w, self.load_bar_canvas.winfo_height())
                    except Exception:
                        pass
                except Exception:
                    pass
                # Atualizar labels de ângulos (1..5)
                try:
                    angles = data.get('angles')
                    if not isinstance(angles, list):
                        angles = []

                    if not angles:
                        angle_val = data.get('angle_val')
                        try:
                            if angle_val is not None:
                                angles = [float(angle_val)]
                        except (ValueError, TypeError):
                            angles = []

                    if getattr(self, 'lbl_angles', None):
                        for idx, lbl in enumerate(self.lbl_angles):
                            try:
                                if idx < len(angles):
                                    val = float(angles[idx])
                                    text = f"{val:.1f}".replace('.', ',') + "°"
                                else:
                                    text = "0,0°"
                                if lbl.cget('text') != text:
                                    lbl.configure(text=text)
                            except Exception:
                                pass
                except Exception:
                    pass
            try:
                if self.lbl_total_unit.cget('text') != "kgf" or self.lbl_total_unit.cget('style') != 'TotalUnit.TLabel':
                    self.lbl_total_unit.configure(text="kgf", style='TotalUnit.TLabel')
            except Exception:
                pass
        
        # Actualizar Sensores Individuales (datos pueden ser parciales; usar get para evitar KeyError)
        sensores = data.get('sensores', {})

        for key, widgets in list(self.sensor_widgets.items()):
            if key in sensores:
                info = sensores[key]
                # Verificar que el widget de valor aún exista (puede pertenecer a un diálogo cerrado)
                val_widget = widgets.get('value')
                try:
                    if not (hasattr(val_widget, 'winfo_exists') and val_widget.winfo_exists()):
                        # El widget fue destruido; eliminar entrada para evitar futuros errores
                        try:
                            del self.sensor_widgets[key]
                        except Exception:
                            pass
                        continue
                except Exception:
                    # Si no podemos comprobar, intentar continuar sin tocar
                    pass

                # Actualizar valor solo si la muestra es nueva (usar last_seen)
                valor_ton = info.get('valor', 0.0)
                incoming_last = info.get('last_seen', 0.0) or 0.0
                prev_last = self._widget_last_seen.get(key, 0.0)
                if incoming_last > prev_last:
                    display_text = self._format_weight(valor_ton)
                    try:
                        if val_widget.cget('text') != display_text:
                            val_widget.configure(text=display_text)
                    except Exception:
                        # Ignorar errores de Tk (widget ya destruido u otro fallo)
                        try:
                            val_widget['text'] = display_text
                        except Exception:
                            pass

                    self._widget_last_seen[key] = incoming_last

                # Atualizar estado visual segundo conexo
                try:
                    if info.get('connected', True):
                        try:
                            if val_widget.cget('foreground') != "#1e293b":
                                val_widget.configure(foreground="#1e293b")
                        except Exception:
                            pass
                        rssi_widget = widgets.get('rssi')
                        if rssi_widget and hasattr(rssi_widget, 'winfo_exists') and rssi_widget.winfo_exists():
                            try:
                                if rssi_widget.cget('text') != "" or rssi_widget.cget('foreground') != "#22c55e":
                                    rssi_widget.configure(text="", foreground="#22c55e")
                            except Exception:
                                pass
                        if 'status' in widgets:
                            st = widgets.get('status')
                            if st and hasattr(st, 'winfo_exists') and st.winfo_exists():
                                try:
                                    if st.cget('text') != "Ativo" or st.cget('foreground') != "#22c55e":
                                        st.configure(text="Ativo", foreground="#22c55e")
                                except Exception:
                                    pass
                    else:
                        try:
                            if val_widget.cget('foreground') != "#cbd5e1":
                                val_widget.configure(foreground="#cbd5e1")
                        except Exception:
                            pass
                        rssi_widget = widgets.get('rssi')
                        if rssi_widget and hasattr(rssi_widget, 'winfo_exists') and rssi_widget.winfo_exists():
                            try:
                                if rssi_widget.cget('text') != "" or rssi_widget.cget('foreground') != "#ef4444":
                                    rssi_widget.configure(text="", foreground="#ef4444")
                            except Exception:
                                pass
                        if 'status' in widgets:
                            st = widgets.get('status')
                            if st and hasattr(st, 'winfo_exists') and st.winfo_exists():
                                try:
                                    if st.cget('text') != "Sem Sinal" or st.cget('foreground') != "#ef4444":
                                        st.configure(text="Sem Sinal", foreground="#ef4444")
                                except Exception:
                                    pass
                except Exception:
                    pass


    def _update_status(self, connected):
        self.connected = connected
        if connected:
            self.lbl_status.configure(text="Conectado", foreground="#22c55e")
            try:
                self._update_status_led('connected')
            except Exception:
                pass
            # Manter dimenses ao mudar estilo
            self.btn_connect.configure(
                text="DESCONECTAR", 
                bootstyle="danger",
                style='ConnectDanger.TButton',
                width=14,
                padding=(15, 12)
            )
            # Si el diálogo de configuración está abierto, actualizar su botón también
            try:
                if hasattr(self, 'btn_connect_dialog') and getattr(self, 'btn_connect_dialog'):
                    try:
                        self.btn_connect_dialog.configure(text="DESCONECTAR", bootstyle="danger", style='Large.danger.TButton', width=12, padding=(20, 10))
                        try:
                            # Forzar fuente/estilo consistente para evitar cambios de tamaño
                            self.btn_connect_dialog.configure(font=self.style.configure('Header.TButton').get('font'))
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass
            # Al conectarse, intentar cargar y aplicar calibraciones disponibles
            try:
                self._apply_saved_calibrations_on_connect()
            except Exception:
                pass
            # Registrar timestamp de conexión exitosa para periodo de gracia
            try:
                import time
                self._conn_success_time = time.time()
            except Exception:
                self._conn_success_time = 0.0
        else:
            self.lbl_status.configure(text="Desconectado", foreground="#64748b")
            try:
                self._update_status_led('disconnected')
            except Exception:
                pass
            try:
                self._update_modbus_led('idle')
            except Exception:
                pass
            # Manter dimenses ao mudar estilo
            self.btn_connect.configure(
                text="CONECTAR", 
                bootstyle="success",
                style='ConnectSuccess.TButton',
                width=14,
                padding=(15, 12)
            )
            try:
                if hasattr(self, 'btn_connect_dialog') and getattr(self, 'btn_connect_dialog'):
                    try:
                        self.btn_connect_dialog.configure(text="CONECTAR", bootstyle="success", style='Large.success.TButton', width=12, padding=(20, 10))
                        try:
                            self.btn_connect_dialog.configure(font=self.style.configure('Header.TButton').get('font'))
                        except Exception:
                            pass
                    except Exception:
                        pass
                    # Si hay un diálogo de conexión activo, interpretar este STATUS=False
                    # como el resultado de una tentativa finalizada. Lanzar nueva tentativa
                    # sólo si el usuario no canceló y aún quedan intentos disponibles.
                    try:
                        if getattr(self, '_connection_dialog_active', False) and not getattr(self, '_cancel_connection', False):
                            # Si aún podemos intentar más veces
                            try:
                                attempts = int(getattr(self, '_conn_attempt', 1))
                            except Exception:
                                attempts = 1

                            if attempts < RECONNECT_ATTEMPTS:
                                attempts += 1
                                self._conn_attempt = attempts
                                # Actualizar texto y solicitar nueva tentativa al backend
                                try:
                                    self._conn_status.configure(text=f"Tentativa {self._conn_attempt}...")
                                    self._conn_info.configure(text=f"Tentativa {self._conn_attempt}")
                                except Exception:
                                    pass
                                try:
                                    self.command_queue.put({'cmd': 'CONNECT'})
                                except Exception:
                                    pass
                            else:
                                # Agotar intentos: mostrar fallo en el diálogo
                                try:
                                    if hasattr(self, '_conn_progress') and self._conn_progress.winfo_exists():
                                        self._conn_progress.stop()
                                except Exception:
                                    pass
                                try:
                                    self._conn_status.configure(text=" Sensor não encontrado", foreground="#ef4444")
                                    self._conn_info.configure(text="Verifique a conexão e tente novamente")
                                    self._conn_btn.configure(text="FECHAR", bootstyle="secondary",
                                                              command=self._safe_close_conn_dialog)
                                except Exception:
                                    pass
                                self._connection_dialog_active = False
                    except Exception:
                        pass
            except Exception:
                pass
            # Al desconectarse, resetear flag de primera muestra
            try:
                self._first_sample_received = False
            except Exception:
                pass

    def _show_numeric_keypad(self, entry_widget, title="Inserir Valor",
                              pin_mode=False, max_digits=None):
        """Teclado numérico virtual grande y funcional."""
        try:
            if hasattr(self, '_active_keypad') and self._active_keypad and not self._active_keypad.winfo_exists():
                self._active_keypad = None
                self._keypad_target_widget = None
        except Exception:
            self._active_keypad = None
            self._keypad_target_widget = None

        # Si ya existe para el mismo widget, no recrear (evita parpadeo/doble instancia)
        try:
            if (
                entry_widget is not None
                and hasattr(self, '_active_keypad')
                and self._active_keypad
                and self._active_keypad.winfo_exists()
                and getattr(self, '_keypad_target_widget', None) is entry_widget
            ):
                try:
                    self._active_keypad.lift()
                    self._active_keypad.focus_force()
                except Exception:
                    pass
                return
        except Exception:
            pass

        # Cerrar teclado anterior si existe
        if hasattr(self, '_active_keypad') and self._active_keypad:
            try:
                try:
                    self._suppress_cfg_watch = False
                except Exception:
                    pass
                self._active_keypad.destroy()
            except:
                pass
            self._active_keypad = None

        # Valor actual del entry
        if entry_widget is not None:
            current_value = entry_widget.get() if hasattr(entry_widget, 'get') else ""
        else:
            current_value = ""

        # Tamaño del teclado
        kp_width, kp_height = 480, 650

        # Obtener la ventana padre
        if entry_widget is not None:
            parent = entry_widget.winfo_toplevel()
        else:
            parent = self
        try:
            self._suppress_cfg_watch = True
        except Exception:
            pass

        # Crear ventana del teclado
        keypad = tk.Toplevel(parent)
        keypad.withdraw()  # Ocultar inmediatamente para evitar flash de barra de título
        keypad.title(title)
        self._center_toplevel(keypad, kp_width, kp_height)
        keypad.resizable(False, False)
        keypad.transient(parent)
        keypad.attributes('-topmost', True)
        if not pin_mode:
            self._apply_window_icon(keypad)
        keypad.configure(bg="#222222")
        if pin_mode:
            keypad.overrideredirect(True)
        self._active_keypad = keypad
        self._keypad_target_widget = entry_widget

        # Variable para el valor
        kp_value = tk.StringVar(value=current_value)

        # Flag para saber si es la primera pulsación
        first_press = [True]

        # Variables para modo PIN
        _real_digits = []               # dígitos reales cuando pin_mode=True
        _pin_result   = {'value': None} # canal de retorno del modal

        # Funciones
        def press_digit(d):
            if pin_mode:
                if d in (".", "-"):
                    return
                if max_digits and len(_real_digits) >= max_digits:
                    return
                _real_digits.append(d)
                kp_value.set('\u25cf' * len(_real_digits))  # ● por dígito
                return
            current = kp_value.get()
            if d == "-":
                if current.startswith("-"):
                    return
                if current == "":
                    kp_value.set("-")
                else:
                    kp_value.set("-" + current)
                first_press[0] = False
                return
            if first_press[0] and current == "0" and d != ".":
                kp_value.set(d)
                first_press[0] = False
                return
            first_press[0] = False
            if d == "." and "." in current:
                return
            kp_value.set(current + d)

        def press_backspace():
            if pin_mode:
                if _real_digits:
                    _real_digits.pop()
                kp_value.set('\u25cf' * len(_real_digits))
                return
            kp_value.set(kp_value.get()[:-1])

        def press_clear():
            kp_value.set("")

        # Frame superior para layout grid
        keypad_frame = ttk.Frame(keypad)
        keypad_frame.pack(fill="both", expand=True)
        if pin_mode:
            keypad_frame.rowconfigure(0, weight=1)  # título
            keypad_frame.rowconfigure(1, weight=2)  # entry
            keypad_frame.rowconfigure(2, weight=8)  # botones
        else:
            keypad_frame.rowconfigure(0, weight=2)  # entry
            keypad_frame.rowconfigure(1, weight=8)  # botones
        keypad_frame.columnconfigure(0, weight=1)

        # Título personalizado (solo en pin_mode, reemplaza la barra de Windows)
        if pin_mode:
            title_lbl = ttk.Label(
                keypad_frame,
                text=title,
                font=("Segoe UI", 14, "bold"),
                anchor="center"
            )
            title_lbl.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
            entry_row = 1
            btns_row = 2
        else:
            entry_row = 0
            btns_row = 1

        # Entry grande para mostrar el valor digitado
        entry_display = ttk.Entry(keypad_frame, textvariable=kp_value, font=("Segoe UI", 32), justify="center", state="readonly")
        entry_display.grid(row=entry_row, column=0, sticky="nsew", padx=40, pady=(10 if pin_mode else 40, 20))

        # Frame de botones
        all_btns = ttk.Frame(keypad_frame)
        all_btns.grid(row=btns_row, column=0, sticky="nsew")
        for i in range(5):
            all_btns.rowconfigure(i, weight=1)
        for j in range(3):
            all_btns.columnconfigure(j, weight=1, uniform="kp_col")

        pad_num = (18, 18)
        pad_act = (18, 22)

        def _close_keypad():
            try:
                keypad.grab_release()
            except Exception:
                pass
            try:
                keypad.destroy()
            except Exception:
                pass
            try:
                self._suppress_cfg_watch = False
            except Exception:
                pass
            try:
                self._active_keypad = None
            except Exception:
                pass
            try:
                self._keypad_target_widget = None
            except Exception:
                pass

        def confirm_and_close():
            if pin_mode:
                _pin_result['value'] = ''.join(_real_digits)
            else:
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, kp_value.get())
                try:
                    entry_widget.focus_set()
                except Exception:
                    pass
            _close_keypad()

        def cancel_and_close():
            # _pin_result['value'] permanece None → el caller interpreta como cancelación
            _close_keypad()

        def _handle_physical_key(event):
            """Soporte de teclado físico cuando el keypad está abierto."""
            try:
                keysym = str(getattr(event, 'keysym', '') or '')
                char = str(getattr(event, 'char', '') or '')

                # Confirmar / cancelar
                if keysym in ('Return', 'KP_Enter'):
                    confirm_and_close()
                    return "break"
                if keysym == 'Escape':
                    cancel_and_close()
                    return "break"

                # Edición
                if keysym in ('BackSpace', 'Delete'):
                    press_backspace()
                    return "break"

                # Digitos del teclado principal o numérico
                if char.isdigit():
                    press_digit(char)
                    return "break"

                # Signo negativo
                if char == '-':
                    press_digit('-')
                    return "break"

                # Separador decimal (permitir punto o coma)
                if char in ('.', ',') or keysym in ('period', 'comma', 'KP_Decimal', 'decimal'):
                    press_digit('.')
                    return "break"
            except Exception:
                return None
            return None

        # Compatibilidad con teclado físico mientras el keypad está abierto
        try:
            keypad.bind('<KeyPress>', _handle_physical_key, add='+')
            keypad.bind('<Return>', _handle_physical_key, add='+')
            keypad.bind('<KP_Enter>', _handle_physical_key, add='+')
            keypad.bind('<Escape>', _handle_physical_key, add='+')
            keypad.bind('<BackSpace>', _handle_physical_key, add='+')
            keypad.bind('<Delete>', _handle_physical_key, add='+')
            entry_display.bind('<KeyPress>', _handle_physical_key, add='+')
            entry_display.bind('<Return>', _handle_physical_key, add='+')
            entry_display.bind('<KP_Enter>', _handle_physical_key, add='+')
            entry_display.bind('<Escape>', _handle_physical_key, add='+')
            entry_display.bind('<BackSpace>', _handle_physical_key, add='+')
            entry_display.bind('<Delete>', _handle_physical_key, add='+')
        except Exception:
            pass

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

        # Fila 3: [./deshabilitado en PIN] 0 DEL
        if not pin_mode:
            ttk.Button(all_btns, text=".", command=lambda: press_digit("."), bootstyle="secondary", padding=pad_num).grid(row=3, column=0, sticky="nsew", padx=4, pady=4)
        else:
            ttk.Button(all_btns, text="", state="disabled", bootstyle="secondary", padding=pad_num).grid(row=3, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="0", command=lambda: press_digit("0"), bootstyle="light", padding=pad_num).grid(row=3, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="DEL", command=press_backspace, bootstyle="warning", padding=pad_act).grid(row=3, column=2, sticky="nsew", padx=4, pady=4)

        # Fila 4: [-/CANCELAR] | OK (OK ocupa 2 columnas)
        if not pin_mode:
            ttk.Button(all_btns, text="-", command=lambda: press_digit("-"), bootstyle="secondary", padding=pad_act).grid(row=4, column=0, sticky="nsew", padx=4, pady=4)
        else:
            ttk.Button(all_btns, text="CANCELAR", command=cancel_and_close, bootstyle="danger", padding=pad_act).grid(row=4, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Button(all_btns, text="OK", command=confirm_and_close, bootstyle="success", padding=pad_act).grid(row=4, column=1, columnspan=2, sticky="nsew", padx=4, pady=4)

        # Mostrar la ventana solo ahora que todo está configurado (sin flash de barra de título)
        try:
            keypad.update_idletasks()
            keypad.deiconify()
        except Exception:
            pass
        if pin_mode:
            try:
                keypad.grab_set()
            except Exception:
                pass

        # Focus y lift
        try:
            keypad.focus_set()
            keypad.lift()
        except Exception:
            pass
        try:
            entry_display.focus_force()
            keypad.after(30, entry_display.focus_force)
            keypad.after(90, entry_display.focus_force)
        except Exception:
            pass

        if pin_mode:
            try:
                self.wait_window(keypad)  # bloquea hasta que _close_keypad llame keypad.destroy()
            except Exception:
                pass
            finally:
                try:
                    if keypad.winfo_exists():
                        keypad.destroy()
                except Exception:
                    pass
                try:
                    self._suppress_cfg_watch = False
                except Exception:
                    pass
                try:
                    self._active_keypad = None
                    self._keypad_target_widget = None
                except Exception:
                    pass
            return _pin_result.get('value')



    def _validate_numeric_input(self, new_value):
        """Valida que la entrada sea numerica (float o vacia)."""
        if not new_value: return True # Empty is valid
        if new_value in ("-", ".", ",", "-.", "-,"): return True # Partial inputs
        
        # Permitir varios puntos/comas mientras se escribe (ej: 1.2.3 -> invalido final, valido intermedio)
        # O ser estricto pero considerar replace
        try:
            float(new_value.replace(',', '.'))
            return True
        except ValueError:
            return False

    def _bind_numeric_keypad(self, entry_widget, title="Inserir Valor"):
        """Vincula teclado numérico a un Entry sin bloquear teclado físico."""
        if entry_widget is None:
            return

        def _open_keypad(_event=None):
            try:
                now_ts = time.monotonic()
                last_ts = float(getattr(self, '_last_keypad_open_req_ts', 0.0) or 0.0)
                last_widget = getattr(self, '_last_keypad_open_widget', None)
                if last_widget is entry_widget and (now_ts - last_ts) < 0.18:
                    return "break"
                self._last_keypad_open_req_ts = now_ts
                self._last_keypad_open_widget = entry_widget

                if (
                    getattr(self, '_active_keypad', None)
                    and self._active_keypad.winfo_exists()
                    and getattr(self, '_keypad_target_widget', None) is entry_widget
                ):
                    try:
                        self._active_keypad.lift()
                        self._active_keypad.focus_force()
                    except Exception:
                        pass
                    return "break"
                self.after(40, lambda: self._show_numeric_keypad(entry_widget, title))
            except Exception:
                pass
            return "break"

        try:
            entry_widget.bind("<Button-1>", _open_keypad, add="+")
        except Exception:
            pass

        # No enlazar FocusIn para permitir uso fluido del teclado físico.

    def _check_connection_status(self):
        """Monitora o status da conexão durante o diálogo de conexão."""
        try:
            if not getattr(self, '_connection_dialog_active', False):
                return
            
            # Verificar se já conectou
            if self.connected:
                # Sucesso!
                try:
                    self._conn_progress.stop()
                    self._conn_status.configure(text="Conectado com sucesso!", foreground="#22c55e") # Green
                    self._conn_info.configure(text="Iniciando...", foreground="#22c55e")
                    # Cerrar dialogo despues de 1s
                    if hasattr(self, '_conn_dialog'):
                        self._conn_dialog.after(1000, self._close_connection_dialog_success)
                except Exception:
                    self._close_connection_dialog_success()
                return

            # Verificar timeout ou error
            elapsed = time.time() - getattr(self, '_conn_start_time', 0)
            timeout = getattr(self, 'CONNECTION_ATTEMPT_TIMEOUT_S', 15) # Default a 15s si no está en config
            if elapsed > timeout:
                # Timeout
                self._conn_status.configure(text="Tempo limite excedido", foreground="#dc2626")
                self._conn_info.configure(text="Verifique cabos e portas COM")
                self._conn_progress.stop()
                return

            # Si sigue intentando, agendar nueva revisión
            if hasattr(self, '_conn_dialog') and self._conn_dialog.winfo_exists():
                self._conn_dialog.after(200, self._check_connection_status)
        except Exception as e:
            print(f"Error checking connection status: {e}")
            pass

    def _close_connection_dialog_success(self):
        try:
            self._connection_dialog_active = False
            if hasattr(self, '_conn_dialog'):
                self._conn_dialog.destroy()
        except:
            pass


    def do_tare(self):
        # Si ya existe una tara aplicada, pedir confirmación antes de sobrescribir
        try:
            has_tare = getattr(self, '_current_tare', 0.0) and float(getattr(self, '_current_tare', 0.0)) != 0.0
        except Exception:
            has_tare = False

        if has_tare:
            try:
                confirm = self.show_large_tare_confirmation("Confirmação", "Já existe uma tara aplicada. Deseja sobrescrever ou limpar a tara?")
            except Exception as e:
                self.log_message(f"Erro ao mostrar diálogo de tara: {e}")
                confirm = "cancel"
            
            if confirm == "overwrite":
                pass
            elif confirm == "clear":
                try:
                    self.command_queue.put({'cmd': 'RESET_TARE'})
                    self.log_message("Solicitado limpar tara a partir da confirmação.")
                except Exception:
                    pass
                return
            else: # "cancel"
                return

        try:
            self.command_queue.put({'cmd': 'TARE'})
        except Exception:
            pass

    def toggle_decimals(self):
        """Alterna entre mostrar valores con o sin decimales."""
        # Toggle flag only; keep the button label as '0.00'
        self._show_decimals = not self._show_decimals
        # Forzar actualización visual inmediata de todos los valores
        # (sin cambiar fuentes — solo se reformatea el texto)
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

        # First: support single-file CSVs. Use `curva_celda.csv` (wide unified format)
        try:
            import csv as _csv
            applied = set()
            unified_path = os.path.join(CALIBRATIONS_DIR, 'curva_celda.csv')
            if unified_path and os.path.exists(unified_path):
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
                                self.log_message(f"Calibração aplicada a partir de {os.path.basename(unified_path)} para target={target} pontos={len(pts)}")
                                applied.add((serial_r, composite_r))
                            except Exception as e:
                                self.log_message(f"Falha ao aplicar calibração unificada para target={target}: {e}")
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
                                self.log_message(f"Falha ao aplicar calibração unificada (fallback) para target={target}: {e}")

                    if applied:
                        return
                except Exception as e:
                    self.log_message(f"Erro ao ler {unified_path}: {e}")

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
                                self.log_message(f"Calibração aplicada a partir de {os.path.basename(csv_path)} para serial={serial_k} composite={composite_k}")
                            else:
                                self.data_processor.calibration_segments = pts
                                self.data_processor.calibration_method = 'segments'
                                self.log_message(f"Calibração (fallback) carregada a partir do CSV para serial={serial_k} composite={composite_k}")
                            applied.add((serial_k, composite_k))
                        except Exception as e:
                            self.log_message(f"Falha ao aplicar calibração CSV para serial={serial_k} composite={composite_k}: {e}")

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
                                self.log_message(f"Calibração aplicada a partir de {os.path.basename(path)} para {composite}")
                            except Exception as e:
                                self.log_message(f"Falha ao aplicar calibração {path}: {e}")
                        else:
                            try:
                                self.data_processor.calibration_segments = pts
                                self.data_processor.calibration_method = 'segments'
                                self.log_message(f"Calibração (fallback) carregada para {composite}")
                            except Exception as e:
                                self.log_message(f"Falha ao estabelecer calibração fallback: {e}")
                        break
                except Exception as e:
                    try:
                        self.log_message(f"Erro ao carregar calibração {path}: {e}")
                    except:
                        pass
                
    
    def _refresh_all_displays(self):
        """Actualiza todos los displays con el formato actual."""
        if hasattr(self, '_last_sensor_data') and self._last_sensor_data:
            self._update_display(self._last_sensor_data)

    def _format_weight(self, value):
        """Formatea el peso según configuración de decimales (redondeo bancario/IEEE 754)."""
        if value is None:
            return "--"
        try:
            if isinstance(value, str):
                cleaned = value.strip().replace(' kgf', '').replace(' kg', '').replace(' ', '')
                if cleaned == "--" or cleaned == "-" or not cleaned:
                    return "--"
                val_float = float(cleaned)
            else:
                val_float = float(value)
        except Exception:
            return "--"

        try:
            if self._show_decimals:
                # Con decimales: 2 posiciones usando redondeo bancario
                from decimal import Decimal, ROUND_HALF_EVEN
                d = Decimal(str(val_float)).quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)
                return f"{d}".replace('.', ',')
            else:
                # Sin decimales: redondeo al entero más cercano (norma ISO 80000-1)
                return f"{round(val_float)}"
        except Exception:
            return "--"

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

            self.log_message(f"Exportadas {len(rows)} linhas para {out_path}")
            messagebox.showinfo("Exportação completa", f"Exportadas {len(rows)} linhas para:\n{out_path}")
        except Exception as e:
            self.log_message(f"Erro ao exportar calibrações: {e}")
            messagebox.showerror("Erro", f"Erro ao exportar calibrações: {e}")

    def import_calibrations_gui(self, parent=None):
        """Permite ao usuário selecionar um CSV de calibrações e importá-lo para CALIBRATIONS_DIR."""
        try:
            from config import CALIBRATIONS_DIR
        except Exception:
            self.log_message("Não foi encontrado CALIBRATIONS_DIR no config.")
            return

        # Abrir filedialog con parent si fue proporcionado para mantener la ventana de config encima
        try:
            if parent:
                path = filedialog.askopenfilename(parent=parent, title="Selecionar CSV de calibrações", filetypes=[("Arquivos CSV", "*.csv")])
            else:
                path = filedialog.askopenfilename(title="Selecionar CSV de calibrações", filetypes=[("Arquivos CSV", "*.csv")])
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
                # Replace curva_celda.csv and apply each column as a calibration
                dest = os.path.join(CALIBRATIONS_DIR, 'curva_celda.csv')
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
                    if hasattr(self.data_processor) and self.data_processor:
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
                                    self.log_message(f"Calibração aplicada a partir da importação (curvas) para target={target} pontos={len(pts)}")
                                else:
                                    self.data_processor.calibration_segments = pts
                                    self.data_processor.calibration_method = 'segments'
                                    applied_report.append((target, len(pts)))
                            except Exception as e:
                                self.log_message(f"Falha ao aplicar calibração importada para target={target}: {e}")
                except Exception as e:
                    self.log_message(f"Erro ao processar CSV importado (amplo): {e}")
                    messagebox.showerror("Erro", f"CSV importado, mas não pôde ser processado: {e}")
            else:
                # Legacy / long format: copy to calibrations.csv and reuse existing loader
                dest = os.path.join(CALIBRATIONS_DIR, 'calibrations.csv')
                shutil.copy2(path, dest)
                self.log_message(f"CSV de calibrações importado para {dest} (formato longo)")
                try:
                    # Reuse existing logic that parses long format and applies
                    self._apply_saved_calibrations_on_connect()
                    self.log_message("Calibrações aplicadas a partir de CSV importado (longo).")
                except Exception as e:
                    self.log_message(f"Erro ao aplicar calibrações a partir do CSV importado: {e}")
                    messagebox.showwarning("Aviso", f"CSV importado, mas não foi possível aplicar as calibrações: {e}")

            # Mostrar informe resumido al usuario si hubo aplicaciones
            try:
                if applied_report:
                    lines = [f"{t}: {n} pontos" for (t, n) in applied_report]
                    msg = "Foram aplicadas as seguintes curvas:\n" + "\n".join(lines)
                    messagebox.showinfo("Importação completa", msg)
                else:
                    # Si no aplicó nada y no hubo error, mostrar confirmación de copia
                    if not is_wide:
                        messagebox.showinfo("Importação", f"CSV importado para:\n{dest}")
                    else:
                        if not applied_report:
                            messagebox.showinfo("Importação", f"CSV importado para:\n{dest}\nMas não foram aplicadas curvas (arquivo vazio ou valores inválidos).")
            except Exception:
                pass
        except Exception as e:
            self.log_message(f"Falha ao importar CSV: {e}")
            messagebox.showerror("Erro", f"Falha ao importar CSV: {e}")

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
        
        # Centralizar em relao  la tela
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
        dialog.deiconify()
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()
        try:
            dialog.attributes('-topmost', True)
        except Exception:
            pass
        
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

    def show_large_tare_confirmation(self, title, message):
        """Mostra um diálogo modal personalizado com 3 botões (SOBRESCREVER, LIMPAR TARA, CANCELAR)."""
        result = {'value': 'cancel', 'done': False}
        
        # Obtener la ventana padre
        parent = self._cal_wizard if hasattr(self, '_cal_wizard') and self._cal_wizard else self
        
        # ... Liberar grab del padre si existe ...
        try:
            parent.grab_release()
        except:
            pass
        
        # Crear janela secundária SIN BARRA DE TÍTULO
        dialog = ttk.Toplevel(parent)
        dialog.overrideredirect(True)  # Quitar barra de Windows
        
        # Centralizar em relação a la tela (un poco más ancha para 3 botones grandes)
        screen_w = dialog.winfo_screenwidth()
        screen_h = dialog.winfo_screenheight()
        x = (screen_w // 2) - 375
        y = (screen_h // 2) - 225
        dialog.geometry(f"750x450+{x}+{y}")
        
        # Forzar que aparezca arriba de todo
        dialog.attributes('-topmost', True)
            
        # Container con borde para definir el diálogo
        outer_frame = ttk.Frame(dialog, bootstyle="dark", padding=4)
        outer_frame.pack(fill=BOTH, expand=YES)
        
        frame = ttk.Frame(outer_frame, padding=40)
        frame.pack(fill=BOTH, expand=YES)
        
        # Título personalizado
        title_lbl = ttk.Label(frame, text=title.upper(), font=("Segoe UI", 22, "bold"), foreground="#1e293b")
        title_lbl.pack(pady=(0, 25))
        
        # Mensagem grande
        lbl = ttk.Label(frame, text=message, font=("Segoe UI", 18), wraplength=650, justify="center")
        lbl.pack(pady=(10, 50), expand=YES)
        
        # Botões grandes
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X, pady=10)
        
        def on_overwrite():
            result['value'] = 'overwrite'
            result['done'] = True
            
        def on_clear():
            result['value'] = 'clear'
            result['done'] = True

        def on_cancel():
            result['value'] = 'cancel'
            result['done'] = True
            
        btn_overwrite = ttk.Button(btn_frame, text="SOBRESCREVER", bootstyle="success", width=15, 
                                   command=on_overwrite, padding=(10, 20))
        btn_overwrite.pack(side=LEFT, padx=10, expand=YES, fill=X)
        
        btn_clear = ttk.Button(btn_frame, text="LIMPAR TARA", bootstyle="warning", width=15, 
                               command=on_clear, padding=(10, 20))
        btn_clear.pack(side=LEFT, padx=10, expand=YES, fill=X)
        
        btn_cancel = ttk.Button(btn_frame, text="CANCELAR", bootstyle="danger", width=15, 
                                command=on_cancel, padding=(10, 20))
        btn_cancel.pack(side=LEFT, padx=10, expand=YES, fill=X)

        # Configurar cierre con protocolo
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)

        dialog.transient(parent)
        dialog.deiconify()
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()
        try:
            dialog.attributes('-topmost', True)
        except Exception:
            pass
        
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
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
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
        dialog.deiconify()
        dialog.lift()
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
        
        # Centrar sempre en pantalla para evitar offsets raros tras minimizar/restaurar.
        self._center_toplevel(dialog, w_dlg, h_dlg)
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
        dialog.update_idletasks()
        dialog.lift()
        dialog.focus_force()

        # Grab robusto: en EXE compilado el WM tarda más en registrar la ventana.
        # Reintentar hasta que winfo_viewable() confirme que el dialogo está visible.
        def _try_grab(dlg, attempts=0):
            if not dlg.winfo_exists():
                return
            try:
                if dlg.winfo_viewable():
                    dlg.grab_set()
                elif attempts < 20:          # máx ~1 s de reintentos
                    dlg.after(50, lambda: _try_grab(dlg, attempts + 1))
            except Exception:
                pass
        dialog.after(50, lambda: _try_grab(dialog))
        
        # Enviar primer intento de conexión (cada llamada es una tentativa)
        self._conn_attempt = 1
        self._conn_start_time = time.time()
        self.command_queue.put({'cmd': 'CONNECT'})
        dialog.after(100, self._check_connection_status)
    
    def _on_profile_select(self, event):
        """Maneja la selección de un perfil en la lista."""
        selection = self.tree_profiles.selection()
        if not selection:
            return
        
        item_id = selection[0]
        item = self.tree_profiles.item(item_id)
        values = item['values'] 
        # values: [ActiveChar, Name, Min, Max]

    def _update_profile_field(self, event=None):
        """Actualiza la estructura de datos interna inmediatamente al editar campos."""
        if not hasattr(self, 'current_profile_id') or not self.current_profile_id:
            return

        # Obtener valores actuales de los inputs
        name = self.entry_name.get()
        
        raw_min = self.entry_min.get().replace(',', '.')
        raw_max = self.entry_max.get().replace(',', '.')
        
        try:
            p_min = float(raw_min) if raw_min and raw_min not in ('-', '.', '-.') else 0.0
        except ValueError:
            p_min = 0.0
        try:
            p_max = float(raw_max) if raw_max and raw_max not in ('-', '.', '-.') else 0.0
        except ValueError:
            p_max = 0.0

        # Validar rango [0, 1200] — mostrar alerta si fuera de rango
        out_of_range = False
        if p_min < 0 or p_min > 1200:
            out_of_range = True
            self.entry_min.delete(0, 'end')
            self.entry_min.insert(0, "0")
            p_min = 0.0
        if p_max < 0 or p_max > 1200:
            out_of_range = True
            self.entry_max.delete(0, 'end')
            self.entry_max.insert(0, "0")
            p_max = 0.0
        
        if out_of_range:
            # Evitar mostrar alerta repetidamente mientras escribe
            if not getattr(self, '_range_alert_shown', False):
                self._range_alert_shown = True
                def _show_range_alert():
                    try:
                        # Buscar la ventana Toplevel padre (diálogo de config)
                        parent = self.entry_min.winfo_toplevel()
                        alert = ttk.Toplevel(parent)
                        alert.overrideredirect(True)

                        # Centrar sobre el diálogo padre
                        aw, ah = 480, 200
                        px = parent.winfo_rootx() + (parent.winfo_width() - aw) // 2
                        py = parent.winfo_rooty() + (parent.winfo_height() - ah) // 2
                        alert.geometry(f"{aw}x{ah}+{px}+{py}")
                        alert.configure(relief="solid", borderwidth=2)
                        
                        # Contenido
                        frm = ttk.Frame(alert, padding=20)
                        frm.pack(fill=BOTH, expand=True)
                        
                        ttk.Label(frm, text="⚠  Valor Fora do Intervalo", 
                                  font=("Segoe UI", 16, "bold"), foreground="#dc2626").pack(pady=(0, 10))
                        ttk.Label(frm, text="Os valores devem estar entre 0 e 1200 kgf.\nPor favor, insira um valor válido.",
                                  font=("Segoe UI", 13), justify="center").pack(pady=(0, 15))
                        
                        def close_alert():
                            try:
                                alert.grab_release()
                                alert.destroy()
                            except Exception:
                                pass
                            # Restaurar visibilidad y grab del diálogo de config
                            try:
                                parent.lift()
                                parent.attributes('-topmost', True)
                                parent.grab_set()
                                parent.focus_force()
                                # Quitar topmost después de un momento para no bloquear otras ventanas
                                parent.after(500, lambda: parent.attributes('-topmost', False))
                            except Exception:
                                pass
                            self._range_alert_shown = False
                        
                        ttk.Button(frm, text="OK", bootstyle="danger", 
                                   command=close_alert, padding=(30, 8)).pack()
                        
                        alert.protocol("WM_DELETE_WINDOW", close_alert)
                        alert.deiconify()
                        alert.grab_set()
                    except Exception:
                        self._range_alert_shown = False
                
                self.after(100, _show_range_alert)
            return  # No guardar valores inválidos
        else:
            self._range_alert_shown = False

        data = self._load_profiles()
        if self.current_profile_id in data["profiles"]:
            data["profiles"][self.current_profile_id]["name"] = name
            data["profiles"][self.current_profile_id]["min"] = p_min
            data["profiles"][self.current_profile_id]["max"] = p_max
            
        # Guardamos inmediatamente para que 'Active Profile' refleje cambios
        self._save_profiles(data)
        
        # Actualizar el item en el treeview sin recrear todo
        try:
            active_char = "✔" if data.get("active_profile") == self.current_profile_id else ""
            self.tree_profiles.item(self.current_profile_id, values=(active_char, name, f"{p_min:.0f}", f"{p_max:.0f}"))
        except Exception:
            pass
        
        # Refrescar display principal si es el activo
        if data.get("active_profile") == self.current_profile_id:
             self.after(200, lambda: self._update_display(self._last_sensor_data))

    def _set_active_profile(self, slot_key):
        """Define el perfil como activo y guarda."""
        data = self._load_profiles()
        if slot_key in data["profiles"]:
            data["active_profile"] = slot_key
            self._save_profiles(data)
            self._refresh_profile_list()
            # Actualizar display principal
            self._update_display(self._last_sensor_data)

    def _refresh_profile_list(self):
        """Recarga la lista de perfiles."""
        # Guardar selección actual
        sel = self.tree_profiles.selection()
        
        for item in self.tree_profiles.get_children():
            self.tree_profiles.delete(item)
            
        data = self._load_profiles()
        profiles = data.get("profiles", {})
        active = data.get("active_profile")
        
        # Ordenar por slotKey (slot_1, slot_2...)
        sorted_keys = sorted(profiles.keys())
        
        for k in sorted_keys:
            p = profiles[k]
            is_active = (k == active)
            active_char = "✔" if is_active else ""
            
            # Insertar
            self.tree_profiles.insert("", END, iid=k, values=(
                active_char,
                p.get("name", ""),
                f"{p.get('min', 0)}",
                f"{p.get('max', 0)}"
            ))
            
        # Restaurar selección
        if sel:
            try:
                self.tree_profiles.selection_set(sel)
            except:
                pass
        # Actualizar información visual del diálogo (sin reintentos automáticos por tiempo).
        # El backend notifica el fin de cada tentativa con un mensaje 'STATUS' y
        # la GUI decidirá si lanzar otra tentativa allí.
        try:
            self._conn_info.configure(text=f"Tentativa {self._conn_attempt}")
        except Exception:
            pass

        # Continuar verificando estado visual
        if getattr(self, '_connection_dialog_active', False):
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
                
            elif status == 'partial':
                # Recuperación parcial: mostrar mensaje de advertencia y permitir reintento
                if hasattr(self, '_conn_progress') and self._conn_progress.winfo_exists():
                    try:
                        self._conn_progress.stop()
                    except Exception:
                        pass

                if hasattr(self, '_conn_status') and self._conn_status.winfo_exists():
                    self._conn_status.configure(
                        text=" " + message,
                        foreground="#f59e0b"
                    )

                if hasattr(self, '_conn_btn') and self._conn_btn.winfo_exists():
                    # Permitir que el usuario reintente manualmente
                    try:
                        self._conn_btn.configure(text="REINTENTAR", state='normal')
                    except Exception:
                        pass

                # Mantener el diálogo abierto para que el usuario decida

            elif status == 'failed':
                if hasattr(self, '_conn_progress') and self._conn_progress.winfo_exists():
                    self._conn_progress.stop()

                if hasattr(self, '_conn_status') and self._conn_status.winfo_exists():
                    self._conn_status.configure(
                        text=" " + message,
                        foreground="#ef4444"
                    )

                if hasattr(self, '_conn_btn') and self._conn_btn.winfo_exists():
                    # Permitir que el usuario cierre o cancele; no cerrar automáticamente
                    self._conn_btn.configure(text="CANCELAR", state='normal')

                # No cerrar el diálogo automáticamente: la GUI controlará reintentos
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
        import time

        # Evitar doble apertura por doble click/toque o eventos duplicados.
        try:
            existing_dialog = getattr(self, '_config_dialog_active_ref', None)
            if existing_dialog and existing_dialog.winfo_exists():
                existing_dialog.lift()
                existing_dialog.focus_force()
                return
        except Exception:
            pass

        try:
            now_ts = time.monotonic()
            last_ts = float(getattr(self, '_last_config_open_req_ts', 0.0) or 0.0)
            if getattr(self, '_config_dialog_opening', False) and (now_ts - last_ts) < 1.0:
                return
            self._config_dialog_opening = True
            self._last_config_open_req_ts = now_ts
        except Exception:
            pass

        # Solicitar PIN de 4 dígitos usando o teclado numérico existente
        pin = self._show_numeric_keypad(
            None,
            title="Inserir senha",
            pin_mode=True,
            max_digits=4
        )
        if pin is None:
            try:
                self._config_dialog_opening = False
            except Exception:
                pass
            return  # Usuário cancelou
        pwd = pin

        # Contraseña básica hardcodeada (sin gestión adicional)
        if not pwd or pwd != '2847':
            try:
                # Usar el diálogo grande de alerta si está disponible
                self.show_alert("Acesso negado", "Senha incorreta.", "error", parent=self)
            except Exception:
                try:
                    from tkinter import messagebox
                    messagebox.showerror("Acesso negado", "Senha incorreta.")
                except Exception:
                    pass
            try:
                self._config_dialog_opening = False
            except Exception:
                pass
            return
        
        # Cargar configuración actual usando helper (lee SETTINGS_FILE o devuelve defaults)
        try:
            current_config = load_settings()
        except Exception:
            current_config = {
                "execution_mode": "REAL",
                "connection_type": "SERIAL",
                "serial_port": "COM3",
                "nodes": NODOS_CONFIG
            }

        # Mantener todos los nodos configurados en la UI

        # Crear ventana de configuración (centrada, con barra de título)
        dialog = ttk.Toplevel(self)
        try:
            dialog.withdraw()  # Ocultar imediatamente antes de configurar para evitar parpadeo
        except Exception:
            pass
        try:
            dialog.title("Configurações do Sistema")
        except Exception:
            pass
        try:
            self._config_dialog_active_ref = dialog
            self._config_dialog_opening = False
        except Exception:
            pass
        try:
            dialog.overrideredirect(False)
        except Exception:
            pass
        try:
            self._apply_window_icon(dialog)
        except Exception:
            pass
        # transient() se aplica depois de state('zoomed') para não interferir
        # com a maximização respeitando a taskbar do Windows.
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        
        # Obter área de trabalho utilizável para detecção de notebooks con resoluções menores
        work_w = screen_w
        work_h = screen_h
        try:
            import ctypes
            from ctypes import wintypes
            class RECT(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                            ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
            SPI_GETWORKAREA = 0x0030
            rect = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                work_w = rect.right - rect.left
                work_h = rect.bottom - rect.top
        except Exception:
            pass

        # Detectar se a tela é pequena (e.g. notebook 768p ou tela com alto DPI scaling)
        small_screen = (screen_h <= 800) or (work_h <= 768)

        # Parâmetros responsivos para a UI de configuração
        if small_screen:
            base_font = ('Segoe UI', self.scaled_font(13))
            base_font_bold = ('Segoe UI', self.scaled_font(13), 'bold')
            maint_font = ("Segoe UI", 13)
            maint_font_bold = ("Segoe UI", 13, "bold")
            ch_radio_font = ("Segoe UI", self.scaled_font(16), "bold")
            ch_btn_padding = (12, 8)
            ch_btn_width = 5
            tab_padding = (self.scaled(25), self.scaled(8))
            btn_pad = (self.scaled(18), self.scaled(6))
            btn_bottom_height = 60
            row_pady = 4
            btn_width = 14
        else:
            base_font = ('Segoe UI', self.scaled_font(16))
            base_font_bold = ('Segoe UI', self.scaled_font(16), 'bold')
            maint_font = ("Segoe UI", 16)
            maint_font_bold = ("Segoe UI", 16, "bold")
            ch_radio_font = ("Segoe UI", self.scaled_font(24), "bold")
            ch_btn_padding = (18, 14)
            ch_btn_width = 6
            tab_padding = (self.scaled(50), self.scaled(14))
            btn_pad = (self.scaled(24), self.scaled(8))
            btn_bottom_height = 72
            row_pady = 7
            btn_width = 16

        # El deiconify se hace al final, luego de construir todos los widgets,
        # para que la ventana aparezca completamente formada sin flash de contenido vacío.
        # Asegurar que el diálogo reciba foco de teclado al hacer click en él
        def _on_dialog_click(event):
            try:
                widget = event.widget
                # Si el click fue en un widget que acepta input, darle foco
                if isinstance(widget, (ttk.Entry, ttk.Combobox)):
                    widget.focus_set()
                else:
                    dialog.focus_force()
            except Exception:
                pass
        dialog.bind("<Button-1>", _on_dialog_click)
        # No usar fullscreen para facilitar multitarea — diálogo centralizado

        # Si la ventana principal se minimiza, cerrar el diálogo de configuración
        # para evitar que quede oculto con foco capturado.
        def _on_main_minimize(event=None):
            try:
                if str(self.state()) == 'iconic' and dialog.winfo_exists():
                    try:
                        dialog.destroy()
                    except Exception:
                        pass
            except Exception:
                pass

        _cfg_unmap_bind_id = None
        try:
            _cfg_unmap_bind_id = self.bind('<Unmap>', _on_main_minimize, add='+')
        except Exception:
            _cfg_unmap_bind_id = None

        # Estilos para pestañas grandes, modernas y centradas
        style = ttk.Style()
        style.configure('CfgTab.TNotebook',
                        background='#f1f5f9', tabposition='nw')
        style.configure('CfgTab.TNotebook.Tab',
                        font=('Segoe UI', self.scaled_font(13 if small_screen else 15), 'bold'),
                        padding=tab_padding,
                        background='#e2e8f0',
                        foreground='#475569',
                        anchor='center')
        style.map('CfgTab.TNotebook.Tab',
                  background=[('selected', '#2563eb'), ('active', '#dbeafe')],
                  foreground=[('selected', 'white'), ('active', '#1e40af')])
        
        # Funo de fechamento seguro
        def safe_close_dialog():
            try:
                if _cfg_unmap_bind_id:
                    self.unbind('<Unmap>', _cfg_unmap_bind_id)
            except Exception:
                pass
            try:
                self._config_dialog_active_ref = None
                self._config_dialog_opening = False
            except Exception:
                pass
            try:
                dialog.grab_release()
            except:
                pass
            try:
                dialog.destroy()
            except:
                pass
            try:
                self.unbind('<FocusIn>')
            except Exception:
                pass
            # Limpiar referencias a botones del diálogo para evitar referencias muertas
            try:
                if hasattr(self, 'btn_connect_dialog'):
                    try:
                        delattr(self, 'btn_connect_dialog')
                    except Exception:
                        try:
                            self.btn_connect_dialog = None
                        except Exception:
                            pass
            except Exception:
                pass

        # Contenedor raíz del diálogo (sin borde para aprovechar todo el espacio)
        border_frame = ttk.Frame(dialog, padding=0)
        border_frame.pack(fill=BOTH, expand=YES)

        # Barra de título interna do diálogo
        title_bar = tk.Frame(border_frame, bg='#2563eb', height=self.scaled(52))
        title_bar.pack(fill=X, side=TOP)
        title_bar.pack_propagate(False)
        tk.Label(
            title_bar,
            text="⚙  Configurações do Sistema",
            bg='#2563eb', fg='white',
            font=('Segoe UI', self.scaled_font(17), 'bold'),
            anchor='w', padx=self.scaled(20)
        ).pack(side=LEFT, fill=Y)

        main_frame = ttk.Frame(border_frame, padding=(14, 8, 14, 0))
        main_frame.pack(fill=BOTH, expand=True)
        
        # Variable para almacenar referencia a save_config (se define después)
        save_config_ref = [None]
        
        def do_save():
            if save_config_ref[0]:
                save_config_ref[0]()

        # ===========================================================
        # BARRA DE BOTONES INFERIOR — diseño profesional con dos zonas
        # ===========================================================
        btn_bottom_bar = tk.Frame(border_frame, bg='#f1f5f9', height=self.scaled(btn_bottom_height))
        btn_bottom_bar.pack(fill=X, side=BOTTOM)
        btn_bottom_bar.pack_propagate(False)

        # Línea divisoria superior de la barra
        tk.Frame(btn_bottom_bar, bg='#cbd5e1', height=1).pack(fill=X, side=TOP)

        # Contenedor interior con padding horizontal
        btn_inner = tk.Frame(btn_bottom_bar, bg='#f1f5f9')
        btn_inner.pack(fill=BOTH, expand=True, padx=self.scaled(20), pady=self.scaled(6 if small_screen else 10))

        # Zona IZQUIERDA — botón principal SALVAR (verde prominente)
        left_zone = tk.Frame(btn_inner, bg='#f1f5f9')
        left_zone.pack(side=LEFT)

        btn_salvar = ttk.Button(
            left_zone, text="✔  SALVAR",
            bootstyle="success",
            command=do_save,
            width=btn_width,
            padding=btn_pad
        )
        btn_salvar.configure(style='Large.success.TButton')
        try:
            btn_salvar._orig_style = 'Large.success.TButton'
            btn_salvar._orig_width = btn_width
        except Exception:
            pass
        btn_salvar.pack(side=LEFT)

        # Zona DERECHA — CANCELAR y FECHAR
        right_zone = tk.Frame(btn_inner, bg='#f1f5f9')
        right_zone.pack(side=RIGHT)

        # Logo (si existe) antes de los botones de cierre
        try:
            import os, sys as _sys
            _logo2_path = os.path.join(BASE_DIR, "assets", "logo2.png")
            _logo2_h = self.scaled(36 if small_screen else 44)
            if Image is not None and ImageTk is not None and os.path.exists(_logo2_path):
                if not hasattr(self, 'config_logo2_img') or self.config_logo2_img is None:
                    _pil = Image.open(_logo2_path)
                    _w = int(_pil.size[0] * (_logo2_h / float(_pil.size[1])))
                    try:
                        _rs = getattr(Image, 'Resampling', Image).LANCZOS
                        _pil = _pil.resize((_w, _logo2_h), _rs)
                    except Exception:
                        _pil = _pil.resize((_w, _logo2_h))
                    self.config_logo2_img = ImageTk.PhotoImage(_pil)
                ttk.Label(right_zone, image=self.config_logo2_img,
                          style='Logo.TLabel').pack(side=RIGHT, padx=(self.scaled(20), 0))
        except Exception:
            pass

        btn_fechar = ttk.Button(
            right_zone, text="✕  FECHAR",
            bootstyle="danger",
            command=safe_close_dialog,
            width=btn_width,
            padding=btn_pad
        )
        btn_fechar.configure(style='Large.danger.TButton')
        btn_fechar.pack(side=RIGHT, padx=(self.scaled(8), 0))

        btn_cancelar = ttk.Button(
            right_zone, text="Cancelar",
            bootstyle="secondary-outline",
            command=safe_close_dialog,
            width=btn_width,
            padding=btn_pad
        )
        btn_cancelar.configure(style='Large.secondary.Outline.TButton')
        btn_cancelar.pack(side=RIGHT, padx=(0, self.scaled(8)))
        # ==================== FIN BARRA DE BOTONES ====================
        
        # === NOTEBOOK (TABS) — estilo CfgTab ===
        notebook = ttk.Notebook(main_frame, style='CfgTab.TNotebook')
        notebook.pack(fill=BOTH, expand=True, pady=(6, 0))

        def _sync_cfg_tab_width(event=None):
            try:
                tab_count = len(notebook.tabs())
                if tab_count <= 0:
                    return
                w = int(notebook.winfo_width())
                if w <= 1:
                    return
                avail = max(1, w - self.scaled(16))
                per_tab_px = max(1, int(avail / tab_count))
                try:
                    import tkinter.font as tkfont
                    tab_font = style.lookup('CfgTab.TNotebook.Tab', 'font')
                    f = tkfont.Font(font=tab_font) if tab_font else tkfont.nametofont('TkDefaultFont')
                    char_w = max(1, int(f.measure('0')))
                except Exception:
                    char_w = 8
                tab_chars = max(6, int(per_tab_px / char_w))
                style.configure('CfgTab.TNotebook.Tab', width=tab_chars)
            except Exception:
                pass

        try:
            notebook.bind('<Configure>', _sync_cfg_tab_width, add='+')
            notebook.after(50, _sync_cfg_tab_width)
        except Exception:
            pass

        # --- TAB 1: Configuração (Existing) ---
        tab_config = ttk.Frame(notebook, padding=10)
        notebook.add(tab_config, text="Configuração")
        
        # Usar ScrolledFrame para evitar cortes em resoluções menores
        from ttkbootstrap.scrolled import ScrolledFrame
        sf_config = ScrolledFrame(tab_config, autohide=True)
        sf_config.pack(fill=BOTH, expand=YES)
        
        # Legacy variable name mapping to preserve existing logic below
        tab_nodes = sf_config

        # --- TAB 2: Modbus ---
        tab_modbus = ttk.Frame(notebook, padding=10)
        notebook.add(tab_modbus, text="Modbus")
        
        sf_modbus = ScrolledFrame(tab_modbus, autohide=True)
        sf_modbus.pack(fill=BOTH, expand=YES)

        # --- TAB 3: Manutenção (New) ---
        tab_maint = ttk.Frame(notebook, padding=10)
        notebook.add(tab_maint, text="Manutenção")
        
        # === MAINTENANCE TAB UI & LOGIC ===
        maint_cols = ttk.Frame(tab_maint)
        maint_cols.pack(fill=BOTH, expand=True)
        maint_cols.columnconfigure(0, weight=1) # List
        maint_cols.columnconfigure(1, weight=1) # Editor
        maint_cols.rowconfigure(0, weight=1)     # Stretch vertically

        # Estilo de fuente para campos de mantenimiento (ya definidos dinámicamente)

        frame_list = ttk.Labelframe(maint_cols, text="Perfis", padding=15, borderwidth=self.scaled(3), relief='solid', labelanchor='n', style='Panel.TLabelframe')
        frame_list.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=8)
        
        # Treeview for profiles
        cols = ("status", "name", "min", "max")
        tv = ttk.Treeview(frame_list, columns=cols, show='headings', height=5)
        tv.heading("status", text="Ativo")
        tv.heading("name", text="Nome")
        tv.heading("min", text="Mín (kgf)")
        tv.heading("max", text="Máx (kgf)")
        # Columnas iguales, se ajustan al espacio disponible
        for c in cols:
            tv.column(c, width=80, minwidth=60, anchor="center", stretch=True)
        
        # Aumentar fuente del Treeview para coincidir con labels del editor
        try:
            style = ttk.Style()
            style.configure("Treeview", font=maint_font, rowheight=self.scaled(32 if small_screen else 40))
            style.configure("Treeview.Heading", font=maint_font_bold)
        except Exception:
            pass

        tv.pack(fill=BOTH, expand=True)
        self.tree_profiles = tv

        # Right: Editor de Perfis
        frame_editor = ttk.Labelframe(maint_cols, text="Editor de Perfil", padding=15, borderwidth=self.scaled(3), relief='solid', labelanchor='n', style='Panel.TLabelframe')
        frame_editor.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=8)
        frame_editor.columnconfigure(0, weight=1)
        for r in range(8):
            frame_editor.rowconfigure(r, weight=1)
        
        ttk.Label(frame_editor, text="Nome do Perfil:", font=maint_font_bold).grid(row=0, column=0, sticky="w", pady=2)
        e_pname = ttk.Entry(frame_editor, font=maint_font)
        e_pname.grid(row=1, column=0, sticky="ew", ipady=self.scaled(4), pady=2)
        
        vcmd = (self.register(self._validate_numeric_input), '%P')

        ttk.Label(frame_editor, text="Peso Mínimo (kgf):", font=maint_font_bold).grid(row=2, column=0, sticky="w", pady=2)
        e_pmin = ttk.Entry(frame_editor, font=maint_font, validate="key", validatecommand=vcmd)
        e_pmin.grid(row=3, column=0, sticky="ew", ipady=self.scaled(4), pady=2)

        ttk.Label(frame_editor, text="Peso Máximo (kgf):", font=maint_font_bold).grid(row=4, column=0, sticky="w", pady=2)
        e_pmax = ttk.Entry(frame_editor, font=maint_font, validate="key", validatecommand=vcmd)
        e_pmax.grid(row=5, column=0, sticky="ew", ipady=self.scaled(4), pady=2)

        # Asignar a self para acceso en callbacks
        self.entry_name = e_pname
        self.entry_min = e_pmin
        self.entry_max = e_pmax

        # Bindings para actualización inmediata
        self.entry_name.bind("<KeyRelease>", self._update_profile_field)
        self.entry_min.bind("<KeyRelease>", self._update_profile_field)
        self.entry_max.bind("<KeyRelease>", self._update_profile_field)

        # Rótulo do perfil ativo
        lbl_active_status = ttk.Label(frame_editor, text="Perfil Ativo: -", font=("Segoe UI", 14, "bold"), foreground="#16a34a", anchor='center')
        lbl_active_status.grid(row=6, column=0, sticky="ew", pady=5)

        def load_profiles_to_ui():
            # Clear tree
            for item in tv.get_children():
                tv.delete(item)
            
            data = self._load_profiles()
            profiles = data.get("profiles", {})
            active_slot = data.get("active_profile")
            
            # Load fixed slots 1-5
            for i in range(1, 6):
                slot_id = f"slot_{i}"
                if slot_id in profiles:
                    prof = profiles[slot_id]
                    p_name = prof.get("name", f"Perfil {i}")
                    p_min = prof.get("min", 0)
                    p_max = prof.get("max", 0)
                    
                    is_active = (slot_id == active_slot)
                    status_indicator = "✔" if is_active else ""
                    
                    tags = ('active',) if is_active else ()
                    tv.insert("", "end", iid=slot_id, values=(status_indicator, p_name, p_min, p_max), tags=tags)
            
            # Update tag style
            tv.tag_configure('active', font=("Segoe UI", 16, "bold"), background="#dcfce7") # Light green bg, same size

            # Update active label status
            act_name = profiles.get(active_slot, {}).get("name", "Nenhum") if active_slot else "Nenhum"
            if 'lbl_active_status' in locals():
                lbl_active_status.configure(text=f"Perfil Ativo: {act_name}")

        def on_tv_select(event):
            """Seleccionar perfil para edición (NO activa automáticamente)."""
            sel = tv.selection()
            if not sel: return
            slot_id = sel[0]
            self.current_profile_id = slot_id
            
            # Get data from profiles
            data = self._load_profiles()
            profiles_dict = data.get("profiles", {})
            prof = profiles_dict.get(slot_id, {})
            
            # Fill editor fields only — no activation
            self.entry_name.delete(0, END)
            self.entry_name.insert(0, prof.get("name", ""))
            self.entry_min.delete(0, END)
            self.entry_min.insert(0, str(prof.get("min", 0)))
            self.entry_max.delete(0, END)
            self.entry_max.insert(0, str(prof.get("max", 0)))

        tv.bind("<<TreeviewSelect>>", on_tv_select)

        def activate_selected_profile():
            """Activar el perfil seleccionado actualmente."""
            sel = tv.selection()
            if not sel:
                try:
                    self.show_alert("Aviso", "Selecione um perfil na lista primeiro.", parent=dialog)
                except Exception:
                    pass
                return
            slot_id = sel[0]
            data = self._load_profiles()
            profiles_dict = data.get("profiles", {})
            prof = profiles_dict.get(slot_id, {})
            
            data["active_profile"] = slot_id
            self._save_profiles(data)
            
            self.log_message(f"Perfil '{prof.get('name')}' ativado.")
            
            # Update Treeview tags visually
            for child in tv.get_children():
                if child == slot_id:
                    tv.item(child, tags=('active',), values=("✔", tv.item(child, 'values')[1], tv.item(child, 'values')[2], tv.item(child, 'values')[3]))
                else:
                    tv.item(child, tags=(), values=("", tv.item(child, 'values')[1], tv.item(child, 'values')[2], tv.item(child, 'values')[3]))
            
            # Update active label
            act_name = prof.get("name", "Nenhum")
            lbl_active_status.configure(text=f"Perfil Ativo: {act_name}")
            
            # Refresh main display
            try:
                self._update_display(self._last_sensor_data)
            except Exception:
                pass

        btn_activate = ttk.Button(
            frame_editor,
            text="✔  ATIVAR PERFIL",
            bootstyle="success",
            command=activate_selected_profile,
        )
        btn_activate.grid(row=7, column=0, sticky="ew", ipadx=self.scaled(10), ipady=self.scaled(8), pady=5)

        try:
            load_profiles_to_ui()
        except Exception:
            pass

        # Fonte base uniforme para toda a aba de configuração
        base_font = ('Segoe UI', self.scaled_font(16))
        base_font_bold = ('Segoe UI', self.scaled_font(16), 'bold')
        # Garantir que o Combobox da listagem use a mesma fonte
        try:
            self.option_add('*TCombobox*Listbox.font', base_font)
        except Exception:
            pass
        try:
            style = ttk.Style()
            style.configure('Trans.Check.TCheckbutton', font=base_font)
            style.configure('Trans.CheckBig.TCheckbutton', font=base_font)
        except Exception:
            pass
        
        
        # Preparar lista de puertos COM disponibles (se usará tanto para nodos como para transmisión)
        com_values = []
        try:
            import serial.tools.list_ports
            com_list = serial.tools.list_ports.comports()
            com_values = [p.device for p in com_list]
        except Exception:
            com_values = []

        current_port = current_config.get("transmissao", {}).get("porta", current_config.get("serial_port", "COM3"))
        if not com_values:
            com_values.append(current_port)
        elif current_port not in com_values:
            com_values.append(current_port)

        try:
            com_values.sort(key=lambda x: int(x.replace('COM', '')) if x.startswith('COM') and x[3:].isdigit() else x)
        except Exception:
            pass

        # Import/Export moved to the CALIBRACAO tab (see _setup_calibration_tab)

        node_entries = {}
        
        # === CONTENEDOR PRINCIPAL: Configuração do Nó ===
        main_content = ttk.Frame(tab_nodes)
        if small_screen:
            main_content.pack(fill=BOTH, expand=True, pady=(15, self.scaled(30)))
        else:
            main_content.pack(fill=BOTH, expand=True, pady=(15, 0))
        main_content.columnconfigure(0, weight=1)
        main_content.columnconfigure(1, weight=1)
        main_content.rowconfigure(0, weight=0) # Porta serial + Calibrar Carga
        main_content.rowconfigure(1, weight=1) # Configuração dos Nós frame

        # === TAB MODBUS: Transmissão de Dados ===
        modbus_content = ttk.Frame(sf_modbus)
        modbus_content.pack(fill=BOTH, expand=True, pady=(15, 0))
        modbus_content.columnconfigure(0, weight=1)
        modbus_content.rowconfigure(0, weight=1)

        discover_frame = ttk.Labelframe(
            modbus_content, text="Transmissão de Dados",
            padding=15, borderwidth=self.scaled(3),
            relief='solid', labelanchor='n', style='Panel.TLabelframe'
        )
        discover_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        discover_frame.rowconfigure(0, weight=1)
        discover_frame.columnconfigure(0, weight=1)
        try:
            discover_frame.grid_propagate(True)
        except Exception:
            pass
        # Estilo para los panels / Descoberta: etiqueta en negrita y fuente ligeramente mayor
        try:
            style = ttk.Style()
            style.configure('Panel.TLabelframe.Label', font=("Segoe UI", self.scaled(13), 'bold'))
            # Estilo para el botón de calibración por nodo (más grande)
            try:
                style.configure('Calib.Node.TButton', font=("Segoe UI", self.scaled_font(16), 'bold'), padding=(self.scaled(8), self.scaled(6)))
            except Exception:
                try:
                    style.configure('Calib.Node.TButton', font=("Segoe UI", 16, 'bold'))
                except Exception:
                    pass
        except Exception:
            try:
                style.configure('Panel.TLabelframe.Label', font=("Segoe UI", 13, 'bold'))
            except Exception:
                pass
        
        # ==================== Seção de Transmissão Modbus ====================

        trans_grid = ttk.Frame(discover_frame)
        trans_grid.pack(fill=BOTH, expand=True, pady=10)
        trans_grid.columnconfigure(0, weight=0, minsize=self.scaled(140))
        trans_grid.columnconfigure(1, weight=0)
        for r in range(7):
            trans_grid.rowconfigure(r, weight=0)
        row_pad = self.scaled(4 if small_screen else 6)

        ttk.Label(trans_grid, text="Porta:", font=base_font_bold).grid(row=0, column=0, sticky='w', padx=(0, 20), pady=row_pad)
        try:
            entry_trans = ttk.Combobox(trans_grid, font=base_font, values=com_values)
            entry_trans.set(current_port)
        except Exception:
            entry_trans = ttk.Entry(trans_grid, font=base_font)
            entry_trans.insert(0, current_port)
        entry_trans.grid(row=0, column=1, sticky='w', ipady=self.scaled(4), pady=row_pad)
        try:
            entry_trans.configure(width=14)
        except Exception:
            pass

        ttk.Label(trans_grid, text="Velocidade:", font=base_font_bold).grid(row=1, column=0, sticky='w', padx=(0, 20), pady=row_pad)
        entry_baud = ttk.Combobox(trans_grid, font=base_font, values=['9600', '19200', '38400', '57600', '115200'])
        modbus_cfg = current_config.get('transmissao', {})
        baud_val = modbus_cfg.get('velocidade', current_config.get('baudrate', 115200))
        entry_baud.set(str(baud_val))
        entry_baud.grid(row=1, column=1, sticky='w', ipady=self.scaled(4), pady=row_pad)
        try:
            entry_baud.configure(width=14)
        except Exception:
            pass

        try:
            style = ttk.Style()
            modbus_rb_pad = (self.scaled(8), self.scaled(4)) if small_screen else (self.scaled(14), self.scaled(8))
            style.configure('Modbus.Radio.TRadiobutton', font=base_font_bold, padding=modbus_rb_pad)
        except Exception:
            pass

        ttk.Label(trans_grid, text="Paridade:", font=base_font_bold).grid(row=4, column=0, sticky='w', padx=(0, 20), pady=row_pad)
        parity_val = modbus_cfg.get('paridade', current_config.get('paridade', 'Nenhuma'))
        parity_var = tk.StringVar(value=parity_val)
        parity_frame = ttk.Frame(trans_grid)
        parity_frame.grid(row=4, column=1, sticky='w', pady=row_pad)
        for label in ['Nenhuma', 'Par', 'Ímpar']:
            rb = ttk.Radiobutton(
                parity_frame,
                text=label,
                value=label,
                variable=parity_var,
                bootstyle='info',
                style='Modbus.Radio.TRadiobutton'
            )
            rb.pack(side=LEFT, padx=self.scaled(8))

        ttk.Label(trans_grid, text="ID Escravo:", font=base_font_bold).grid(row=3, column=0, sticky='w', padx=(0, 20), pady=row_pad)
        e_slave = ttk.Entry(trans_grid, font=base_font)
        slave_val = modbus_cfg.get('id_escravo_pc', current_config.get('id_escravo_pc', 1))
        e_slave.insert(0, str(slave_val))
        e_slave.grid(row=3, column=1, sticky='w', ipady=self.scaled(4), pady=row_pad)
        try:
            e_slave.configure(width=14)
        except Exception:
            pass

        swap_val = modbus_cfg.get('swap_words', current_config.get('swap_words', False))
        swap_var = tk.StringVar(value='Sim' if bool(swap_val) else 'Não')
        swap_frame = ttk.Frame(trans_grid)
        swap_frame.grid(row=5, column=0, columnspan=2, sticky='w', pady=row_pad)
        ttk.Label(swap_frame, text='Inverter Bytes (Swap Words):', font=base_font_bold).pack(side=LEFT, padx=(0, 10))
        for label in ['Sim', 'Não']:
            rb = ttk.Radiobutton(
                swap_frame,
                text=label,
                value=label,
                variable=swap_var,
                bootstyle='info',
                style='Modbus.Radio.TRadiobutton'
            )
            rb.pack(side=LEFT, padx=self.scaled(8))

        # Spacer no longer needed as trans_grid expands with grid weights
        
        # =====================================================================
        # === Porta Serial (Gateway USB) ===
        port_frame = ttk.Labelframe(
            main_content, text='Porta Serial (Gateway USB)',
            padding=(15, 6), borderwidth=self.scaled(2),
            relief='solid', labelanchor='n', style='Panel.TLabelframe'
        )
        port_frame.grid(row=0, column=0, sticky='nsew', padx=(8, 4), pady=(4, 8))
        
        port_grid = ttk.Frame(port_frame)
        port_grid.pack(fill=X)
        port_grid.columnconfigure(1, weight=1)
        
        ttk.Label(port_grid, text="Porta COM:", font=base_font_bold).grid(row=0, column=0, sticky="w", padx=(0, 15), pady=4)
        
        # Función para escanear puertos COM disponibles
        def _scan_com_ports():
            com_vals = []
            try:
                import serial.tools.list_ports
                com_list = serial.tools.list_ports.comports()
                com_vals = [p.device for p in com_list]
            except:
                com_vals = []
            try:
                cur = entry_serial.get()
            except:
                cur = current_config.get("serial_port", "COM3")
            if not cur:
                cur = current_config.get("serial_port", "COM3")
            if not com_vals:
                com_vals.append(cur)
            elif cur not in com_vals:
                com_vals.append(cur)
            try:
                com_vals.sort(key=lambda x: int(x.replace('COM', '')) if x.startswith('COM') and x[3:].isdigit() else x)
            except:
                pass
            return com_vals
            
        current_port = current_config.get("serial_port", "COM3")
        
        entry_serial = ttk.Combobox(port_grid, font=base_font, values=_scan_com_ports(), width=12, state='readonly')
        entry_serial.set(current_port)
        entry_serial.grid(row=0, column=1, sticky="w", ipady=self.scaled(4), pady=4)
        
        # Botón para refrescar puertos COM disponibles
        def _refresh_com_ports():
            new_vals = _scan_com_ports()
            entry_serial['values'] = new_vals
            
        btn_refresh = ttk.Button(
            port_grid, text="Atualizar Portos", command=_refresh_com_ports,
            bootstyle="info-outline"
        )
        btn_refresh.grid(row=0, column=2, sticky="w", padx=(8, 0), pady=4)

        # === Botão Calibrar Carga (ao lado da seção de porta COM) ===
        cal_frame = ttk.Labelframe(
            main_content, text='Calibração',
            padding=(15, 6), borderwidth=self.scaled(2),
            relief='solid', labelanchor='n', style='Panel.TLabelframe'
        )
        cal_frame.grid(row=0, column=1, sticky='nsew', padx=(4, 8), pady=(4, 8))
        cal_frame.columnconfigure(0, weight=1)
        cal_frame.rowconfigure(0, weight=1)

        def start_cal_from_top():
            # Sincronizar current_config con los valores actuales de los campos
            try:
                if 'nodes' not in current_config or not isinstance(current_config['nodes'], dict):
                    current_config['nodes'] = {}
                for k, inputs in node_entries.items():
                    try:
                        nid = int(inputs['id'].get())
                    except Exception:
                        nid = 0
                    try:
                        serial_v = inputs['serial'].get()
                    except Exception:
                        serial_v = ''
                    try:
                        com_v = inputs['com'].get()
                    except Exception:
                        com_v = ''
                    angle_list = []
                    for v in inputs.get('ch_angles', []):
                        try:
                            val = v.get()
                        except Exception:
                            val = ""
                        if val:
                            angle_list.append(val)
                    ch_angle_fallback = angle_list[0] if angle_list else 'ch2'
                    current_config['nodes'][k] = {
                        'id': nid,
                        'ch_load': inputs['ch_load'].get(),
                        'ch_angles': angle_list,
                        'ch_angle': ch_angle_fallback,
                        'load_enabled': bool(inputs.get('load_enabled').get()) if inputs.get('load_enabled') else True,
                        'ch': inputs['ch_load'].get(),
                        'serial': serial_v,
                        'com_port': com_v
                    }
            except Exception:
                pass
            try:
                sensor_name = 'celda_1'
                try:
                    dialog.grab_release()
                except Exception:
                    pass
                self._open_calibration_wizard(current_config, sensor_name, dialog)
            except Exception as e:
                try:
                    self.show_alert("Erro", f"Não foi possível iniciar calibração: {e}", "error", parent=cal_frame)
                except Exception:
                    pass

        btn_cal_top = ttk.Button(
            cal_frame, text="CALIBRAR CARGA",
            command=start_cal_from_top, bootstyle="success")
        try:
            btn_cal_top.configure(style='Calib.Node.TButton')
        except Exception:
            pass
        btn_cal_top.pack(fill=BOTH, expand=True, ipadx=self.scaled(10), ipady=self.scaled(8))

        # === Configuração dos Nós ===
        panel1 = ttk.Labelframe(
            main_content, text='Configuração dos Nós',
            padding=14, borderwidth=self.scaled(2),
            relief='solid', labelanchor='n', style='Panel.TLabelframe'
        )
        panel1.grid(row=1, column=0, columnspan=2, rowspan=1, sticky='nsew', padx=8, pady=8)
        panel1.columnconfigure(0, weight=1)
        panel1.columnconfigure(1, weight=1)
        panel1.rowconfigure(0, weight=1)

        # Mapa fixo de canais por nó:
        # Nó 1 → Carga=ch1 | Ângulo 1=ch2 | Ângulo 2=ch3
        # Nó 2 → Ângulo 3=ch1 | Ângulo 4=ch2 | Ângulo 5=ch3
        node_definitions = [
            {
                'key': 'celda_1', 'grid_col': 0, 'title': 'Nó 1',
                'channels': [
                    {'label': 'Carga',    'ch': 'ch1', 'is_load': True},
                    {'label': 'Ângulo 1', 'ch': 'ch2', 'is_load': False},
                    {'label': 'Ângulo 2', 'ch': 'ch3', 'is_load': False},
                ],
                'defaults': {'id': 0, 'ch': 'ch1', 'serial': ''}
            },
            {
                'key': 'celda_2', 'grid_col': 1, 'title': 'Nó 2',
                'channels': [
                    {'label': 'Ângulo 3', 'ch': 'ch1', 'is_load': False},
                    {'label': 'Ângulo 4', 'ch': 'ch2', 'is_load': False},
                    {'label': 'Ângulo 5', 'ch': 'ch3', 'is_load': False},
                ],
                'defaults': {'id': 0, 'ch': 'ch1', 'serial': ''}
            },
        ]

        for node_def in node_definitions:
            key          = node_def['key']
            grid_col     = node_def['grid_col']
            node_title   = node_def['title']
            channels_def = node_def['channels']
            defaults     = node_def['defaults']

            current_node_data = current_config['nodes'].get(key, defaults)

            node_frame = ttk.Labelframe(
                panel1, text=node_title, padding=12,
                borderwidth=self.scaled(2), relief='solid', labelanchor='n'
            )
            node_frame.grid(row=0, column=grid_col, sticky='nsew', padx=8, pady=8)
            node_frame.columnconfigure(0, weight=0)
            node_frame.columnconfigure(1, weight=1)
            node_frame.rowconfigure(0, weight=1)

            cell_grid = ttk.Frame(node_frame)
            cell_grid.grid(row=0, column=0, columnspan=2, sticky='nsew')
            try:
                cell_grid.columnconfigure(0, weight=0, minsize=self.scaled(140))
                cell_grid.columnconfigure(1, weight=1)
            except Exception:
                pass

            row_idx = 0

            # ID do Nó
            ttk.Label(cell_grid, text='ID do Nó:', font=base_font_bold).grid(
                row=row_idx, column=0, sticky='w', padx=(0, 12), pady=row_pady)
            e_id = ttk.Entry(cell_grid, font=base_font, width=14)
            e_id.insert(0, str(current_node_data.get('id', 0)))
            e_id.grid(row=row_idx, column=1, sticky='ew', ipady=self.scaled(4), pady=row_pady)
            self._bind_numeric_keypad(e_id, f'ID do Nó — {node_title}')
            row_idx += 1

            # Nº de Série
            ttk.Label(cell_grid, text='Nº de Série:', font=base_font_bold).grid(
                row=row_idx, column=0, sticky='w', padx=(0, 12), pady=row_pady)
            e_serial = ttk.Entry(cell_grid, font=base_font, width=14)
            e_serial.insert(0, str(current_node_data.get('serial', '')))
            e_serial.grid(row=row_idx, column=1, sticky='ew', ipady=self.scaled(4), pady=row_pady)
            self._bind_numeric_keypad(e_serial, f'Nº Série — {node_title}')
            row_idx += 1

            # Separador e cabeçalho de canais
            try:
                ttk.Separator(cell_grid, orient='horizontal').grid(
                    row=row_idx, column=0, columnspan=2, sticky='ew', pady=(10, 3))
                row_idx += 1
                ttk.Label(
                    cell_grid, text='Atribuição de Canais',
                    font=base_font_bold, anchor='center'
                ).grid(row=row_idx, column=0, columnspan=2, sticky='ew', pady=(2, 6))
                row_idx += 1
            except Exception:
                pass

            # Variáveis de canal
            is_load_node = any(ch['is_load'] for ch in channels_def)
            ch_load_var = tk.StringVar()
            load_enabled_var = tk.BooleanVar(value=is_load_node)
            angle_vars = []

            for ch_def in channels_def:
                lbl_text   = ch_def['label']
                default_ch = ch_def['ch']
                is_load    = ch_def['is_load']

                # Ler valor salvo
                if is_load:
                    saved_val = current_node_data.get('ch_load',
                                current_node_data.get('ch', default_ch))
                    ch_var = ch_load_var
                    ch_var.set(saved_val or default_ch)
                else:
                    angle_idx  = len(angle_vars)
                    saved_list = current_node_data.get('ch_angles', [])
                    if isinstance(saved_list, list) and angle_idx < len(saved_list):
                        saved_val = saved_list[angle_idx] or default_ch
                    else:
                        saved_val = default_ch
                    ch_var = tk.StringVar(value=saved_val)
                    angle_vars.append(ch_var)

                # Etiqueta do canal (à esquerda)
                ch_lbl_font = base_font_bold if is_load else base_font
                ttk.Label(
                    cell_grid, text=lbl_text + ':',
                    font=ch_lbl_font
                ).grid(row=row_idx, column=0, sticky='w', padx=(0, 10), pady=3 if small_screen else 5)

                # Seleção de canal via Radiobuttons
                ch_btn_frame = ttk.Frame(cell_grid)
                ch_btn_frame.grid(row=row_idx, column=1, sticky='w', pady=2 if small_screen else 4)
                
                for ch_opt in ["ch1", "ch2", "ch3"]:
                    ch_btn = ttk.Radiobutton(
                        ch_btn_frame, 
                        text=f" {ch_opt[-1]} ",
                        variable=ch_var,
                        value=ch_opt,
                        bootstyle="info-toolbutton",
                        width=ch_btn_width,
                        padding=ch_btn_padding
                    )
                    ch_btn.pack(side=LEFT, padx=4 if small_screen else 6)
                    try:
                        ch_btn.configure(font=ch_radio_font)
                    except Exception:
                        pass
                row_idx += 1

            # Configurar rowconfigure para distribuir o espaço vertical em cell_grid
            try:
                for r in [0, 1, 4, 5, 6]:
                    cell_grid.rowconfigure(r, weight=1)
            except Exception:
                pass

            node_entries[key] = {
                'id': e_id,
                'ch_load': ch_load_var,
                'ch_angles': angle_vars,
                'load_enabled': load_enabled_var,
                'serial': e_serial,
                'com': entry_serial
            }

        # (Botão de calibração movido para a seção superior, ao lado da Porta COM)

        # Fin configuración de nodos

        # Definir la función save_config y asignarla a la referencia del header
        def save_config():
            # Recolectar valores de la sección de transmisión
            try:
                baud_val = int(entry_baud.get())
            except Exception:
                try:
                    baud_val = int(current_config.get('baudrate', 9600))
                except Exception:
                    baud_val = 9600
            try:
                slave_id_val = int(e_slave.get())
            except Exception:
                try:
                    slave_id_val = int(current_config.get('id_escravo_pc', current_config.get('slave_id', 1)))
                except Exception:
                    slave_id_val = 1

            # --- Construir los datos de nodos ---
            built_nodes = {}
            for key, inputs in node_entries.items():
                try:
                    nid = int(inputs["id"].get())
                except:
                    nid = 0
                serial_num = inputs.get("serial", None)
                serial_val = serial_num.get() if serial_num else ""
                com_widget = inputs.get("com")
                try:
                    com_val = com_widget.get() if com_widget else ""
                except Exception:
                    try:
                        com_val = str(com_widget.get())
                    except Exception:
                        com_val = ""
                angle_vars = inputs.get("ch_angles", [])
                angle_list = []
                for v in angle_vars:
                    try:
                        val = v.get()
                    except Exception:
                        val = ""
                    if val:
                        angle_list.append(val)
                ch_angle_fallback = angle_list[0] if angle_list else "ch2"
                load_enabled_var = inputs.get("load_enabled")
                built_nodes[key] = {
                    "id": nid,
                    "ch_load": inputs["ch_load"].get(),
                    "ch_angles": angle_list,
                    "ch_angle": ch_angle_fallback,
                    "load_enabled": bool(load_enabled_var.get()) if load_enabled_var else True,
                    "ch": inputs["ch_load"].get(),
                    "serial": serial_val,
                    "com_port": com_val
                }

            # --- Partir de la config existente para preservar claves no editadas ---
            new_config = load_settings()
            
            # Limpiar redundancias del nivel superior
            keys_to_remove = ["baudrate", "paridade", "stopbits", "bytesize", "timeout", "id_escravo_pc", "swap_words", "connection_type"]
            for k in keys_to_remove:
                if k in new_config:
                    del new_config[k]

            try:
                _porta = entry_trans.get()
            except Exception:
                _porta = current_config.get('transmissao', {}).get('porta', 'COM10')
            try:
                _paridade = parity_var.get()
            except Exception:
                _paridade = current_config.get('transmissao', {}).get('paridade', 'Nenhuma')
            try:
                _swap = True if swap_var.get() == 'Sim' else False
            except Exception:
                _swap = current_config.get('transmissao', {}).get('swap_words', False)

            new_config.update({
                "execution_mode": current_config.get('execution_mode', 'REAL'),
                "use_sensor_config": current_config.get('use_sensor_config', True),
                "serial_port": entry_serial.get(),
                "nodes": built_nodes,
                "transmissao": {
                    "porta": _porta,
                    "velocidade": baud_val,
                    "paridade": _paridade,
                    "id_escravo_pc": slave_id_val,
                    "swap_words": _swap,
                    "stopbits": current_config.get('transmissao', {}).get('stopbits', 1),
                    "bytesize": current_config.get('transmissao', {}).get('bytesize', 8),
                    "timeout": current_config.get('transmissao', {}).get('timeout', 0.005)
                }
            })
            
            try:
                # Guardar usando el helper centralizado para persistencia
                saved_ok = False
                try:
                    saved_ok = save_settings(new_config)
                except Exception:
                    saved_ok = False
                if not saved_ok:
                    # Fallback: intentar escribir manualmente
                    try:
                        from config import SETTINGS_FILE
                        config_path = SETTINGS_FILE
                        with open(config_path, 'w', encoding='utf-8') as f:
                            json.dump(new_config, f, indent=4, ensure_ascii=False)
                            saved_ok = True
                    except Exception:
                        saved_ok = False
                
                # Aplicar cambios en caliente al driver si existe
                if hasattr(self, 'driver') and self.driver:
                    try:
                        self.driver.update_nodes_config(new_config["nodes"])
                    except Exception as e:
                        print(f"[GUI] Aviso: Não foi possível atualizar o driver: {e}")

                # Recargar configuración en el DataProcessor para no requerir reinicio
                try:
                    if hasattr(self, 'data_processor') and self.data_processor:
                        try:
                            self.data_processor.nodos_config = new_config["nodes"]
                            # Re-inicializar estructuras internas (buffers, mapeos)
                            if hasattr(self.data_processor, '_initialize_structures'):
                                try:
                                    self.data_processor._initialize_structures()
                                except Exception:
                                    pass
                            # Reaplicar calibraciones disponibles para las nuevas claves
                            try:
                                self._apply_saved_calibrations_on_connect()
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    pass
                # Informar al backend para que aplique la nueva config (puerto/nodos) en caliente
                try:
                    if hasattr(self, 'command_queue') and self.command_queue:
                        try:
                            self.command_queue.put({'cmd': 'APPLY_CONFIG', 'payload': new_config})
                        except Exception:
                            pass
                except Exception:
                    pass

                
                # Mostrar el mensaje de éxito anclado a la ventana de configuración
                # Registrar y devolver el foco al diálogo de configuración sin mostrar aviso
                try:
                    self.log_message("Configuração salva e aplicada.")
                except Exception:
                    pass
                try:
                    dialog.lift()
                    dialog.focus_force()
                except Exception:
                    pass
                # Refrescar la vista de calibración para que muestre los nuevos N° de Série
                try:
                    self._refresh_calibration_sensor_serials()
                    try:
                        # También actualizar estilos/selección visual si la pestaña está abierta
                        if hasattr(self, '_cal_select_inner') and getattr(self, '_cal_select_inner', None):
                            self._update_sensor_buttons_visuals(self._cal_select_inner)
                    except Exception:
                        pass
                except Exception:
                    pass

                # Feedback visual: deshabilitar el botón SALVAR durante 5 segundos
                try:
                    # btn_salvar está en el scope exterior; cambiar estado y estilo
                    try:
                        btn_salvar.configure(state='disabled')
                    except Exception:
                        try:
                            btn_salvar.state(['disabled'])
                        except Exception:
                            pass

                    def _restore_salvar():
                        try:
                            btn_salvar.configure(state='normal')
                        except Exception:
                            try:
                                btn_salvar.state(['!disabled'])
                            except Exception:
                                pass
                        try:
                            # Restaurar estilo y ancho originales para evitar shrink
                            if getattr(btn_salvar, '_orig_style', None):
                                btn_salvar.configure(style=btn_salvar._orig_style)
                        except Exception:
                            pass
                        try:
                            if getattr(btn_salvar, '_orig_width', None) is not None:
                                btn_salvar.configure(width=btn_salvar._orig_width)
                        except Exception:
                            pass

                    # Restaurar tras ~5000 ms
                    try:
                        self.after(5000, _restore_salvar)
                    except Exception:
                        # como fallback usar timer en thread si after fallara
                        import threading
                        threading.Timer(5.0, _restore_salvar).start()
                except Exception:
                    pass
            except Exception as e:
                try:
                    dialog.grab_release()
                except:
                    pass
                try:
                    self._suppress_cfg_watch = True
                except Exception:
                    pass
                try:
                    # Mostrar error anclado al diálogo de configuración
                    self.show_alert("Erro", f"Não foi possível salvar: {e}", "error", parent=dialog)
                finally:
                    try:
                        self._suppress_cfg_watch = False
                    except Exception:
                        pass
        
        # Asignar la función a la referencia del header
        save_config_ref[0] = save_config

        # Configurar protocolo de cierre
        dialog.protocol("WM_DELETE_WINDOW", safe_close_dialog)

        # Copiar posição e tamanho real da janela principal (mesma abordagem que
        # o wizard de calibração, que funciona corretamente respeitando a taskbar).
        try:
            self.update_idletasks()
            wx = self.winfo_x()
            wy = self.winfo_y()
            ww = self.winfo_width()
            wh = self.winfo_height()
            dialog.geometry(f"{ww}x{wh}+{wx}+{wy}")
        except Exception:
            pass
        try:
            dialog.transient(self)
        except Exception:
            pass

        # Mostrar la ventana ahora que todos los widgets están construidos
        try:
            dialog.update_idletasks()
            dialog.deiconify()
            dialog.lift()
            dialog.focus_force()
        except Exception:
            pass
        try:
            dialog.grab_set()
        except:
            pass
        self.wait_window(dialog)
        try:
            self._config_dialog_active_ref = None
            self._config_dialog_opening = False
        except Exception:
            pass

    def _setup_calibration_tab(self, parent, current_config, close_config_dialog=None, config_dialog=None):
        """Configura a aba de calibração de sensores (Layout Tablet Grande)."""
        from modules.calibration import CalibrationManager

        base_font = ("Segoe UI", self.scaled_font(16))
        base_font_bold = ("Segoe UI", self.scaled_font(16), "bold")
        
        # Mapeo de nombres internos a nombres en portugués para display
        def get_display_name(internal_name):
            """Convierte nombre interno a nombre legible en portugués."""
            display_map = {
                'celda_1': 'Nó 1',
                'celda_2': 'Nó 2',
                'celda_3': 'Nó 3',
                'celda_4': 'Nó 4',
            }
            return display_map.get(internal_name, internal_name.replace('_', ' ').title())
        
        # Guardar mapeo inverso para recuperar nombre interno
        self._sensor_display_to_internal = {}
        
        # Descricao breve
        ttk.Label(parent, 
                  text="Selecione o nó e o canal de carga para iniciar a calibração.",
                  font=base_font, foreground="#64748b",
                  wraplength=800).pack(anchor="w", pady=(0, 15))
        
        # === SELECCION DE SENSOR (GRIGO DE BOTONES GRANDES) ===
        # Reemplazamos el combobox viejo por algo mas tactil
        
        # Remover texto del borde (frame) ya que es redundante con el texto de arriba
        select_frame = ttk.Labelframe(parent, text="", padding=20)
        select_frame.pack(fill=X, pady=(0, 25))
        
        # Container interior con borde para diferenciar visualmente la zona
        inner_container = ttk.Frame(select_frame, style='CardNoBorder.TFrame') 
        inner_container.pack(fill=X)
        inner_container.columnconfigure(1, weight=1)
        # Guardar referencia para poder refrescar los números de serie cuando cambien
        try:
            self._cal_select_inner = inner_container
        except Exception:
            pass
        
        sensor_names = list(current_config.get("nodes", {}).keys())
        if not sensor_names:
            sensor_names = ["celda_1"]
        selected_key = next(iter(sensor_names), "celda_1")
        self._cal_sensor_selected = tk.StringVar(value=selected_key)

        node_display_to_internal = {}
        node_display_values = []
        for internal in sensor_names:
            display = get_display_name(internal)
            node_display_to_internal[display] = internal
            node_display_values.append(display)

        def _get_default_load_channel(internal_name):
            try:
                cfg = current_config.get('nodes', {}).get(internal_name, {})
                ch = cfg.get('ch_load') or cfg.get('ch')
                if ch:
                    return ch
            except Exception:
                pass
            return 'ch1'

        node_display_default = get_display_name(selected_key)
        node_var = tk.StringVar(value=node_display_default)
        channel_var = tk.StringVar(value=_get_default_load_channel(selected_key))
        self._cal_channel_selected = channel_var

        ttk.Label(inner_container, text="Nó:", font=base_font_bold).grid(row=0, column=0, sticky='w', padx=(0, 12), pady=6)
        node_combo = ttk.Combobox(inner_container, values=node_display_values, textvariable=node_var, font=base_font, state='readonly')
        node_combo.grid(row=0, column=1, sticky='ew', ipady=self.scaled(3), pady=6)

        ttk.Label(inner_container, text="Canal de Carga:", font=base_font_bold).grid(row=1, column=0, sticky='w', padx=(0, 12), pady=6)
        channel_combo = ttk.Combobox(inner_container, values=['ch1', 'ch2', 'ch3'], textvariable=channel_var, font=base_font, state='readonly')
        channel_combo.grid(row=1, column=1, sticky='ew', ipady=self.scaled(3), pady=6)

        def _on_node_change(event=None):
            internal = node_display_to_internal.get(node_var.get(), selected_key)
            try:
                self._cal_sensor_selected.set(internal)
            except Exception:
                pass
            channel_var.set(_get_default_load_channel(internal))

        try:
            node_combo.bind("<<ComboboxSelected>>", _on_node_change)
        except Exception:
            pass

        action_frame = ttk.Frame(parent)
        action_frame.pack(fill=X, pady=self.scaled(8))

        def start_calibration_action():
            sensor_name = self._cal_sensor_selected.get() or "celda_1"
            channel_name = None
            try:
                channel_name = self._cal_channel_selected.get()
            except Exception:
                channel_name = None
            if config_dialog:
                try:
                    config_dialog.grab_release()
                except Exception:
                    pass
            # Abrir wizard directamente para la celda seleccionada
            try:
                self._open_calibration_wizard(current_config, sensor_name, config_dialog, channel_override=channel_name)
            except Exception as e:
                try:
                    self.show_alert("Erro", f"Não foi possível iniciar calibração: {e}", "error", parent=parent)
                except Exception:
                    pass

        # Botón grande y centrado
        try:
            btn_start = ttk.Button(action_frame, text="INICIAR CALIBRAÇÃO", command=start_calibration_action, bootstyle="success", width=28)
            btn_start.pack(pady=(6, 12))
        except Exception:
            try:
                btn_start = ttk.Button(action_frame, text="INICIAR CALIBRAÇÃO", command=start_calibration_action)
                btn_start.pack(pady=(6, 12))
            except Exception:
                pass

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
                            initialfile="curva_celda.csv"
                        )
                    else:
                        out_path = filedialog.asksaveasfilename(
                            title="Exportar curvas de calibración",
                            defaultextension=".csv",
                            filetypes=[("Archivos CSV", "*.csv")],
                            initialdir=calib_dir,
                            initialfile="curva_celda.csv"
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
                    dlg.deiconify()
                    dlg.lift()
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
                try:
                    widget.configure(style='Card.TFrame')
                except Exception:
                    pass
                if content_frame:
                    try:
                        content_frame.configure(background=BG_CARD)
                    except Exception:
                        pass
                    for sub in content_frame.winfo_children():
                        if isinstance(sub, ttk.Label):
                            try:
                                if hasattr(sub, 'tag') and sub.tag == 'name':
                                    sub.configure(foreground=COLOR_NORMAL_FG, font=("Segoe UI", self.scaled_font(26), 'bold'), background=BG_CARD)
                                elif hasattr(sub, 'tag') and sub.tag == 'serial':
                                    sub.configure(foreground=COLOR_NORMAL_SUB, font=("Segoe UI", self.scaled_font(14)), background=BG_CARD)
                                elif hasattr(sub, 'tag') and sub.tag == 'status':
                                    sub.configure(foreground=COLOR_NORMAL_FG, font=("Segoe UI", self.scaled_font(12)), background=BG_CARD)
                            except Exception:
                                pass
                if lbl_status:
                    try:
                        lbl_status.configure(text="Clicar para selecionar")
                    except Exception:
                        pass

    def _refresh_calibration_sensor_serials(self):
        """Refresca los labels de Nº Serie mostrados en la pestaña de calibración
        a partir de `self.data_processor.nodos_config`. Esto asegura que si el
        usuario cambia el serial en el diálogo de configuración, la vista de
        calibración lo muestre inmediatamente.
        """
        try:
            container = getattr(self, '_cal_select_inner', None)
            if container is None or not container.winfo_exists():
                return
            # Obtener mapping actual
            mapping = {}
            try:
                if hasattr(self, 'data_processor') and getattr(self.data_processor, 'nodos_config', None):
                    mapping = self.data_processor.nodos_config
            except Exception:
                mapping = {}

            for btn_frame in container.winfo_children():
                s_name = getattr(btn_frame, 'sensor_name', None)
                if not s_name:
                    continue
                # Buscar label con tag 'serial' dentro del content frame
                for child in btn_frame.winfo_children():
                    if isinstance(child, ttk.Frame):
                        for sub in child.winfo_children():
                            tag = getattr(sub, 'tag', None)
                            if tag == 'serial' and isinstance(sub, ttk.Label):
                                # Actualizar texto según mapping
                                try:
                                    serial_val = ''
                                    cfg = mapping.get(s_name, {}) if isinstance(mapping, dict) else {}
                                    serial_val = cfg.get('serial', '') if isinstance(cfg, dict) else ''
                                    if serial_val:
                                        sub.configure(text=f"Nº Serie: {serial_val}")
                                    else:
                                        sub.configure(text="")
                                except Exception:
                                    pass
                        break
        except Exception:
            pass
    
    def _open_calibration_wizard(self, current_config, sensor_name_override=None, config_dialog=None, channel_override=None):
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
        config_dialog_hidden = False

        # Si se pasa un override de sensor, forzar la selección interna para que
        # el wizard muestre el número de célula y nº de serie correctamente.
        try:
            if sensor_name_override:
                try:
                    self._cal_sensor_selected = tk.StringVar(value=sensor_name_override)
                except Exception:
                    self._cal_sensor_selected = sensor_name_override
        except Exception:
            pass

        # Obtener celda y serial para persistencia
        from modules.calibration import CalibrationManager
        celda_id = None
        serial = None
        internal_name = None
        # Preferir la selección forzada si existe
        try:
            if sensor_name_override:
                internal_name = sensor_name_override
            elif hasattr(self, '_cal_sensor_selected') and hasattr(self._cal_sensor_selected, 'get'):
                internal_name = self._cal_sensor_selected.get()
            elif hasattr(self, '_cal_sensor_selected') and isinstance(self._cal_sensor_selected, str):
                internal_name = self._cal_sensor_selected
        except Exception:
            internal_name = None

        if internal_name:
            try:
                if internal_name.startswith("celda_"):
                    celda_id = internal_name.split("_")[-1]
            except Exception:
                pass
            # Buscar serial en current_config o en data_processor.nodos_config
            try:
                if current_config and isinstance(current_config, dict):
                    nodos_cfg = current_config.get('nodes', {})
                    if internal_name in nodos_cfg:
                        serial = nodos_cfg[internal_name].get('serial', None)
            except Exception:
                pass
            try:
                if serial is None and hasattr(self.data_processor, 'nodos_config'):
                    nodos_cfg = self.data_processor.nodos_config
                    if internal_name in nodos_cfg:
                        serial = nodos_cfg[internal_name].get('serial', None)
            except Exception:
                pass

        # Canal seleccionado para calibración (por defecto carga del nodo)
        cal_channel = None
        try:
            if channel_override:
                cal_channel = channel_override
        except Exception:
            cal_channel = None
        if not cal_channel:
            try:
                if current_config and isinstance(current_config, dict) and internal_name:
                    cfg = current_config.get('nodes', {}).get(internal_name, {})
                    cal_channel = cfg.get('ch_load') or cfg.get('ch')
            except Exception:
                cal_channel = None
        if not cal_channel:
            cal_channel = 'ch1'


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

        # Crear ventana del wizard (con barra de título de Windows)
        wizard = ttk.Toplevel(self)
        try:
            wizard.withdraw()
        except Exception:
            pass
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
        wizard.title(f"Calibração - Nó {celda_num} (Carga {cal_channel})")
        try:
            self._apply_window_icon(wizard)
        except Exception:
            pass
        # Copiar posición y tamaño real de la ventana principal (winfo_* reflejan la geometría
        # actual en pantalla, a diferencia de geometry() que devuelve el estado restaurado)
        try:
            self.update_idletasks()
            wx = self.winfo_x()
            wy = self.winfo_y()
            ww = self.winfo_width()
            wh = self.winfo_height()
            wizard.geometry(f"{ww}x{wh}+{wx}+{wy}")
        except Exception:
            pass
        try:
            wizard.resizable(True, True)
        except Exception:
            pass
        try:
            wizard.attributes('-fullscreen', False)
        except Exception:
            pass
        # Mantener el wizard asociado a la ventana principal o diálogo de configuración
        try:
            if self._config_dialog_ref and self._config_dialog_ref.winfo_exists():
                wizard.transient(self._config_dialog_ref)
            else:
                wizard.transient(self)
        except Exception:
            pass
        try:
            wizard.update_idletasks()
            wizard.deiconify()
        except Exception:
            pass
        # Desactivar la ventana de configuración mientras el wizard esté activo
        config_dialog_disabled = False
        if self._config_dialog_ref:
            try:
                if self._config_dialog_ref.winfo_exists():
                    try:
                        self._config_dialog_ref.attributes('-disabled', True)
                        config_dialog_disabled = True
                    except Exception:
                        self._config_dialog_ref.withdraw()
                        config_dialog_hidden = True
            except Exception:
                pass
        # Evitar grab_set aquí para no bloquear la UI en escenarios de primer guardado
        try:
            wizard.lift()
            wizard.focus_force()
        except Exception:
            pass
        # Suprimir el watchdog de config mientras el wizard esté activo
        try:
            self._suppress_cfg_watch = True
        except Exception:
            pass
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
            try:
                # Limpiar bandera que suprime el watchdog
                self._suppress_cfg_watch = False
            except Exception:
                pass
            # Restaurar grab del diálogo de configuración
            if self._config_dialog_ref:
                try:
                    if self._config_dialog_ref.winfo_exists():
                        if config_dialog_hidden:
                            self._config_dialog_ref.deiconify()
                            self._config_dialog_ref.update_idletasks()
                        if config_dialog_disabled:
                            try:
                                self._config_dialog_ref.attributes('-disabled', False)
                            except Exception:
                                pass
                        try:
                            if self._config_dialog_ref.state() != 'zoomed':
                                self._config_dialog_ref.state('zoomed')
                        except Exception:
                            try:
                                self._config_dialog_ref.attributes('-zoomed', True)
                            except Exception:
                                pass
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
            selected_comp = None
            try:
                if current_config and isinstance(current_config, dict) and selected:
                    cfg = current_config.get('nodes', {}).get(selected, {})
                    nid = cfg.get('id')
                    if nid is not None:
                        selected_comp = f"{nid}:{cal_channel}"
            except Exception:
                selected_comp = None

            # Priorizar lectura RAW por sensor seleccionado
            try:
                raw = 0.0
                if selected_comp:
                    raw = float(self.data_processor.get_last_raw_for(selected_comp))
                elif selected:
                    raw = float(self.data_processor.get_last_raw_for(selected))
                else:
                    raw = float(self.data_processor.get_last_total_raw())
            except Exception:
                raw = float(self.data_processor.get_last_total_raw())

            if unit == "Bits (Raw)":
                return raw

            # Si la unidad es peso (kg), intentar leer el valor procesado del sensor
            if unit == "t":
                try:
                    proc = getattr(self, '_last_sensor_data', None)
                    if proc and 'sensores' in proc:
                        if selected_comp and selected_comp in proc['sensores']:
                            val = proc['sensores'][selected_comp].get('valor')
                            if val is not None:
                                return float(val) / 1000.0
                        if selected in proc['sensores']:
                            val = proc['sensores'][selected].get('valor')
                            if val is not None:
                                return float(val) / 1000.0
                except Exception:
                    pass
                # Fallback: intentar convertir la lectura CRUDA a peso
                try:
                    if selected_comp:
                        raw_f = float(self.data_processor.get_last_raw_for(selected_comp))
                    else:
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

                # Aplicar coeficientes del sistema
                try:
                    slope = float(getattr(self.data_processor, 'system_slope', 1.0))
                    offset = float(getattr(self.data_processor, 'system_offset', 0.0))
                    peso = (raw_applied * slope) + offset
                except Exception:
                    peso = raw_applied

                # El sistema ahora asume que las lecturas crudas y los coeficientes
                # están en kilogramos; por tanto `peso` ya está en kg.
                try:
                    return float(peso) / 1000.0
                except Exception:
                    return 0.0

            if unit == "kg":
                try:
                    proc = getattr(self, '_last_sensor_data', None)
                    if proc and 'sensores' in proc:
                        if selected_comp and selected_comp in proc['sensores']:
                            val = proc['sensores'][selected_comp].get('valor')
                            if val is not None:
                                return float(val)
                        if selected in proc['sensores']:
                            val = proc['sensores'][selected].get('valor')
                            if val is not None:
                                return float(val)
                except Exception:
                    pass
                try:
                    return float(raw)
                except Exception:
                    return 0.0

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

            # Requisito operativo: calibración lineal de 2 puntos para todo el rango.
            # Si el usuario ingresó más puntos, se toman los extremos por lectura.
            if len(points) > 2:
                try:
                    pts_sorted_for_line = sorted(points, key=lambda p: float(p[1]))
                    points = [pts_sorted_for_line[0], pts_sorted_for_line[-1]]
                    self.log_message("[CALIBRATION] Más de 2 puntos detectados: usando solo 2 extremos para recta global.")
                except Exception:
                    points = points[:2]

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
        # Usar el mismo texto que el título de la ventana
        label_titulo = f"Calibração de Carga — Nó {celda_num} ({cal_channel})"
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
        try:
            main.pack_propagate(False)
        except:
            pass
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
        
        # Weight (en kg)
        f_w = ttk.Frame(f_fields)
        f_w.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        ttk.Label(f_w, text="Peso Padrão (kgf):", font=("Segoe UI", 11)).pack(anchor="w")
        e_weight = ttk.Entry(f_w, textvariable=self._cal_input_weight, font=("Consolas", 16))
        e_weight.pack(fill=X, ipady=8)
        e_weight.bind("<Return>", on_weight_enter)
        e_weight.bind("<KP_Enter>", on_weight_enter)
        self._bind_numeric_keypad(e_weight, "Peso Padrão (kgf)")
        
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
        ttk.Label(h_frame, text="PESO (kgf)", font=("Segoe UI", 10, "bold"), 
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
                self._cal_ax.set_ylabel("Peso (kgf)", fontsize=10)
                self._cal_ax.grid(True, linestyle='--', alpha=0.5)
                # Diferir la creación del canvas de matplotlib al loop de eventos
                # para que la ventana aparezca rápido y el gráfico cargue después
                def _init_mpl_canvas():
                    if not self._cal_wizard_active:
                        return
                    try:
                        self._cal_canvas = FigureCanvasTkAgg(self._cal_fig, master=g_frame)
                        self._cal_canvas.get_tk_widget().pack(fill=BOTH, expand=YES)
                        self._update_cal_wizard_graph()
                    except Exception as ex:
                        self.log_message(f"Error matplotlib canvas: {ex}")
                wizard.after(80, _init_mpl_canvas)
            except Exception as e:
                self.log_message(f"Error matplotlib: {e}")
                ttk.Label(g_frame, text="Erro ao inicializar gráfico",
                          font=("Segoe UI", 12)).pack(expand=YES)
        else:
            ttk.Label(g_frame, text="Matplotlib não disponível\nInstale com: pip install matplotlib",
                      font=("Segoe UI", 12), justify="center").pack(expand=YES)

        ttk.Button(right, text="FINALIZAR E APLICAR CALIBRAÇÃO",
                   command=cmd_apply_cal,
                   bootstyle="success",
                   padding=(20, 15)).pack(fill=X, pady=(10, 0))

        # Diferir el primer refresco de tabla al loop de eventos para que
        # la ventana aparezca completa antes de poblar la tabla
        wizard.after(50, lambda: self._refresh_cal_wizard_table_ui() if self._cal_wizard_active else None)
        
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
            e_w.bind("<Button-1>", lambda e, ew=e_w: self.after(50, lambda: self._show_numeric_keypad(ew, "Peso (kg)")))

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
            f"Tem certeza que deseja eliminar o ponto?\n\nPeso: {peso:.2f} kgf\nLeitura: {lectura:.2f}"
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
            self._cal_ax.set_ylabel("Peso (kgf)", fontsize=10)
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
