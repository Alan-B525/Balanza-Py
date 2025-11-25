import threading
import tkinter as tk
from tkinter import filedialog, BOTH, YES, NO, X, Y, LEFT, RIGHT, END, HORIZONTAL, BOTTOM
from PIL import Image, ImageTk

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.dialogs import Messagebox

from config import APP_TITLE, APP_SIZE, THEME_NAME

class BalanzaGUI(ttk.Window):
    def __init__(self, sensor_manager, data_processor, logger):
        super().__init__(themename=THEME_NAME)
        self.title(APP_TITLE)
        self.geometry(APP_SIZE)
        
        self.sensor_manager = sensor_manager
        self.data_processor = data_processor
        self.logger = logger
        
        self.connected = False
        
        # Handle window close event (OS X button)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        
        self._configure_styles()
        self._setup_ui()
        
        # Start update loop
        self.after(100, self._update_loop)

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
        self.style.configure('Reset.TButton', font=(FONT_MAIN, 12))
        
        # Header
        self.style.configure('Header.TFrame', background=BG_CARD)
        self.style.configure('HeaderTitle.TLabel', background=BG_CARD, foreground=TEXT_MAIN, font=(FONT_MAIN, 18, 'bold'))
        self.style.configure('HeaderSub.TLabel', background=BG_CARD, foreground=TEXT_MUTED, font=(FONT_MAIN, 10))

    def _setup_ui(self):
        # Main Container with Body Background
        main_container = ttk.Frame(self, style='Body.TFrame', padding=20)
        main_container.pack(fill=BOTH, expand=YES)
        
        # --- Header ---
        header_frame = ttk.Frame(main_container, style='Header.TFrame', padding=15)
        header_frame.pack(fill=X, pady=(0, 20))
        
        # Brand Area
        brand_frame = ttk.Frame(header_frame, style='Header.TFrame')
        brand_frame.pack(side=LEFT)
        
        # Logo Icon (Placeholder)
        self.logo_label = ttk.Label(brand_frame, text="M", font=("Segoe UI", 16, "bold"), background="#2563eb", foreground="white", width=3, anchor="center")
        self.logo_label.pack(side=LEFT, padx=(0, 15))
        
        # Titles
        title_box = ttk.Frame(brand_frame, style='Header.TFrame')
        title_box.pack(side=LEFT)
        ttk.Label(title_box, text="Sistema de Pesagem Industrial", style='HeaderTitle.TLabel').pack(anchor="w")
        ttk.Label(title_box, text="v2.0.1 • Conectado à BaseStation", style='HeaderSub.TLabel').pack(anchor="w")
        
        # Header Actions
        actions_frame = ttk.Frame(header_frame, style='Header.TFrame')
        actions_frame.pack(side=RIGHT)
        
        self.btn_connect = ttk.Button(actions_frame, text="Conectar Sistema", command=self.toggle_connection, bootstyle="success", padding=(15, 8))
        self.btn_connect.pack(side=LEFT, padx=10)
        
        ttk.Button(actions_frame, text="✕", command=self.quit_app, bootstyle="danger-outline", width=3).pack(side=LEFT)

        # --- Main Grid ---
        grid_area = ttk.Frame(main_container, style='Body.TFrame')
        grid_area.pack(fill=BOTH, expand=YES)
        
        grid_area.columnconfigure(0, weight=1) # Left
        grid_area.columnconfigure(1, weight=0) # Center (Fixed width handled by frame size)
        grid_area.columnconfigure(2, weight=1) # Right
        
        grid_area.rowconfigure(0, weight=1)
        grid_area.rowconfigure(1, weight=1)

        self.sensor_widgets = [] # Stores dicts of widgets for each sensor

        def create_sensor_card(parent, idx, row, col):
            # Card Container
            card = ttk.Frame(parent, style='Card.TFrame', padding=20)
            card.grid(row=row, column=col, sticky="nsew", padx=10, pady=10)
            
            # Header
            header = ttk.Frame(card, style='Card.TFrame')
            header.pack(fill=X, pady=(0, 15))
            
            title_lbl = ttk.Label(header, text=f"NÓ --", style='CardTitle.TLabel')
            title_lbl.pack(side=LEFT)
            
            rssi_lbl = ttk.Label(header, text="-- dBm", font=("Segoe UI", 9), bootstyle="secondary", padding=(5, 2))
            rssi_lbl.pack(side=RIGHT)
            
            # Value Area
            value_container = ttk.Frame(card, style='Body.TFrame', padding=10) # Light gray bg for value
            value_container.pack(fill=BOTH, expand=YES)
            
            value_lbl = ttk.Label(value_container, text="0.00", font=('Consolas', 36, 'bold'), background="#f0f2f5", foreground="#1e293b", anchor="center", width=8)
            value_lbl.pack(side=LEFT, expand=YES)
            
            unit_lbl = ttk.Label(value_container, text="t", font=('Segoe UI', 14), background="#f0f2f5", foreground="#64748b")
            unit_lbl.pack(side=RIGHT, padx=(0, 10))
            
            self.sensor_widgets.append({
                'title': title_lbl,
                'rssi': rssi_lbl,
                'value': value_lbl
            })

        # Create 4 Sensor Cards
        create_sensor_card(grid_area, 0, 0, 0) # Top Left
        create_sensor_card(grid_area, 1, 0, 2) # Top Right
        create_sensor_card(grid_area, 2, 1, 0) # Bottom Left
        create_sensor_card(grid_area, 3, 1, 2) # Bottom Right

        # --- Center Control Panel ---
        control_panel = ttk.Frame(grid_area, style='Card.TFrame') # White bg
        control_panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=10, pady=10)
        
        # Total Section (Blue Top)
        total_section = ttk.Frame(control_panel, style='TotalPanel.TFrame', padding=30)
        total_section.pack(fill=X)
        
        ttk.Label(total_section, text="TOTAL", style='TotalLabel.TLabel', anchor="center").pack(fill=X)
        self.lbl_total = ttk.Label(total_section, text="0.00", style='TotalValue.TLabel', anchor="center", width=8)
        self.lbl_total.pack(fill=X, pady=10)
        ttk.Label(total_section, text="t", background="#2563eb", foreground="white", font=("Segoe UI", 16), anchor="center").pack()
        
        # Actions Section (White Bottom)
        actions_section = ttk.Frame(control_panel, style='Card.TFrame', padding=30)
        actions_section.pack(fill=BOTH, expand=YES)
        
        btn_tare = ttk.Button(actions_section, text="TARA", command=self.do_tare, bootstyle="warning", style='Tare.TButton', width=15, padding=15)
        btn_tare.pack(pady=20)
        
        self.lbl_tare_info = ttk.Label(actions_section, text="Tara Acumulada: 0.00 t", style='CardTitle.TLabel', anchor="center")
        self.lbl_tare_info.pack(pady=10)
        
        btn_reset = ttk.Button(actions_section, text="Zerar Tara", command=self.reset_tare, bootstyle="secondary-outline", style='Reset.TButton', width=15, padding=10)
        btn_reset.pack(pady=10)

        # --- Log (Hidden or Minimal) ---
        # We'll put it at the bottom, small
        log_frame = ttk.Frame(main_container, style='Card.TFrame', padding=10)
        log_frame.pack(fill=X, side=BOTTOM, pady=(20, 0))
        self.log_text = ScrolledText(log_frame, height=3, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=YES)

    def _update_display(self):
        net_values, total_net, total_tare, slot_info, slot_status = self.data_processor.get_display_values()
        
        for i in range(4):
            widgets = self.sensor_widgets[i]
            
            # Update Value
            widgets['value'].configure(text=f"{net_values[i]:.2f}")
            
            # Update Title
            widgets['title'].configure(text=slot_info[i])
            
            # Update Status (RSSI)
            status = slot_status[i]
            rssi_val = status['rssi']
            is_stale = status['stale']
            
            if rssi_val != -999:
                rssi_text = f"{rssi_val} dBm"
                if rssi_val > -60:
                    bootstyle = "success"
                elif rssi_val > -80:
                    bootstyle = "warning"
                else:
                    bootstyle = "danger"
            else:
                rssi_text = "-- dBm"
                bootstyle = "secondary"
            
            if is_stale and slot_info[i] != "Aguardando...":
                rssi_text = "Sem sinal"
                bootstyle = "danger"
                widgets['value'].configure(foreground="#cbd5e1") # Gray out value
            else:
                widgets['value'].configure(foreground="#1e293b") # Normal color

            widgets['rssi'].configure(text=rssi_text, bootstyle=bootstyle)
            
        self.lbl_total.configure(text=f"{total_net:.2f}")
        self.lbl_tare_info.configure(text=f"Tara Acumulada: {total_tare:.2f} t")

    def do_tare(self):
        self.data_processor.set_tare()
        self._update_display()

    def reset_tare(self):
        self.data_processor.reset_tare()
        self._update_display()

    def log_message(self, message):
        self.log_text.configure(state='normal')
        self.log_text.insert(END, message + "\n")
        self.log_text.see(END)
        self.log_text.configure(state='disabled')

    def _update_loop(self):
        if self.connected:
            # Fetch data from sensor manager queue
            new_data_items = self.sensor_manager.get_data()
            
            # Process each item
            for node_id, data, rssi in new_data_items:
                self.data_processor.process_incoming_data(node_id, data, rssi)
        
        self._update_display()
        self.after(100, self._update_loop)

    def load_logo(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg")])
        if file_path:
            try:
                img = Image.open(file_path)
                img = img.resize((100, 50), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.logo_label.configure(image=photo, text="")
                self.logo_label.image = photo
                self.logger.log(f"Logo carregado: {file_path}")
            except Exception as e:
                self.logger.log(f"Erro ao carregar logo: {e}")

    def quit_app(self):
        result = Messagebox.show_question("Deseja fechar a aplicação?", "Sair", buttons=['Não:secondary', 'Sim:danger'], parent=self)
        if result == 'Sim':
            if self.connected:
                self.sensor_manager.disconnect()
            self.destroy()
            # Force exit to ensure all threads are killed
            import sys
            sys.exit(0)
            
    def toggle_connection(self):
        if not self.connected:
            self.btn_connect.configure(state="disabled", text="Buscando...")
            self.update()
            
            def connect_thread():
                success = self.sensor_manager.connect()
                self.after(0, lambda: self._post_connect(success))
            
            threading.Thread(target=connect_thread, daemon=True).start()
        else:
            self.sensor_manager.disconnect()
            self.connected = False
            self.btn_connect.configure(text="Conectar Sistema", bootstyle="success")
            self.logger.log("Desconectado.")

    def _post_connect(self, success):
        self.btn_connect.configure(state="normal")
        if success:
            self.connected = True
            self.btn_connect.configure(text="Desconectar", bootstyle="danger")
            self.logger.log("Sistema Online.")
        else:
            self.btn_connect.configure(text="Conectar Sistema", bootstyle="success")
            Messagebox.show_error("Não foi possível detectar o receptor sem fio.", "Erro de Conexão")
