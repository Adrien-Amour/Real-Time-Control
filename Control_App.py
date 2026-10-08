import tkinter as tk
from tkinter import ttk
from adriq.ad9910 import *
from adriq.Counters import *
from adriq.RedLabs_Dac import *
from adriq.pulse_sequencer import *
from adriq.Custom_Tkinter import *
from adriq.Optomechanics import *
from adriq.laser_calibration import *
from adriq.Trap_RF_Board import TrapControlWidget
from adriq.HMP_4030 import HMP_4030, PSU_Control_Frame

shift = 10

class ControlApp(tk.Tk):
    def __init__(self):

        self.lasers = create_laser_objects(
            r"C:\Users\probe\OneDrive - University of Sussex\Desktop\Experiment_Config\dds_config.cfg",
            include_lasers=[
                "397b", "397c", "866 RP", "854 Cav", "850 RP", "866 OP", "866S", "397a", "850 SP1", "850 SP2",  "854 SP1", "854 SP2", "729 t1", "729 t2"
            ]
        )
        # self.lasers = create_laser_objects(
        #     r"C:\Users\probe\OneDrive - University of Sussex\Desktop\Experiment_Config\dds_config.cfg",
        #     include_lasers=[
        #         "397b", "397c", "866 RP", "854 Cav"
        #     ]
        # )

        super().__init__()
        self.title("Control Application")
        self.geometry("635x1000")

        # Create notebook (tabbed interface)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        # Main tab
        self.main_tab = tk.Frame(self.notebook)
        self.notebook.add(self.main_tab, text="Main")

        # Running Stuff tab
        self.running_tab = tk.Frame(self.notebook)
        self.notebook.add(self.running_tab, text="Running Stuff")

        # NEW: RAM tab
        self.ram_tab = tk.Frame(self.notebook)
        self.notebook.add(self.ram_tab, text="RAM")

        # --- Main Tab Widgets ---
        self.load_control_panel = LoadControlPanel(
            self.main_tab, PMT_Reader, Redlabs_DAC, Threshold=2000, Timeout=100
        )
        self.load_control_panel.place(x=shift+0, y=520, anchor="nw", width=580, height=380)

        self.trap_control_frame = TrapControlFrame(
            self.main_tab, QuTau_Reader, Redlabs_DAC,
            config_file=r"C:\Users\probe\OneDrive - University of Sussex\Desktop\Experiment_Config\dc_null_history.csv",
            default_trap_depth=0.8
        )
        self.trap_control_frame.place(x=shift+300, y=530, anchor="nw", width=580, height=380)

        self.logo_label = Watermark(self.main_tab)
        # Place Trap Control widget where the logo was
        trap_x = shift + 18
        trap_y = 765
        self.trap_widget = TrapControlWidget(self.main_tab)
        self.trap_widget.place(x=trap_x, y=trap_y, anchor="nw", width=275, height=35)
        # Move the logo just below the widget
        self.logo_label.place(x=trap_x, y=trap_y + 70, anchor="nw")

        self.pulse_sequencer_frame = PulseSequencerFrame(
            self.main_tab, defaultbitstring="0100000000000000", pulse_sequencer_port="COM5"
        )
        self.pulse_sequencer_frame.place(x=shift+10, y=710, anchor="nw", width=300, height=50)

        self.laser_control = LaserControl(self.main_tab)
        for laser in self.lasers:
            self.laser_control.add_laser(laser)
        self.laser_control.place(x=shift+0, y=0, anchor="nw", width=650, height=480)

        # Add quick preset buttons
        self.laser_control.add_quick_preset_button(
            "Cooling",
            r"C:\Users\probe\OneDrive - University of Sussex\Desktop\Python_Package2\ADRIQ\examples\presets\cooling.json",
            bg="#AEC6CF"
        )
        self.laser_control.add_quick_preset_button(
            "Trapping",
            r"C:\Users\probe\OneDrive - University of Sussex\Desktop\Python_Package2\ADRIQ\examples\presets\trapping.json",
            bg="#FFB6C1"
        )

        self.piezo_control_panel = PiezoControlPanel(self.main_tab, Redlabs_DAC)
        self.piezo_control_panel.place(x=shift, y=500, anchor="nw", width=200, height=30)

        self.qwp_control_panel = WaveplateMountControlPanel(self.main_tab, Standa_Motorised_WaveplateMount)
        self.qwp_control_panel.place(x=shift+220, y=500, anchor="nw", width=200, height=30)

        self.hwp_control_panel = WaveplateMountControlPanel(self.main_tab, Thorlabs_Motorised_WaveplateMount)
        self.hwp_control_panel.place(x=shift+440, y=500, anchor="nw", width=200, height=30)

        # Dynamically resize LaserControl and push everything below it down if needed
        self.update_idletasks()
        lc_req_h = self.laser_control.winfo_reqheight()
        # Expand laser control height if content grew
        current_h = int(float(self.laser_control.place_info().get("height", 0)) or 0)
        if lc_req_h > current_h:
            self.laser_control.place_configure(height=lc_req_h)
            current_h = lc_req_h

        # Compute how far the "row" that starts at y=500 must be shifted
        new_base_y = self.laser_control.winfo_y() + current_h + 10  # 10px spacing
        original_base_y = 500
        delta = max(0, new_base_y - original_base_y)
        if delta:
            for w in (
                self.piezo_control_panel, self.qwp_control_panel, self.hwp_control_panel,
                self.load_control_panel, self.trap_control_frame, self.pulse_sequencer_frame,
                self.trap_widget, self.logo_label
            ):
                info = w.place_info()
                if info:
                    y = int(float(info.get("y", 0)))
                    w.place_configure(y=y + delta)

        # --- Running Stuff Tab Widgets ---
        self.calibration_frame = CalibrationFrame(self.running_tab)
        self.calibration_frame.place(x=shift+10, y=10, anchor="nw", width=300, height=500)

        # --- RAM Tab Widgets ---
        self.ram_control_frame = RamControlFrame(self.ram_tab, self.lasers)
        self.ram_control_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # self.coil_control_widget = PSU_Control_Frame(self.main_tab)
        # self.coil_control_widget.place(x=trap_x, y=trap_y+210, anchor="nw", width=270, height=30)
        # Move the logo just below the widget

if __name__ == "__main__":
    app = ControlApp()
    app.mainloop()