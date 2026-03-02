# Trap Drive Board GUI: scan -> choose lock range -> enable PID -> live plots (last 5 min)
# All serial I/O at 9600 baud; every method opens/closes its own handle.
# Requires: PyQt5, pyqtgraph, pyserial

import sys, time, struct, csv, os
from datetime import datetime
from collections import deque
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg
import serial

# ---- Constants ----
SYSCLK = 500_000_000
VREF, RES = 3.3, 1024
PID_STATUS_USB   = ord('m')
PID_SETTINGS_USB = ord('e')
FEEDBACK_USB     = ord('g')
READ, WRITE      = 1, 0

# ---- Helpers ----
def ftw_to_freq_mhz(ftw, sysclk=SYSCLK):
    return (ftw * sysclk) / (2**32) / 1e6

def freq_to_ftw(freq_mhz, sysclk=SYSCLK):
    return int((freq_mhz * 1e6 * (2**32)) / sysclk) & 0xFFFFFFFF

def voltage_to_setpoint_scaled(voltage, k, vref=VREF, resolution=RES):
    code_10bit = int((voltage / vref) * (resolution - 1))
    return code_10bit * (4**k)

def adc_sum_to_volts(adc_sum, k, vref=VREF, res=RES):
    denom = (4**k) if k > 0 else 1
    return vref * (adc_sum / denom) / (res - 1)

def code_to_volts(code, k, vref=VREF):
    resolution = 1023 * (4 ** k)
    return code * vref / resolution

# ---- Device class: every call opens/closes serial at 9600 baud ----
class Trap_Drive_Board:
    def __init__(self, port, timeout=2.0):
        self.port = port
        self.timeout = timeout
        self.baud = 9600
        self.ser = serial.Serial(self.port, baudrate=self.baud, timeout=self.timeout)

    def _with_serial(self, func, *args, **kwargs):
        """Now just reuses the persistent serial handle."""
        if not self.ser.is_open:
            self.ser.open()
        return func(self.ser, *args, **kwargs)


    # PID enable
    def enable_pid(self, on=True):
        def inner(ser):
            ser.reset_input_buffer(); ser.reset_output_buffer()
            buf = bytearray(6)
            buf[0] = FEEDBACK_USB; buf[1] = WRITE; buf[2] = 0; buf[3] = 1 if on else 0; buf[4] = 0; buf[5] = 0
            ser.write(buf); ser.read(8)
        return self._with_serial(inner)

    # PID settings
    def set_pid(self, setpoint_v, p_gain, i_gain, fmin_mhz, fmax_mhz, k):
        def inner(ser):
            ser.reset_input_buffer(); ser.reset_output_buffer()
            sp = voltage_to_setpoint_scaled(setpoint_v, k)
            ftw_min, ftw_max = freq_to_ftw(fmin_mhz), freq_to_ftw(fmax_mhz)
            buf = bytearray(19)
            buf[0] = PID_SETTINGS_USB; buf[1] = WRITE
            buf[2:4]   = sp.to_bytes(2, 'big')
            buf[4:6]   = int(p_gain).to_bytes(2, 'big', signed=True)
            buf[6:10]  = int(i_gain).to_bytes(4, 'big', signed=True)
            buf[10]    = int(k) & 0xFF
            buf[11:15] = ftw_min.to_bytes(4, 'big')
            buf[15:19] = ftw_max.to_bytes(4, 'big')
            ser.write(buf); ser.read(2)
        return self._with_serial(inner)

    # PID status (for live)
    def read_pid_status(self):
        def inner(ser):
            ser.reset_input_buffer(); ser.reset_output_buffer()
            buf = bytearray(23); buf[0] = PID_STATUS_USB; buf[1] = READ
            ser.write(buf)
            resp = ser.read(23)
            if len(resp) < 23:
                raise IOError("Timeout or short PID status response")
            return {
                "OutputFTW": int.from_bytes(resp[11:15], 'big'),
                "amp_AdcSum": int.from_bytes(resp[17:19], 'big'),
                "Error32": int.from_bytes(resp[19:23], 'big', signed=True),
            }
        return self._with_serial(inner)

    # Amplitude and phase
    def set_trap_amplitude(self, amp_frac):
        def inner(ser):
            ser.reset_input_buffer(); ser.reset_output_buffer()
            AMP = int(max(0.0, min(1.0, float(amp_frac))) * 0x3FF) & 0x3FF
            ser.write(struct.pack('>cH', b't', AMP))
        return self._with_serial(inner)
    
    def set_trap_frequency(self, freq_mhz):
        def inner(ser):
            ser.reset_input_buffer(); ser.reset_output_buffer()
            ftw = freq_to_ftw(freq_mhz)
            msg = struct.pack('>cBBIHH', b'a', 0, 2, ftw, 0, 0)  # ch2, zero phase, keep amp as-is
            ser.write(msg)
        return self._with_serial(inner)


    def set_lo_amplitude(self, amp_frac):
        def inner(ser):
            ser.reset_input_buffer(); ser.reset_output_buffer()
            AMP = int(max(0.0, min(1.0, float(amp_frac))) * 0x3FF) & 0x3FF
            ser.write(struct.pack('>cH', b'l', AMP))
        return self._with_serial(inner)

    def set_phase_ch3(self, phase_deg):
        def inner(ser):
            ser.reset_input_buffer(); ser.reset_output_buffer()
            POW = int((float(phase_deg) / 360.0) * (2**14)) & 0x3FFF
            ser.write(struct.pack('>cBH', b'q', 3, POW))
        return self._with_serial(inner)
    
    

    # Dispersion scan
    def scan(self, f_lo_hz, f_hi_hz, n_steps, k):
        def inner(ser):
            ser.reset_input_buffer(); ser.reset_output_buffer()
            cmd = bytearray([ord('s')])
            cmd += int(f_lo_hz).to_bytes(4, 'big')
            cmd += int(f_hi_hz).to_bytes(4, 'big')
            cmd += int(n_steps).to_bytes(2, 'big')
            cmd.append(int(k) & 0xFF)
            cmd += bytes(64 - len(cmd))
            ser.write(cmd)
            expected = int(n_steps) * 8
            resp = bytearray()
            deadline = time.time() + 60
            while len(resp) < expected:
                if time.time() > deadline:
                    print("timeout")
                    raise TimeoutError("USB read timeout during scan")
                chunk = ser.read(expected - len(resp))
                if chunk:
                    resp += chunk
            out = []
            for i in range(int(n_steps)):
                b = 8 * i
                freq_word = int.from_bytes(resp[b:b+4], 'big')
                ch0 = int.from_bytes(resp[b+4:b+6], 'big')
                ch1 = int.from_bytes(resp[b+6:b+8], 'big')
                out.append((freq_word, ch0, ch1))
            return out
        return self._with_serial(inner)

# ---- GUI ----
class LiveApp(QtWidgets.QWidget):
    def __init__(self, board: Trap_Drive_Board, sample_ms=3000):
        super().__init__()
        self.board = board
        self.setWindowTitle("Trap Drive Board — Scan and Lock")
        self.resize(1500, 900)

        # State
        self.pid_enabled = False
        self.session_tag = datetime.now().strftime("%Y%m%d_%H%M%S")

        # --- Controls ---
        self.enableChk = QtWidgets.QCheckBox("Enable PID"); self.enableChk.setChecked(False)
        self.startBtn  = QtWidgets.QPushButton("Start live"); self.startBtn.setCheckable(True); self.startBtn.setEnabled(False)
        self.saveBtn   = QtWidgets.QPushButton("Save CSV")
        self.clearBtn  = QtWidgets.QPushButton("Clear")
        self.statusLab = QtWidgets.QLabel("PID disabled")

        # --- Scan controls ---
        self.scanBtn = QtWidgets.QPushButton("Run Scan")
        self.phaseDegSpin = QtWidgets.QDoubleSpinBox(); self.phaseDegSpin.setRange(0.0, 360.0); self.phaseDegSpin.setDecimals(2); self.phaseDegSpin.setSingleStep(1.0); self.phaseDegSpin.setValue(0.0)
        self.loAmpSpin = QtWidgets.QDoubleSpinBox(); self.loAmpSpin.setRange(0.0, 1.0); self.loAmpSpin.setDecimals(3); self.loAmpSpin.setSingleStep(0.01); self.loAmpSpin.setValue(0.5)
        self.trapAmpSpin = QtWidgets.QDoubleSpinBox(); self.trapAmpSpin.setRange(0.0, 1.0); self.trapAmpSpin.setDecimals(3); self.trapAmpSpin.setSingleStep(0.01); self.trapAmpSpin.setValue(0.5)

        # --- Scan range ---
        self.scanFloSpin = QtWidgets.QDoubleSpinBox(); self.scanFloSpin.setRange(1.0, 1000.0); self.scanFloSpin.setDecimals(3); self.scanFloSpin.setValue(19.600)
        self.scanFhiSpin = QtWidgets.QDoubleSpinBox(); self.scanFhiSpin.setRange(1.0, 1000.0); self.scanFhiSpin.setDecimals(3); self.scanFhiSpin.setValue(20.600)

        # --- Lock range ---
        self.lockFloSpin = QtWidgets.QDoubleSpinBox(); self.lockFloSpin.setRange(1.0, 1000.0); self.lockFloSpin.setDecimals(3); self.lockFloSpin.setValue(19.950)
        self.lockFhiSpin = QtWidgets.QDoubleSpinBox(); self.lockFhiSpin.setRange(1.0, 1000.0); self.lockFhiSpin.setDecimals(3); self.lockFhiSpin.setValue(20.050)

        # --- Other scan parameters ---
        self.stepsSpin = QtWidgets.QSpinBox(); self.stepsSpin.setRange(8, 4096); self.stepsSpin.setValue(128)
        self.kSpin = QtWidgets.QSpinBox(); self.kSpin.setRange(0, 8); self.kSpin.setValue(3)

        # --- PID params ---
        self.setpointSpin = QtWidgets.QDoubleSpinBox(); self.setpointSpin.setRange(0.0, 3.3); self.setpointSpin.setDecimals(3); self.setpointSpin.setValue(1.65)
        self.pgainSpin = QtWidgets.QSpinBox(); self.pgainSpin.setRange(-32768, 32767); self.pgainSpin.setValue(10)
        self.igainSpin = QtWidgets.QSpinBox(); self.igainSpin.setRange(-2**31, 2**31-1); self.igainSpin.setValue(4)

        # --- Layout (top controls) ---
        top = QtWidgets.QGridLayout()
        r = 0
        top.addWidget(self.enableChk, r, 0); top.addWidget(self.startBtn, r, 1); top.addWidget(self.saveBtn, r, 2); top.addWidget(self.clearBtn, r, 3)
        top.addWidget(QtWidgets.QLabel("Status:"), r, 4); top.addWidget(self.statusLab, r, 5, 1, 4)

        r += 1
        top.addWidget(QtWidgets.QLabel("LO phase (deg)"), r, 0); top.addWidget(self.phaseDegSpin, r, 1)
        top.addWidget(QtWidgets.QLabel("LO amp"), r, 2); top.addWidget(self.loAmpSpin, r, 3)
        top.addWidget(QtWidgets.QLabel("Trap amp"), r, 4); top.addWidget(self.trapAmpSpin, r, 5)
        top.addWidget(QtWidgets.QLabel("Scan f_lo (MHz)"), r, 6); top.addWidget(self.scanFloSpin, r, 7)
        top.addWidget(QtWidgets.QLabel("Scan f_hi (MHz)"), r, 8); top.addWidget(self.scanFhiSpin, r, 9)
        top.addWidget(QtWidgets.QLabel("steps"), r, 10); top.addWidget(self.stepsSpin, r, 11)
        top.addWidget(QtWidgets.QLabel("k"), r, 12); top.addWidget(self.kSpin, r, 13)
        top.addWidget(self.scanBtn, r, 14)

        r += 1
        top.addWidget(QtWidgets.QLabel("Lock f_lo (MHz)"), r, 6); top.addWidget(self.lockFloSpin, r, 7)
        top.addWidget(QtWidgets.QLabel("Lock f_hi (MHz)"), r, 8); top.addWidget(self.lockFhiSpin, r, 9)

        r += 1
        top.addWidget(QtWidgets.QLabel("PID setpoint (V)"), r, 0); top.addWidget(self.setpointSpin, r, 1)
        top.addWidget(QtWidgets.QLabel("P"), r, 2); top.addWidget(self.pgainSpin, r, 3)
        top.addWidget(QtWidgets.QLabel("I"), r, 4); top.addWidget(self.igainSpin, r, 5)

        # --- Plots ---
        pg.setConfigOptions(antialias=True)
        self.p_freq = pg.PlotWidget(title="Frequency (MHz)")
        self.p_err  = pg.PlotWidget(title="Error32")
        self.p_setA = pg.PlotWidget(title="Set amplitude (fraction)")
        self.p_measA= pg.PlotWidget(title="Measured amplitude (V)")
        for p in (self.p_freq, self.p_err, self.p_setA, self.p_measA):
            p.showGrid(x=True, y=True)
        self.c_freq = self.p_freq.plot([], [], pen=pg.mkPen(width=2))
        self.c_err  = self.p_err.plot([], [], pen=pg.mkPen(width=2))
        self.c_setA = self.p_setA.plot([], [], pen=pg.mkPen(width=2))
        self.c_measA= self.p_measA.plot([], [], pen=pg.mkPen(width=2))

        self.p_scan = pg.PlotWidget(title="Scan (select view range)")
        self.p_scan.setBackground('w')
        self.p_scan.showGrid(x=True, y=True)
        self.p_scan.setLabel('bottom', 'Frequency (MHz)')
        self.p_scan.setLabel('left', 'Voltage (V)')

        # --- Layout for plots ---
        grid = QtWidgets.QGridLayout()
        grid.addWidget(self.p_freq, 0, 0)
        grid.addWidget(self.p_err,  0, 1)
        grid.addWidget(self.p_setA, 1, 0)
        grid.addWidget(self.p_measA,1, 1)
        grid.addWidget(self.p_scan, 0, 2, 2, 1)

        main = QtWidgets.QVBoxLayout(self)
        main.addLayout(top)
        main.addLayout(grid)

        # --- Buffers and timer ---
        nmax = 200000
        self.t = deque(maxlen=nmax)
        self.set_amp = deque(maxlen=nmax)
        self.meas_amp_V = deque(maxlen=nmax)
        self.err = deque(maxlen=nmax)
        self.freq = deque(maxlen=nmax)
        self.t0 = time.time()

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(sample_ms)
        self.timer.timeout.connect(self.sample_once)

        # --- Signal connections ---
        self.enableChk.toggled.connect(self.on_enable_toggled)
        self.startBtn.toggled.connect(self.toggle_run)
        self.saveBtn.clicked.connect(self.save_csv)
        self.clearBtn.clicked.connect(self.clear_data)
        self.scanBtn.clicked.connect(self.on_run_scan_clicked)
        self.trapAmpSpin.valueChanged.connect(self.on_trap_amp_changed)
        self.loAmpSpin.valueChanged.connect(self.on_lo_amp_changed)
        self.phaseDegSpin.valueChanged.connect(self.on_phase_changed)

        # --- Manual trap frequency write ---
        r += 1
        self.trapFreqSpin = QtWidgets.QDoubleSpinBox()
        self.trapFreqSpin.setRange(1.0, 1000.0)
        self.trapFreqSpin.setDecimals(3)
        self.trapFreqSpin.setValue(20.000)
        self.trapWriteBtn = QtWidgets.QPushButton("Write Trap Freq+Amp")
        self.trapWriteBtn.clicked.connect(self.on_trap_write_clicked)
        top.addWidget(QtWidgets.QLabel("Trap freq (MHz)"), r, 0)
        top.addWidget(self.trapFreqSpin, r, 1)
        top.addWidget(self.trapWriteBtn, r, 2)



        # --- Initial device sync ---
        self.on_phase_changed(self.phaseDegSpin.value())
        self.on_lo_amp_changed(self.loAmpSpin.value())
        self.on_trap_amp_changed(self.trapAmpSpin.value())

    # ---- Slots ----
    def on_phase_changed(self, deg):
        try:
            self.board.set_phase_ch3(deg)
            self.statusLab.setText(f"LO phase {float(deg):.2f}°")
        except Exception as e:
            self.statusLab.setText(f"Phase error: {e}")

    def on_trap_write_clicked(self):
        if self.pid_enabled:
            self.statusLab.setText("Disable PID to write trap")
            return
        try:
            freq = float(self.trapFreqSpin.value())
            amp = float(self.trapAmpSpin.value())
            self.board.set_trap_frequency(freq)
            self.board.set_trap_amplitude(amp)
            self.statusLab.setText(f"Trap ch2 set {freq:.3f} MHz, amp {amp:.3f}")
        except Exception as e:
            self.statusLab.setText(f"Trap write error: {e}")



    def on_lo_amp_changed(self, val):
        try:
            self.board.set_lo_amplitude(val)
            self.statusLab.setText(f"LO amp {float(val):.3f}")
        except Exception as e:
            self.statusLab.setText(f"LO amp error: {e}")

    def on_trap_amp_changed(self, val):
        try:
            self.board.set_trap_amplitude(val)
            self.statusLab.setText(f"Trap amp {float(val):.3f}")
        except Exception as e:
            self.statusLab.setText(f"Trap amp error: {e}")

    def on_enable_toggled(self, checked):
        try:
            self.board.enable_pid(checked)
            self.pid_enabled = checked
            self.startBtn.setEnabled(checked)
            self.scanBtn.setEnabled(not checked)
            if checked:
                fmin = float(self.lockFloSpin.value())
                fmax = float(self.lockFhiSpin.value())
                self.board.set_pid(
                    setpoint_v=self.setpointSpin.value(),
                    p_gain=self.pgainSpin.value(),
                    i_gain=self.igainSpin.value(),
                    fmin_mhz=fmin,
                    fmax_mhz=fmax,
                    k=self.kSpin.value()
                )
                self.statusLab.setText("PID enabled")
            else:
                if self.timer.isActive():
                    self.timer.stop()
                    self.startBtn.setChecked(False)
                self.statusLab.setText("PID disabled")
        except Exception as e:
            self.statusLab.setText(f"Enable error: {e}")


    def toggle_run(self, checked):
        if checked:
            if not self.pid_enabled:
                self.statusLab.setText("Enable PID to run live"); self.startBtn.setChecked(False); return
            self.timer.start(); self.statusLab.setText("Live running")
        else:
            self.timer.stop(); self.statusLab.setText("Live stopped")

    def sample_once(self):
        if not self.pid_enabled:
            return
        try:
            s = self.board.read_pid_status()
            now = time.time() - self.t0
            v_amp = adc_sum_to_volts(s["amp_AdcSum"], self.kSpin.value())
            err = s["Error32"]
            fmhz = ftw_to_freq_mhz(s["OutputFTW"])
        except Exception as e:
            self.statusLab.setText(f"Read error: {e}")
            return
        self.t.append(now)
        self.set_amp.append(self.trapAmpSpin.value())
        self.meas_amp_V.append(v_amp)
        self.err.append(err)
        self.freq.append(fmhz)
        # last 5 minutes
        t_arr = list(self.t)
        cutoff = t_arr[-1] - 300.0
        idx0 = next((i for i, tv in enumerate(t_arr) if tv >= cutoff), 0)
        t_arr = t_arr[idx0:]
        self.c_freq.setData(t_arr, list(self.freq)[idx0:])
        self.c_err.setData(t_arr, list(self.err)[idx0:])
        self.c_setA.setData(t_arr, list(self.set_amp)[idx0:])
        self.c_measA.setData(t_arr, list(self.meas_amp_V)[idx0:])

    def clear_data(self):
        self.t.clear(); self.set_amp.clear(); self.meas_amp_V.clear(); self.err.clear(); self.freq.clear()
        self.c_freq.clear(); self.c_err.clear(); self.c_setA.clear(); self.c_measA.clear()
        self.t0 = time.time(); self.statusLab.setText("Cleared")

    def save_csv(self):
        rows = list(zip(self.t, self.set_amp, self.meas_amp_V, self.err, self.freq))
        if not rows:
            self.statusLab.setText("No data to save"); return
        default_name = f"pid_live_{self.session_tag}.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save CSV", default_name, "CSV Files (*.csv)")
        if not path: return
        try:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["time_s", "set_amp_frac", "measured_amp_V", "error32", "freq_MHz"])
                w.writerows(rows)
            self.statusLab.setText(f"Saved {os.path.basename(path)}")
        except Exception as e:
            self.statusLab.setText(f"Save error: {e}")

    def on_run_scan_clicked(self):
        if self.pid_enabled:
            self.statusLab.setText("Disable PID to scan")
            return
        try:
            # Apply scan settings
            self.board.set_phase_ch3(self.phaseDegSpin.value())
            self.board.set_lo_amplitude(self.loAmpSpin.value())
            self.board.set_trap_amplitude(self.trapAmpSpin.value())

            f_lo = float(self.scanFloSpin.value()) * 1e6
            f_hi = float(self.scanFhiSpin.value()) * 1e6
            n_steps = int(self.stepsSpin.value())
            k = int(self.kSpin.value())

            results = self.board.scan(f_lo, f_hi, n_steps, k)

            freqs_hz, ch0_v, ch1_v = [], [], []
            for freq, ch0, ch1 in results:
                freqs_hz.append(freq)
                ch0_v.append(code_to_volts(ch0, k))
                ch1_v.append(code_to_volts(ch1, k))

            freqs_mhz = [f/1e6 for f in freqs_hz]

            # Plot error and transmission
            self.p_scan.clear()
            self.p_scan.addLegend()
            self.p_scan.setBackground('w')
            self.p_scan.showGrid(x=True, y=True)
            self.p_scan.setLabel('bottom', 'Frequency (MHz)')
            self.p_scan.setLabel('left', 'Voltage (V)')
            self.c_scan_ch0 = self.p_scan.plot(freqs_mhz, ch0_v, pen=pg.mkPen('b', width=2), name="Error Signal")
            self.c_scan_ch1 = self.p_scan.plot(freqs_mhz, ch1_v, pen=pg.mkPen('r', width=2), name="Transmitted Power")

            # ---- Extract resonant power and Q from raw data ----
            import numpy as np
            f_arr = np.array(freqs_mhz)
            p_arr = np.array(ch1_v)

            # Peak power and its frequency
            peak_idx = np.argmax(p_arr)
            peak_power = p_arr[peak_idx]
            f0 = f_arr[peak_idx]

            # Half max level
            half_max = peak_power / 2.0

            # Find nearest crossings around the peak
            left_idx = np.where(p_arr[:peak_idx] <= half_max)[0]
            right_idx = np.where(p_arr[peak_idx:] <= half_max)[0]

            if left_idx.size > 0 and right_idx.size > 0:
                f_left = f_arr[left_idx[-1]]
                f_right = f_arr[peak_idx + right_idx[0]]
                fwhm = f_right - f_left
                q_factor = f0 / fwhm if fwhm > 0 else np.nan
            else:
                fwhm = np.nan
                q_factor = np.nan

            # ---- Display results in a box under the scan plot (right side) ----
            resonance_freq = f0  # frequency at max transmitted power

            if not hasattr(self, 'fitResultsContainer'):
                self.fitResultsContainer = QtWidgets.QWidget()
                hbox = QtWidgets.QHBoxLayout(self.fitResultsContainer)
                hbox.setContentsMargins(0, 0, 0, 0)
                hbox.addStretch()

                self.fitResultsLabel = QtWidgets.QLabel()
                font = self.fitResultsLabel.font()
                font.setPointSize(14)
                font.setBold(True)
                self.fitResultsLabel.setFont(font)
                self.fitResultsLabel.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

                hbox.addWidget(self.fitResultsLabel)
                self.layout().addWidget(self.fitResultsContainer)

            self.fitResultsLabel.setText(
                f"Resonance = {resonance_freq:.2f} MHz    Peak Power = {peak_power:.4f} V    Q = {q_factor:.2f}"
            )


            self.statusLab.setText("Scan complete")
        except Exception as e:
            self.statusLab.setText(f"Scan error: {e}")


    def closeEvent(self, ev):
        try:
            if self.timer.isActive():
                self.timer.stop()
            # ensure PID off on exit
            self.board.enable_pid(False)
        except Exception:
            pass
        super().closeEvent(ev)

# ---- main ----
if __name__ == "__main__":
    port = "COM7" if len(sys.argv) < 2 else sys.argv[1]
    board = Trap_Drive_Board(port)
    app = QtWidgets.QApplication(sys.argv)
    w = LiveApp(board, sample_ms=200)
    w.show()
    sys.exit(app.exec_())
