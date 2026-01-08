import tkinter as tk
from tkinter import messagebox, filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import time
import random
import os
import sys
import json
from datetime import datetime

# Intentar importar matplotlib
try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import numpy as np
except ImportError:
    print("Error: Matplotlib o Numpy no instalados. Instale con: pip install matplotlib numpy")
    sys.exit(1)

# Intentar importar scipy para splines
try:
    from scipy.interpolate import interp1d, UnivariateSpline, CubicSpline
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: Scipy no instalado. Métodos avanzados limitados.")

from dataclasses import dataclass, field

# --- MOCKS Y CLASES SIMULADAS ---

@dataclass
class CalibrationPoint:
    """Punto de calibración individual (Copia simplificada)."""
    peso_aplicado_kg: float
    valor_crudo_mv_v: float
    valor_sensor_kg: float
    timestamp: str

class MockCalibrationManager:
    """Simulación simple del manager de calibración."""
    def __init__(self):
        self.points = []
    
    def add_point(self, point):
        self.points.append(point)
    
    def remove_point(self, index):
        if 0 <= index < len(self.points):
            self.points.pop(index)

# --- APLICACIÓN PRINCIPAL DE PRUEBA ---

class TestCalibrationApp(ttk.Window):
    def __init__(self):
        super().__init__(themename="litera") # Usar un tema similar
        self.title("Simulador de Calibración - Balanza Py")
        self.geometry("1024x768")
        
        # Estado simulado del sensor - AHORA 200 TONELADAS
        self.simulated_weight = 0.0 # kg
        self.sensor_noise_level = 0.00005 # mV/V noise
        self.sensor_sensitivity = 2.0 # mV/V a fondo de escala
        self.sensor_capacity = 200000.0 # kg (200 ton)
        
        self._configure_styles()
        self._setup_main_ui()

    def _configure_styles(self):
        # Configurar estilos copiados de gui.py para los diálogos
        FONT_MAIN = "Segoe UI"
        
        # Large Dialog Buttons
        self.style.configure('Large.success.TButton', font=(FONT_MAIN, 16, 'bold'))
        self.style.configure('Large.danger.TButton', font=(FONT_MAIN, 16, 'bold'))
        
    def _setup_main_ui(self):
        """Interfaz principal de control de simulación."""
        container = ttk.Frame(self, padding=20)
        container.pack(fill=BOTH, expand=YES)
        
        # Header
        ttk.Label(container, text="SIMULADOR DE HARDWARE", font=("Segoe UI", 24, "bold"), bootstyle="primary").pack(pady=20)
        
        # Control de simulación
        sim_frame = ttk.Labelframe(container, text="Control del Sensor Simulado", padding=20)
        sim_frame.pack(fill=X, pady=20)
        
        ttk.Label(sim_frame, text="Use este control para simular que pone peso físico sobre la balanza.", 
                 font=("Segoe UI", 12)).pack(anchor=W, pady=(0,20))
        
        # Slider de peso
        self.weight_var = tk.DoubleVar(value=0.0)
        
        lbl_frame = ttk.Frame(sim_frame)
        lbl_frame.pack(fill=X)
        ttk.Label(lbl_frame, text="Peso Aplicado (kg):", font=("Segoe UI", 14, "bold")).pack(side=LEFT)
        # Ancho fijo para evitar redimensionamiento
        self.lbl_weight = ttk.Label(lbl_frame, text="0 kg", font=("Consolas", 18, "bold"), bootstyle="success", width=15, anchor="e")
        self.lbl_weight.pack(side=RIGHT)
        
        scale = ttk.Scale(sim_frame, from_=0, to=self.sensor_capacity, variable=self.weight_var, 
                         orient=HORIZONTAL, command=self._update_simulated_weight)
        scale.pack(fill=X, pady=10)
        
        # Botones de pesos predefinidos (Actualizados a rango 200 ton)
        btn_frame = ttk.Frame(sim_frame)
        btn_frame.pack(fill=X, pady=10)
        
        ttk.Button(btn_frame, text="0 ton", command=lambda: self.set_weight(0)).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="15 ton", command=lambda: self.set_weight(15000)).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="60 ton", command=lambda: self.set_weight(60000)).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="120 ton", command=lambda: self.set_weight(120000)).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="200 ton", command=lambda: self.set_weight(200000)).pack(side=LEFT, padx=5)
        
        ttk.Separator(container).pack(fill=X, pady=20)
        
        # Área de lanzamiento de la interfaz a probar
        test_frame = ttk.Labelframe(container, text="Interfaz a Probar", padding=20, bootstyle="info")
        test_frame.pack(fill=BOTH, expand=YES)
        
        ttk.Label(test_frame, text="Configuración simulada:", font=("Segoe UI", 12)).pack(anchor=W)
        ttk.Label(test_frame, text=f"- Sensor: Celda 1 (ID: 12345)\n- Capacidad: {self.sensor_capacity/1000:.0f} ton\n- Sensibilidad: {self.sensor_sensitivity} mV/V (No Lineal > 80%)", 
                 font=("Consolas", 10), foreground="gray").pack(anchor=W, pady=5)
        
        ttk.Button(test_frame, text="ABRIR WIZARD DE CALIBRAÇÃO", bootstyle="warning", 
                  command=self.open_calibration_wizard, padding=(30, 20)).pack(pady=30)
        
    def set_weight(self, value):
        self.weight_var.set(value)
        self._update_simulated_weight(value)
        
    def _update_simulated_weight(self, value):
        w = float(value)
        self.simulated_weight = w
        self.lbl_weight.configure(text=f"{w:,.0f} kg")
    
    def _calculate_simulated_mv(self, weight_kg):
        """
        Calcula el valor mV/V simulado para un peso dado, con comportamiento no-lineal.
        - Inicio (0-30t): 'Panza abajo' (respuesta lenta inicial).
        - Medio (30t-180t): Lineal.
        - Final (>180t): Saturación/Aplanamiento.
        """
        capacity = self.sensor_capacity
        sensitivity = self.sensor_sensitivity
        
        # 1. Base ideal lineal
        mv = (weight_kg / capacity) * sensitivity
        
        # 2. Aplicar deformaciones
        if weight_kg < 30000:
            # Panza abajo: El sensor entrega menos voltaje del ideal al inicio
            # Factor progresivo de 0.90 a 1.00
            ratio_low = weight_kg / 30000.0
            factor = 0.90 + (0.10 * (ratio_low**0.5)) # Curva suave
            mv = mv * factor
            
        elif weight_kg > 180000:
            # Saturación: El sensor entrega menos voltaje del ideal al final
            excess = weight_kg - 180000
            # Perdida exponencial
            loss_factor = 1.0 - (excess / 50000.0) * 0.2 # Pierde hasta 20% sensibilidad extra
            if loss_factor < 0.1: loss_factor = 0.1
            
            # Recalcular parte excedente con perdida
            base_180 = (180000 / capacity) * sensitivity
            excess_mv = (excess / capacity) * sensitivity * loss_factor
            mv = base_180 + excess_mv
            
        else:
            # Zona lineal centro - Ajuste para conectar suavemente con zona baja
            # La zona baja termina en factor 1.0, asi que conecta bien.
            pass
            
        return mv

    # =========================================================================================
    # DIÁLOGOS PERSONALIZADOS (Manteniendo estética de gui.py)
    # =========================================================================================

    def show_large_confirmation(self, title, message):
        """Mostra um dilogo modal personalizado SEM barra de ttulo, com fontes e botes grandes."""
        result = {'value': False}
        
        # Criar janela secundria SIN BARRA DE TTULO
        dialog = ttk.Toplevel(self)
        dialog.overrideredirect(True)  # Quitar barra de Windows
        dialog.geometry("600x360")
        
        # Centralizar em relao  janela principal
        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 300
            y = self.winfo_y() + (self.winfo_height() // 2) - 180
            dialog.geometry(f"+{x}+{y}")
        except:
            pass
        
        # Forzar que aparezca arriba
        dialog.lift()
        dialog.focus_force()
            
        # Container con borde para definir el dilogo
        outer_frame = ttk.Frame(dialog, bootstyle="secondary", padding=3)
        outer_frame.pack(fill=BOTH, expand=YES)
        
        frame = ttk.Frame(outer_frame, padding=30)
        frame.pack(fill=BOTH, expand=YES)
        
        # Ttulo personalizado
        title_lbl = ttk.Label(frame, text=title.upper(), font=("Segoe UI", 16, "bold"), foreground="#1e293b")
        title_lbl.pack(pady=(0, 20))
        
        # Mensagem grande
        lbl = ttk.Label(frame, text=message, font=("Segoe UI", 20), wraplength=480, justify="center")
        lbl.pack(pady=(10, 40), expand=YES)
        
        # Botes grandes
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X, pady=10)
        
        # Funcin de cierre seguro
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
            icon = "⛔"
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
            pass
        target.wait_window(dialog)
    
    # =========================================================================================
    # LÓGICA COPIADA Y ADAPTADA DE LA INTERFAZ ORIGINAL (modules/gui.py)
    # =========================================================================================
    
    def open_calibration_wizard(self):
        """Abre o wizard de calibração simulado."""
        sensor_name = "SIMULATED_SENSOR"
        sensor_id = 12345
        
        # Crear ventana del wizard
        wizard = ttk.Toplevel(self)
        wizard.overrideredirect(True) # Frameless como la original
        
        # Tamaño casi pantalla completa (simulando tablet)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        # Hacemos un poco mas chico para que se vvea que es una ventana sobre la app de prueba
        wizard_w = int(screen_w * 0.9)
        wizard_h = int(screen_h * 0.9)
        x = int(screen_w * 0.05)
        y = int(screen_h * 0.05)
        wizard.geometry(f"{wizard_w}x{wizard_h}+{x}+{y}")
        
        wizard.lift()
        wizard.focus_force()
        
        self._cal_wizard = wizard
        
        # Generar datos simulados iniciales (Curva compleja)
        self._cal_points = []
        
        # Puntos: mas densos al principio y al final para ver la curva
        points_kg = list(range(0, 40000, 5000)) + \
                    list(range(40000, 180000, 20000)) + \
                    list(range(180000, 210000, 5000))
        
        for kg in points_kg:
            kg = float(kg)
            if kg > self.sensor_capacity * 1.05: break
                
            mv_simulated = self._calculate_simulated_mv(kg)
            
            # Agregar algo de aleatoriedad minima
            mv_simulated += (random.random() - 0.5) * 0.0002
            
            if mv_simulated < 0: mv_simulated = 0.0
            
            self._cal_points.append((kg, mv_simulated))

        self._cal_manager = MockCalibrationManager()
        # Cargar puntos simulados en manager
        for kg, mv in self._cal_points:
            p = CalibrationPoint(kg, mv, kg, datetime.now().strftime("%Y-%m-%d"))
            self._cal_manager.add_point(p)

        self._cal_current_mv_value = 0.0
        self._cal_wizard_active = True
        
        # Estado del punto de prueba
        self.test_point_mv = None  # Para almacenar el valor X de prueba
        
        # Funcin de cierre seguro
        def on_close():
            self._cal_wizard_active = False
            try:
                wizard.destroy()
            except:
                pass
            self._cal_wizard = None
        
        # Borde (estilo warning original)
        border_frame = ttk.Frame(wizard, bootstyle="warning", padding=4)
        border_frame.pack(fill=BOTH, expand=YES)
        
        main_frame = ttk.Frame(border_frame, padding=15)
        main_frame.pack(fill=BOTH, expand=YES)
        
        # === HEADER ===
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill=X, pady=(0, 10))
        
        ttk.Label(title_frame, text=f" CALIBRAÇÃO: {sensor_name}", 
                 font=("Segoe UI", 24, "bold")).pack(side=LEFT)
        
        ttk.Button(title_frame, text=" FECHAR", bootstyle="danger",
                  command=on_close, padding=(20, 10)).pack(side=RIGHT)
        
        # === CONTENEDOR PRINCIPAL ===
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=BOTH, expand=YES)
        # Configurar grid para aprovechar mejor el espacio:
        # Columna 0 (Izquierda: Controles y tabla): weight=4
        # Columna 1 (Derecha: Gráfico): weight=6
        content_frame.columnconfigure(0, weight=4)
        content_frame.columnconfigure(1, weight=6)
        content_frame.rowconfigure(0, weight=1)
        
        # === COLUMNA IZQUIERDA ===
        left_frame = ttk.Frame(content_frame)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        # Leitura Atual - Compacto arriba
        reading_frame = ttk.Labelframe(left_frame, text=" Leitura Atual", padding=10)
        reading_frame.pack(fill=X, pady=(0, 10))
        
        reading_container = ttk.Frame(reading_frame)
        reading_container.pack(fill=X)
        # Ancho fijo para evitar jitter
        self._cal_current_mv = ttk.Label(reading_container, text="0.0000 mV/V", 
                                        font=("Consolas", 32, "bold"), foreground="#2563eb", width=13) 
        self._cal_current_mv.pack(side=LEFT)
        self._cal_current_kg = ttk.Label(reading_container, text="(0.000 ton)", 
                                        font=("Segoe UI", 16), foreground="#64748b", width=15)
        self._cal_current_kg.pack(side=LEFT, padx=(15, 0))
        
        # Adicionar Ponto - Compacto
        action_frame = ttk.Labelframe(left_frame, text=" Nova Medição", padding=10)
        action_frame.pack(fill=X, pady=(0, 10))
        
        input_row = ttk.Frame(action_frame)
        input_row.pack(fill=X)
        
        ttk.Label(input_row, text="Peso (kg):", font=("Segoe UI", 14)).pack(side=LEFT)
        self._cal_peso_entry = ttk.Entry(input_row, font=("Segoe UI", 16), width=10)
        self._cal_peso_entry.pack(side=LEFT, padx=10, ipady=5)
        
        ttk.Button(input_row, text=" CAPTURAR ", bootstyle="success",
                  command=self._capture_cal_point,
                  padding=(15, 10)).pack(side=LEFT, padx=5, expand=YES, fill=X)
        
        # Tabla escrolleable - Ocupa TODO el espacio restante vertical
        table_frame = ttk.Labelframe(left_frame, text=" Pontos Capturados", padding=10)
        table_frame.pack(fill=BOTH, expand=YES, pady=(0, 10))
        
        # Header de la tabla fijo
        header_frame = ttk.Frame(table_frame, bootstyle="secondary", padding=5)
        header_frame.pack(fill=X)
        header_frame.columnconfigure(0, weight=2)
        header_frame.columnconfigure(1, weight=2)
        header_frame.columnconfigure(2, weight=1)
        
        ttk.Label(header_frame, text="Peso (kg)", font=('Segoe UI', 11, 'bold'), anchor="c").grid(row=0, column=0, sticky="ew")
        ttk.Label(header_frame, text="Leitura", font=('Segoe UI', 11, 'bold'), anchor="c").grid(row=0, column=1, sticky="ew")
        ttk.Label(header_frame, text="Ação", font=('Segoe UI', 11, 'bold'), anchor="c").grid(row=0, column=2, sticky="ew")
        
        ttk.Separator(table_frame).pack(fill=X)
        
        # Container scrolleable
        from ttkbootstrap.scrolled import ScrolledFrame
        self._cal_table_scroll = ScrolledFrame(table_frame, autohide=False) # autohide False para ver siempre scrollbar
        self._cal_table_scroll.pack(fill=BOTH, expand=YES, pady=5)
        
        # Botones export al final
        export_frame = ttk.Frame(left_frame)
        export_frame.pack(fill=X)
        ttk.Button(export_frame, text="EXPORTAR CSV", bootstyle="secondary-outline", padding=(10, 10)).pack(side=LEFT, padx=5, expand=YES, fill=X)
        ttk.Button(export_frame, text="SALVAR", bootstyle="success", padding=(10, 10)).pack(side=LEFT, padx=5, expand=YES, fill=X)

        # === COLUMNA DERECHA: Grafico ===
        right_frame = ttk.Labelframe(content_frame, text=" Análise da Curva", padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        
        # --- NUEVO: Selector de Metodo ---
        method_frame = ttk.Frame(right_frame)
        method_frame.pack(fill=X, pady=(0, 10))
        
        ttk.Label(method_frame, text="Método de Ajuste:", font=("Segoe UI", 12)).pack(side=LEFT, padx=5)
        
        self.calc_method_var = tk.StringVar(value="Polinomio Grado 2")
        methods = ["Lineal (y=mx+b)", "Polinomio Grado 2", "Polinomio Grado 3", "Interpolacion Lineal (Segmentos)"]
        if SCIPY_AVAILABLE:
            methods.append("Spline Cubico (Scipy)")
            
        cb_method = ttk.Combobox(method_frame, textvariable=self.calc_method_var, values=methods, state="readonly", width=30)
        cb_method.pack(side=LEFT, padx=5)
        cb_method.bind("<<ComboboxSelected>>", lambda e: self._update_cal_graph())
        
        # --- TEST POINT UI ---
        test_frame = ttk.Labelframe(right_frame, text="Probar Calibración", padding=10)
        test_frame.pack(fill=X, pady=(0, 10))
        
        f_test = ttk.Frame(test_frame)
        f_test.pack(fill=X)
        
        ttk.Label(f_test, text="Entrada (mV/V):").pack(side=LEFT)
        self.entry_test_mv = ttk.Entry(f_test, width=10)
        self.entry_test_mv.pack(side=LEFT, padx=5)
        
        ttk.Button(f_test, text="Calcular Kg", bootstyle="info-outline", 
                   command=self._set_test_point).pack(side=LEFT, padx=5)
                   
        self.lbl_test_result = ttk.Label(f_test, text="-> ??? kg", font=("Consolas", 12, "bold"))
        self.lbl_test_result.pack(side=LEFT, padx=10)
        # ---------------------
        
        # Gráfico maximizado
        fig = Figure(figsize=(5, 4), dpi=90, facecolor='#ffffff')
        self._cal_ax = fig.add_subplot(111)
        self._cal_ax.set_facecolor('#ffffff')
        # Márgenes ajustados
        fig.subplots_adjust(left=0.12, right=0.95, top=0.92, bottom=0.12)
        
        self._cal_canvas = FigureCanvasTkAgg(fig, master=right_frame)
        self._cal_canvas.draw()
        self._cal_canvas.get_tk_widget().pack(fill=BOTH, expand=YES)
        
        # --- Eventos para arrastrar puntos ---
        self._drag_index = None
        self._cal_canvas.mpl_connect('button_press_event', self._on_plot_click)
        self._cal_canvas.mpl_connect('button_release_event', self._on_plot_release)
        self._cal_canvas.mpl_connect('motion_notify_event', self._on_plot_drag)
        # -------------------------------------
        
        # Grid propagate false para evitar que el texto largo cambie el tamao
        frame_results = ttk.Frame(right_frame)
        frame_results.pack(fill=X, pady=(5,0))
        frame_results.pack_propagate(False)
        frame_results.configure(height=30)
        
        self._cal_results_label = ttk.Label(frame_results, text="Adicione pelo menos 2 pontos...", 
                                          font=("Segoe UI", 11), foreground="#64748b", anchor="center")
        self._cal_results_label.pack(fill=BOTH, expand=YES)

        # Iniciar loop de lectura simulada
        self._update_cal_reading_loop(wizard)
        
        # Mostrar datos precargados
        self._refresh_cal_table()
        self._update_cal_graph()

    def _update_cal_reading_loop(self, wizard):
        """Genera datos simulados y actualiza la UI."""
        if not self._cal_wizard_active:
            return
            
        try:
            if wizard.winfo_exists():
                # 1. Obtener peso simulado (de la app principal)
                actual_weight_kg = self.simulated_weight
                
                # 2. Calcular mV/V usando la curva compleja
                mv_simulated = self._calculate_simulated_mv(actual_weight_kg)
                
                # 3. Añadir ruido
                noise = (random.random() - 0.5) * 2 * self.sensor_noise_level
                mv_final = mv_simulated + noise
                if mv_final < 0: mv_final = 0.0
                
                self._cal_current_mv_value = mv_final
                
                # 4. Actualizar UI
                self._cal_current_mv.configure(text=f"{mv_final:.4f} mV/V")
                
                # conversión visual a ton
                ton = actual_weight_kg / 1000.0
                self._cal_current_kg.configure(text=f"({ton:.3f} ton)")
                
                # Loop
                wizard.after(100, lambda: self._update_cal_reading_loop(wizard))
        except Exception as e:
            print(f"Error en loop: {e}")

    def _capture_cal_point(self):
        """Captura el punto actual (copiado de original)."""
        try:
            peso_str = self._cal_peso_entry.get().strip().replace(",", "").replace(".", "")
            if not peso_str:
                messagebox.showerror("Erro", "Digite o peso real aplicado")
                return
            
            peso_kg = float(peso_str)
            mv_v = self._cal_current_mv_value
            
            # Guardar punto
            self._cal_points.append((peso_kg, mv_v))
            
            # Mock Manager
            point = CalibrationPoint(peso_kg, mv_v, peso_kg, datetime.now().strftime("%Y-%m-%d"))
            self._cal_manager.add_point(point)
            
            # Limpiar entry 
            self._cal_peso_entry.delete(0, END)
            
            # Actualizar tabla visual completa
            self._refresh_cal_table()
            
            # Actualizar grafica
            self._update_cal_graph()
            
        except ValueError:
            self.show_alert("Erro", "Peso inválido. Use apenas números.", "error")

    def _refresh_cal_table(self):
        """Reconstruye la tabla visual item por item (Editable)."""
        # Limpiar tabla actual
        for widget in self._cal_table_scroll.winfo_children():
            widget.destroy()
            
        # Reconstruir filas
        for i, (peso, mv) in enumerate(self._cal_points):
            row_frame = ttk.Frame(self._cal_table_scroll, padding=(5, 5))
            row_frame.pack(fill=X, pady=2)
            
            row_frame.columnconfigure(0, weight=2)
            row_frame.columnconfigure(1, weight=2)
            row_frame.columnconfigure(2, weight=1)
            
            # Entry Peso (Kg) - Editable
            v_weight = tk.StringVar(value=f"{peso:.2f}")
            e_weight = ttk.Entry(row_frame, textvariable=v_weight, font=('Consolas', 11), justify="center")
            e_weight.grid(row=0, column=0, sticky="ew", padx=2)
            # Bind events to update model
            e_weight.bind("<FocusOut>", lambda e, idx=i, var=v_weight: self._update_point_from_entry(idx, 'weight', var))
            e_weight.bind("<Return>", lambda e, idx=i, var=v_weight: [self._update_point_from_entry(idx, 'weight', var), row_frame.focus_set()]) # Remove focus on enter

            # Entry mV/V - Editable
            v_mv = tk.StringVar(value=f"{mv:.6f}")
            e_mv = ttk.Entry(row_frame, textvariable=v_mv, font=('Consolas', 11), justify="center")
            e_mv.grid(row=0, column=1, sticky="ew", padx=2)
            e_mv.bind("<FocusOut>", lambda e, idx=i, var=v_mv: self._update_point_from_entry(idx, 'mv', var))
            e_mv.bind("<Return>", lambda e, idx=i, var=v_mv: [self._update_point_from_entry(idx, 'mv', var), row_frame.focus_set()])
            
            # Botón ROJO de borrar
            btn_delete = ttk.Button(
                row_frame, 
                text="X", 
                bootstyle="danger-outline", 
                width=4,
                command=lambda idx=i: self._confirm_and_delete(idx)
            )
            btn_delete.grid(row=0, column=2, padx=5)
            
            ttk.Separator(self._cal_table_scroll).pack(fill=X, pady=0)

    def _update_point_from_entry(self, index, field_type, string_var):
        """Actualiza el modelo cuando se edita una celda."""
        if not (0 <= index < len(self._cal_points)):
            return

        try:
            val_str = string_var.get().replace(",", "")
            val = float(val_str)
            
            p_kg, p_mv = self._cal_points[index]
            
            if field_type == 'weight':
                self._cal_points[index] = (val, p_mv)
            elif field_type == 'mv':
                self._cal_points[index] = (p_kg, val)
            
            # Refrescar grafico
            self._update_cal_graph()
            
        except ValueError:
            pass # Ignorar valores invalidos

    def _confirm_and_delete(self, index):
        """Muestra dialogo de confirmación y elimina."""
        # Validar indice
        if not (0 <= index < len(self._cal_points)):
            return

        peso = self._cal_points[index][0]
        peso_ton = peso / 1000.0
        
        # Diálogo grande personalizado
        if self.show_large_confirmation("Remover Ponto", f"Deseja excluir a medição de {peso_ton:.2f} ton?"):
            try:
                self._cal_points.pop(index)
                self._cal_manager.remove_point(index)
                
                self._refresh_cal_table()
                self._update_cal_graph()
            except Exception as e:
                print(f"Error borrando: {e}")

    def _remove_cal_point(self):
        """Legacy - por si se llama internamente, aunque el boton fue removido."""
        pass

    def _update_cal_graph(self):
        """Dibuja la gráfica simulando diferentes metodos."""
        try:
            self._cal_ax.clear()
            
            # INVERTIDOS EJES: X=mV/V, Y=Kg
            self._cal_ax.set_xlabel('Lectura Sensor (mV/V)', fontsize=12, fontweight='bold')
            self._cal_ax.set_ylabel('Peso Calculado (kg)', fontsize=12, fontweight='bold')
            
            method = self.calc_method_var.get()
            self._cal_ax.set_title(f'Calibración: {method}', fontsize=14, fontweight='bold', color='#1e293b')
            self._cal_ax.grid(True, linestyle='--', alpha=0.7)
            self._cal_ax.set_facecolor('#ffffff')
            
            if not self._cal_points:
                self._cal_canvas.draw()
                return

            # Ordenar por mV/V (Eje X) para graficar correctamente
            sorted_points = sorted(self._cal_points, key=lambda p: p[1])
            x_data = np.array([p[1] for p in sorted_points]) # mV/V
            y_data = np.array([p[0] for p in sorted_points]) # Kg
            
            # Scatter plots (Puntos Reales)
            self._cal_ax.scatter(x_data, y_data, s=100, c='#2563eb', marker='o', 
                               zorder=5, edgecolors='white', linewidth=2, label="Mediciones")
            
            if len(x_data) >= 2:
                # Generar linea suave para visualizacion
                x_smooth = np.linspace(min(x_data), max(x_data), 200)
                y_smooth = None
                label_txt = ""
                
                # Modelos calculados para usarlos en el punto de test
                model_func = None # Funcion lambda x: y
                
                # Check for "Lineal (y=mx+b)" ONLY
                if method == "Lineal (y=mx+b)":
                    # y = mx + b
                    z = np.polyfit(x_data, y_data, 1)
                    p = np.poly1d(z)
                    y_smooth = p(x_smooth)
                    label_txt = f"y={z[0]:.2f}x + {z[1]:.2f}"
                    
                    model_func = p
                    # Stats
                    y_pred = p(x_data)
                    
                elif "Polinomio Grado 2" in method:
                    if len(x_data) >= 3:
                        z = np.polyfit(x_data, y_data, 2)
                        p = np.poly1d(z)
                        y_smooth = p(x_smooth)
                        label_txt = "Poly Order 2"
                        model_func = p
                    else:
                        label_txt = "Necesita 3+ ptos"

                elif "Polinomio Grado 3" in method:
                    if len(x_data) >= 4:
                        z = np.polyfit(x_data, y_data, 3)
                        p = np.poly1d(z)
                        y_smooth = p(x_smooth)
                        label_txt = "Poly Order 3"
                        model_func = p
                    else:
                        label_txt = "Necesita 4+ ptos"

                elif "Interpolacion Lineal" in method:
                    # Unir puntos directamente con lineas rectas (Segmentos)
                    # NO usamos suavizado, graficamos directmente punto a punto
                    self._cal_ax.plot(x_data, y_data, "r-", linewidth=2, label="Segmentos")
                    y_smooth = None
                    
                    # Para el modelo usamos np.interp
                    model_func = lambda x: np.interp(x, x_data, y_data)
                    
                elif "Spline" in method and SCIPY_AVAILABLE:
                    try:
                        # Spline Cubico (CubicSpline si es posible, sino UnivariateSpline con s=0)
                        # UnivariateSpline con s=0 fuerza interpolacion por todos los puntos
                        if 'CubicSpline' in globals():
                             cs = CubicSpline(x_data, y_data)
                             y_smooth = cs(x_smooth)
                             label_txt = "CubicSpline (Exacto)"
                             model_func = cs
                        elif len(x_data) > 3:
                            spl = UnivariateSpline(x_data, y_data, s=0) # s=0 -> No smoothing, force points
                            y_smooth = spl(x_smooth)
                            label_txt = "UnivariateSpline (s=0)"
                            model_func = spl
                        else:
                             # Fallback interp1d if few points
                            f = interp1d(x_data, y_data, kind='cubic')
                            y_smooth = f(x_smooth)
                            label_txt = "Spline (Interp1d Cubic)"
                            model_func = f
                    except Exception as e:
                        print(f"Spline error: {e}")
                
                # Plot Curve if calculated
                if y_smooth is not None:
                     self._cal_ax.plot(x_smooth, y_smooth, "r-", linewidth=2, label=label_txt)

                self._cal_ax.legend()
                
                # --- Test Point Plotting ---
                if self.test_point_mv is not None and model_func is not None:
                    try:
                        # Calcular kg usando el modelo actual
                        y_test = float(model_func(self.test_point_mv))
                        
                        # Graficar punto rojo
                        self._cal_ax.plot(self.test_point_mv, y_test, 'ro', markersize=10, markeredgecolor='black', label='Test')
                        
                        # Etiqueta en el grafico
                        self._cal_ax.annotate(f"{y_test:.1f} kg", 
                                             xy=(self.test_point_mv, y_test), 
                                             xytext=(10, -10), textcoords='offset points',
                                             bbox=dict(boxstyle="round,pad=0.3", fc="yellow", alpha=0.9))
                                             
                        # Actualizar etiqueta UI
                        self.lbl_test_result.configure(text=f"-> {y_test:.2f} kg")
                        
                    except Exception as e:
                         print(f"Error test point: {e}")
                
                # --- Update Results Label ---
                
                # --- Update Results Label ---
                # Calcular error medio (RMSE) para evaluar el ajuste
                if "Interpolacion" not in method:
                     # Para metodos no exactos (Lineal, Poly)
                     if len(x_data) >= 2:
                         if "Lineal (" in method or "Polinomio" in method:
                             y_pred_stats = np.polyval(z, x_data)
                             mse = np.mean((y_data - y_pred_stats)**2)
                             rmse = np.sqrt(mse)
                             self._cal_results_label.configure(text=f"{label_txt} | RMSE: {rmse:.4f} kg")
                         else:
                             self._cal_results_label.configure(text=f"Metodo: {method}")
                else:
                    self._cal_results_label.configure(text="Ajuste Exacto (Interpolacion)")
                # -------------------------
            
            # Límites dinámicos
            if len(y_data) > 0:
                y_min, y_max = min(y_data), max(y_data)
                margin = (y_max - y_min) * 0.1 if y_max != y_min else 1.0
                self._cal_ax.set_ylim(y_min - margin, y_max + margin)
                
                x_min, x_max = min(x_data), max(x_data)
                x_margin = (x_max - x_min) * 0.1 if x_max != x_min else 0.001
                self._cal_ax.set_xlim(x_min - x_margin, x_max + x_margin)

            self._cal_canvas.draw()
            
        except Exception as e:
            print(f"Error grafica: {e}")
            import traceback
            traceback.print_exc()

    # =========================================================================================
    # --- NUEVO: EVENTOS PARA ARRASTRAR PUNTOS EN LA GRAFICA ---
    # =========================================================================================
    
    def _on_plot_click(self, event):
        """Detecta click sobre un punto."""
        if event.inaxes != self._cal_ax: return
        if event.button != 1: return # Solo click izquierdo
        
        # Buscar punto cercano
        ind = self._get_point_index_under_mouse(event)
        if ind is not None:
            self._drag_index = ind
            
    def _on_plot_release(self, event):
        """Finaliza el arrastre."""
        if self._drag_index is not None:
            self._drag_index = None
            # Refrescar tabla para mostrar valores finales
            self._refresh_cal_table()

    def _on_plot_drag(self, event):
        """Mueve el punto seleccionado."""
        if self._drag_index is None: return
        if event.inaxes != self._cal_ax: return
        
        # Obtener nuevas coordenadas
        new_mv = event.xdata
        new_kg = event.ydata
        
        # Validaciones basicas
        if new_mv < 0: new_mv = 0
        # if new_kg < 0: new_kg = 0 # Permitir negativo? Balanzas a veces marcan neg.
        
        # Actualizar dato
        # _cal_points formato: (kg, mv)
        self._cal_points[self._drag_index] = (new_kg, new_mv)
        
        # Redibujar rapido (sin refrescar tabla aun para performance)
        self._update_cal_graph()

    def _get_point_index_under_mouse(self, event):
        """Encuentra el índice del punto bajo el mouse (tolerancia en pixeles)."""
        if not self._cal_points: return None
        
        # Coordenadas Plot: (mv, kg)  <-- OJO: Graph X=mv, Y=kg
        # Coordenadas Data: (kg, mv)
        plot_points = [(p[1], p[0]) for p in self._cal_points]
        
        # Transformar puntos del grafico a pixeles
        # event.x, event.y están en pixeles de pantalla
        
        # Matplotlib transform: Data -> Display
        tpoints = self._cal_ax.transData.transform(plot_points)
        
        # Calcular distancias en pixeles
        mx, my = event.x, event.y
        dists = np.sqrt(np.sum((tpoints - [mx, my])**2, axis=1))
        
        # Indice del mas cercano
        ind = np.argmin(dists)
        
        if dists[ind] < 15: # 15 pixeles tolerancia
            return ind
        return None

    def _set_test_point(self):
        """Lee el valor del entry de test y actualiza el grafico."""
        try:
            val = float(self.entry_test_mv.get())
            self.test_point_mv = val
            self._update_cal_graph()
        except ValueError:
            messagebox.showerror("Error", "Ingrese un valor numerico valido para mV/V")

    def _highlight_test_point(self, mv_input, kg_estimated):
        """Resalta el punto de prueba en la gráfica."""
        try:
            self._cal_ax.scatter([mv_input], [kg_estimated], s=150, c='red', marker='x', label="Punto de Prueba", zorder=10)
            self._cal_canvas.draw()
        except Exception as e:
            print(f"Error resaltando punto de prueba: {e}")


if __name__ == "__main__":
    app = TestCalibrationApp()
    app.mainloop()
