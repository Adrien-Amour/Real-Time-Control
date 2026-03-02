import sys
import os
import time
import threading
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QDoubleSpinBox, QPushButton, QLineEdit
)
from PyQt5.QtCore import QTimer, Qt
import pyqtgraph as pg

from adriq.Servers import Client
from adriq.RedLabs_Dac import Redlabs_DAC
from pylablib.devices import HighFinesse

# Initialize WLM
app_folder = r"C:\Program Files (x86)\HighFinesse\Wavelength Meter WS7 417"
dll_path = os.path.join(app_folder, "Projects", "64")
app_path = os.path.join(app_folder, "wlm_ws7.exe")
wm = HighFinesse.WLM(417, dll_path=dll_path, app_path=app_path)

# Initialize DAC
DAC = Client(Redlabs_DAC)

class PIDApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PID Feedback Control")
        self.setGeometry(100, 100, 800, 600)

        # PID and setpoint values
        self.setpoint = 422.79167
        self.P = 10.0
        self.I = 5.0
        self.D = 2.0
        self.integral = 0
        self.prev_error = 0
        self.feedback_enabled = False

        # Acquisition control and safety thresholds
        self.acquisition_enabled = True
        self.read_fail_count = 0
        self.max_read_failures = 3
        self.auto_disable_error_nm = 1.0  # auto-disable if |error| >= this (nm)

        self.errors = []
        self.times = []
        self.start_time = time.time()

        self.init_ui()
        self.init_timer()

    def init_ui(self):
        layout = QVBoxLayout()

        # --- Controls ---
        control_layout = QHBoxLayout()

        self.p_spin = self.create_spinbox("P:", self.P, control_layout)
        self.i_spin = self.create_spinbox("I:", self.I, control_layout)
        self.d_spin = self.create_spinbox("D:", self.D, control_layout)

        # Wavelength setpoint input
        control_layout.addWidget(QLabel("Setpoint (nm):"))
        self.setpoint_input = QLineEdit(str(self.setpoint))
        self.setpoint_input.setFixedWidth(100)
        self.setpoint_input.editingFinished.connect(self.update_setpoint)
        control_layout.addWidget(self.setpoint_input)

        # On/Off Button (feedback)
        self.toggle_button = QPushButton("Enable Feedback")
        self.toggle_button.setCheckable(True)
        self.toggle_button.clicked.connect(self.toggle_feedback)
        control_layout.addWidget(self.toggle_button)

        # Acquisition toggle button
        self.acq_button = QPushButton("Enable Acquisition")
        self.acq_button.setCheckable(True)
        self.acq_button.setChecked(True)
        self.acq_button.setText("Disable Acquisition")
        self.acq_button.clicked.connect(self.toggle_acquisition)
        control_layout.addWidget(self.acq_button)

        # --- Zero Feedback Button ---
        self.zero_button = QPushButton("Zero Feedback")
        self.zero_button.clicked.connect(self.zero_feedback)
        control_layout.addWidget(self.zero_button)

        layout.addLayout(control_layout)

        # Feedback display
        self.feedback_label = QLabel("Feedback: 0.000 V")
        layout.addWidget(self.feedback_label)

        # --- Error plot ---
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("left", "Error (nm)")
        self.plot_widget.setLabel("bottom", "Time (s)")
        self.plot_widget.showGrid(x=True, y=True)

        self.error_curve = self.plot_widget.plot([], [], pen='r')
        layout.addWidget(self.plot_widget)

        self.setLayout(layout)

    def create_spinbox(self, label, value, layout):
        layout.addWidget(QLabel(label))
        spin = QDoubleSpinBox()
        spin.setRange(-1000, 1000)
        spin.setValue(value)
        spin.setDecimals(3)
        layout.addWidget(spin)
        return spin

    def update_setpoint(self):
        try:
            self.setpoint = float(self.setpoint_input.text())
        except ValueError:
            self.setpoint_input.setText(str(self.setpoint))

    def toggle_feedback(self):
        self.feedback_enabled = self.toggle_button.isChecked()
        self.toggle_button.setText("Disable Feedback" if self.feedback_enabled else "Enable Feedback")

    def toggle_acquisition(self):
        self.acquisition_enabled = self.acq_button.isChecked()
        self.acq_button.setText("Disable Acquisition" if self.acquisition_enabled else "Enable Acquisition")
        if not self.acquisition_enabled:
            self.feedback_label.setText("Acquisition: OFF")

    def zero_feedback(self):
        DAC.set_PI_lock_voltage(0)
        self.integral = 0
        self.feedback_label.setText("Feedback: 0.000 V (Zeroed)")

    def init_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_loop)
        self.timer.start(100)

    def disable_acquisition(self, reason: str):
        # Helper to programmatically turn acquisition off and update UI without re-triggering the slot
        self.acquisition_enabled = False
        self.acq_button.blockSignals(True)
        self.acq_button.setChecked(False)
        self.acq_button.blockSignals(False)
        self.acq_button.setText("Enable Acquisition")
        self.feedback_label.setText(f"Acquisition: OFF ({reason})")

    def update_loop(self):
        # Skip everything if acquisition is disabled
        if not self.acquisition_enabled:
            self.feedback_label.setText("Acquisition: OFF")
            return

        # Try to acquire wavelength
        try:
            wavelength = wm.get_wavelength() * 1e9  # Convert to nm
            self.read_fail_count = 0  # reset on success
        except Exception as e:
            self.read_fail_count += 1
            self.feedback_label.setText(f"Read failed ({self.read_fail_count}/{self.max_read_failures}): {e}")
            if self.read_fail_count >= self.max_read_failures:
                self.disable_acquisition("3 consecutive read failures")
            return

        # Compute error and auto-disable if too far from setpoint
        error = self.setpoint - wavelength
        if abs(error) >= self.auto_disable_error_nm:
            self.disable_acquisition(f"|error|={abs(error):.3f} nm >= {self.auto_disable_error_nm} nm")
            return

        # Normal plotting
        self.errors.append(error)
        self.times.append(time.time() - self.start_time)
        self.errors = self.errors[-100:]
        self.times = self.times[-100:]
        self.error_curve.setData(self.times, self.errors)

        # Update PID gains from UI
        self.P = self.p_spin.value()
        self.I = self.i_spin.value()
        self.D = self.d_spin.value()

        # Apply PID only when feedback is enabled and we have a valid reading
        if self.feedback_enabled:
            self.integral += error
            derivative = error - self.prev_error
            feedback = self.P * error + self.I * self.integral + self.D * derivative
            self.feedback_label.setText(f"Feedback: {feedback:.3f} V")
            DAC.set_PI_lock_voltage(feedback)

        self.prev_error = error


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PIDApp()
    window.show()
    sys.exit(app.exec_())
