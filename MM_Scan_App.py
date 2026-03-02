import os
import csv
import time
import threading
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from adriq.RedLabs_Dac import Redlabs_DAC
from adriq.Counters import QuTau_Reader
from adriq.Servers import Client

def sine_wave_local(x, amplitude, frequency, phase, offset):
    return amplitude * np.sin(2 * np.pi * frequency * x + phase) + offset


class RFScanApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RF Correlation Scanner")
        self.geometry("1100x700")

        # Hardware clients
        self.dac = Client(Redlabs_DAC)
        self.qutau = Client(QuTau_Reader)

        # State
        self.running = False
        self.worker = None
        self.idx = 0
        # Replace H-only state with generalized axis state
        self.scan_axis = 'V'
        self.scan_vals = np.array([])
        self.H = -1.4    # fixed H when scanning V (default)
        self.V = -0.6    # fixed V when scanning H

        # Results
        self.amps_percent = []
        self.phases_pi = []
        self.hist_list = []   # list of np arrays
        self.edges_list = []  # list of np arrays
        self.popt_list = []   # list of fit params

        self._build_ui()

    def _build_ui(self):
        ctrl = ttk.LabelFrame(self, text="Scan Controls")
        ctrl.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        # New: Scan axis selector
        r = 0
        ttk.Label(ctrl, text="Scan axis").grid(row=r, column=0, sticky="e", padx=4, pady=2)
        self.axis_combo = ttk.Combobox(ctrl, values=["H", "V"], state="readonly", width=6)
        self.axis_combo.set("V")
        self.axis_combo.grid(row=r, column=1, padx=4, pady=2)
        self.axis_combo.bind("<<ComboboxSelected>>", lambda e: self._on_axis_change())

        # Row 1: Range and fixed entries (two groups, toggle by axis)
        r += 1
        # H-scan group (H range, fixed V)
        self.lbl_h_start = ttk.Label(ctrl, text="H start")
        self.lbl_h_start.grid(row=r, column=0, sticky="e", padx=4, pady=2)
        self.h_start = ttk.Entry(ctrl, width=10)
        self.h_start.insert(0, "-1.275")
        self.h_start.grid(row=r, column=1, padx=4, pady=2)

        self.lbl_h_stop = ttk.Label(ctrl, text="H stop")
        self.lbl_h_stop.grid(row=r, column=2, sticky="e", padx=4, pady=2)
        self.h_stop = ttk.Entry(ctrl, width=10)
        self.h_stop.insert(0, "-1.475")
        self.h_stop.grid(row=r, column=3, padx=4, pady=2)

        self.lbl_h_points = ttk.Label(ctrl, text="# points")
        self.lbl_h_points.grid(row=r, column=4, sticky="e", padx=4, pady=2)
        self.h_points = ttk.Entry(ctrl, width=8)
        self.h_points.insert(0, "9")
        self.h_points.grid(row=r, column=5, padx=4, pady=2)

        self.lbl_v_fixed = ttk.Label(ctrl, text="V")
        self.lbl_v_fixed.grid(row=r, column=6, sticky="e", padx=4, pady=2)
        self.v_entry = ttk.Entry(ctrl, width=8)
        self.v_entry.insert(0, "-0.6")
        self.v_entry.grid(row=r, column=7, padx=4, pady=2)

        # V-scan group (V range, fixed H)
        self.lbl_v_start = ttk.Label(ctrl, text="V start")
        self.v_start = ttk.Entry(ctrl, width=10)
        self.v_start.insert(0, "-0.8")

        self.lbl_v_stop = ttk.Label(ctrl, text="V stop")
        self.v_stop = ttk.Entry(ctrl, width=10)
        self.v_stop.insert(0, "-0.7")

        self.lbl_v_points = ttk.Label(ctrl, text="# points")
        self.v_points = ttk.Entry(ctrl, width=8)
        self.v_points.insert(0, "9")

        self.lbl_h_fixed = ttk.Label(ctrl, text="H")
        self.h_fixed = ttk.Entry(ctrl, width=8)
        self.h_fixed.insert(0, "-1.4")

        # Place V-scan group widgets in same grid positions, initially hidden
        self.lbl_v_start.grid(row=r, column=0, sticky="e", padx=4, pady=2)
        self.v_start.grid(row=r, column=1, padx=4, pady=2)
        self.lbl_v_stop.grid(row=r, column=2, sticky="e", padx=4, pady=2)
        self.v_stop.grid(row=r, column=3, padx=4, pady=2)
        self.lbl_v_points.grid(row=r, column=4, sticky="e", padx=4, pady=2)
        self.v_points.grid(row=r, column=5, padx=4, pady=2)
        self.lbl_h_fixed.grid(row=r, column=6, sticky="e", padx=4, pady=2)
        self.h_fixed.grid(row=r, column=7, padx=4, pady=2)

        # Hide V-scan group by default
        for w in [self.lbl_v_start, self.v_start, self.lbl_v_stop, self.v_stop,
                  self.lbl_v_points, self.v_points, self.lbl_h_fixed, self.h_fixed]:
            w.grid_remove()

        # Row 2: RF correlation params (unchanged layout)
        r += 1
        ttk.Label(ctrl, text="NO_RUNS").grid(row=r, column=0, sticky="e", padx=4, pady=2)
        self.no_runs = ttk.Entry(ctrl, width=10)
        self.no_runs.insert(0, "200")
        self.no_runs.grid(row=r, column=1, padx=4, pady=2)

        ttk.Label(ctrl, text="RATE").grid(row=r, column=2, sticky="e", padx=4, pady=2)
        self.rate = ttk.Entry(ctrl, width=10)
        self.rate.insert(0, "5")
        self.rate.grid(row=r, column=3, padx=4, pady=2)

        ttk.Label(ctrl, text="NO_BINS").grid(row=r, column=4, sticky="e", padx=4, pady=2)
        self.no_bins = ttk.Entry(ctrl, width=10)
        self.no_bins.insert(0, "100")
        self.no_bins.grid(row=r, column=5, padx=4, pady=2)

        ttk.Label(ctrl, text="TARGET_FREQ (MHz)").grid(row=r, column=6, sticky="e", padx=4, pady=2)
        self.target_freq = ttk.Entry(ctrl, width=10)
        self.target_freq.insert(0, "20.55")
        self.target_freq.grid(row=r, column=7, padx=4, pady=2)

        # Row 3: Window periods and start/stop/save (unchanged layout)
        r += 1
        ttk.Label(ctrl, text="Window periods").grid(row=r, column=0, sticky="e", padx=4, pady=2)
        self.periods = ttk.Entry(ctrl, width=10)
        self.periods.insert(0, "4.0")
        self.periods.grid(row=r, column=1, padx=4, pady=2)

        self.btn_start = ttk.Button(ctrl, text="Start Scan", command=self.start_scan)
        self.btn_start.grid(row=r, column=4, padx=4, pady=2)

        self.btn_stop = ttk.Button(ctrl, text="Stop", command=self.stop_scan)
        self.btn_stop.grid(row=r, column=5, padx=4, pady=2)

        self.btn_save = ttk.Button(ctrl, text="Save Data", command=self.save_data)
        self.btn_save.grid(row=r, column=6, padx=4, pady=2)

        self.status = ttk.Label(ctrl, text="Idle", anchor="w")
        self.status.grid(row=r, column=7, sticky="w", padx=4, pady=2)

        # Figure: amplitude (top), phase (middle), histogram (bottom)
        fig = plt.Figure(figsize=(10, 5), dpi=100)
        gs = fig.add_gridspec(3, 1, height_ratios=[2, 2, 2], hspace=0.35)

        # Amplitude subplot
        self.ax_amp = fig.add_subplot(gs[0, 0])
        self.amp_line, = self.ax_amp.plot([], [], 'o-', label='Amplitude (%)', color='tab:blue')
        self.ax_amp.set_xlabel('H (V)')
        self.ax_amp.set_ylabel('Amplitude (%)')
        self.ax_amp.grid(True)
        self.ax_amp.set_title('RF correlation amplitude vs H')

        # Phase subplot
        self.ax_phase = fig.add_subplot(gs[1, 0])
        self.phase_line, = self.ax_phase.plot([], [], 's--', label='Phase (π rad)', color='tab:orange')
        self.ax_phase.set_xlabel('H (V)')
        self.ax_phase.set_ylabel('Phase (π rad)')
        self.ax_phase.grid(True)
        self.ax_phase.set_title('RF correlation phase vs H')

        # Histogram subplot
        self.ax_hist = fig.add_subplot(gs[2, 0])
        self.hist_line = None
        self.fit_line = None
        self.ax_hist.set_title('Histogram and fit (current H)')
        self.ax_hist.set_xlabel('Time (s)')
        self.ax_hist.set_ylabel('Counts')
        self.ax_hist.grid(True)

        canvas = FigureCanvasTkAgg(fig, master=self)
        canvas.draw()
        canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas = canvas

        # Ensure correct control group + labels at startup for default axis
        self._on_axis_change()

    def _on_axis_change(self):
        # Toggle UI groups based on selected axis
        axis = self.axis_combo.get()
        self.scan_axis = axis
        if axis == 'H':
            # Show H group, hide V group
            for w in [self.lbl_h_start, self.h_start, self.lbl_h_stop, self.h_stop,
                      self.lbl_h_points, self.h_points, self.lbl_v_fixed, self.v_entry]:
                w.grid()
            for w in [self.lbl_v_start, self.v_start, self.lbl_v_stop, self.v_stop,
                      self.lbl_v_points, self.v_points, self.lbl_h_fixed, self.h_fixed]:
                w.grid_remove()
        else:
            # Show V group, hide H group
            for w in [self.lbl_h_start, self.h_start, self.lbl_h_stop, self.h_stop,
                      self.lbl_h_points, self.h_points, self.lbl_v_fixed, self.v_entry]:
                w.grid_remove()
            for w in [self.lbl_v_start, self.v_start, self.lbl_v_stop, self.v_stop,
                      self.lbl_v_points, self.v_points, self.lbl_h_fixed, self.h_fixed]:
                w.grid()
        # Refresh plot axis labels
        self._update_scan_plot()

    def start_scan(self):
        if self.running:
            return
        try:
            axis = self.axis_combo.get()
            # Read range/fixed based on axis
            if axis == 'H':
                h0 = float(self.h_start.get())
                h1 = float(self.h_stop.get())
                npts = int(self.h_points.get())
                self.V = float(self.v_entry.get())
                self.scan_axis = 'H'
                self.scan_vals = np.linspace(h0, h1, npts) if npts > 1 else np.array([h0])
            else:
                v0 = float(self.v_start.get())
                v1 = float(self.v_stop.get())
                npts = int(self.v_points.get())
                self.H = float(self.h_fixed.get())
                self.scan_axis = 'V'
                self.scan_vals = np.linspace(v0, v1, npts) if npts > 1 else np.array([v0])

            runs = int(self.no_runs.get())
            rate = float(self.rate.get())
            nbins = int(self.no_bins.get())
            target_mhz = float(self.target_freq.get())
            periods = float(self.periods.get())
        except ValueError:
            messagebox.showerror("Input Error", "Please check numeric inputs.")
            return

        if npts < 1:
            messagebox.showerror("Input Error", "# points must be >= 1.")
            return

        self.idx = 0
        self.amps_percent = []
        self.phases_pi = []
        self.hist_list = []
        self.edges_list = []
        self.popt_list = []

        # Precompute window_us from periods and target freq (MHz)
        self.window_us = periods / max(target_mhz, 1e-9)

        # Store params
        self.params = dict(
            NO_RUNS=runs, RATE=rate, NO_BINS=nbins,
            TARGET_FREQ_MHZ=target_mhz, WINDOW_US=self.window_us,
            PERIODS=periods, V=self.V, H=self.H
        )

        # Update status/plots
        self.status.config(text="Running...")
        self._update_scan_plot()
        self._update_hist_plot(None, None, None)

        self.running = True
        self._kickoff_step()

    def stop_scan(self):
        self.running = False
        self.status.config(text="Stopping...")

    def _kickoff_step(self):
        if not self.running or self.idx >= len(self.scan_vals):
            self.running = False
            self.status.config(text="Done" if self.idx >= len(self.scan_vals) else "Stopped")
            return

        current = self.scan_vals[self.idx]
        if self.scan_axis == 'H':
            H_val = float(current)
            V_val = float(self.V)
            self.status.config(text=f"Scanning H={H_val:.4f}  ({self.idx+1}/{len(self.scan_vals)})")
        else:
            H_val = float(self.H)
            V_val = float(current)
            self.status.config(text=f"Scanning V={V_val:.4f}  ({self.idx+1}/{len(self.scan_vals)})")

        # Removed: DAC move on the UI thread (it can block the UI)
        # try:
        #     self.dac.dc_min_shift(H_val, V_val)
        # except Exception as e:
        #     print("DAC error:", e)

        runs = self.params["NO_RUNS"]
        rate = self.params["RATE"]
        nbins = self.params["NO_BINS"]
        target_mhz = self.params["TARGET_FREQ_MHZ"]
        window_us = self.params["WINDOW_US"]

        def _worker(h_val=H_val, v_val=V_val):
            # Perform DAC move in worker thread to keep UI responsive
            try:
                self.dac.dc_min_shift(h_val, v_val)
            except Exception as e:
                print("DAC error:", e)

            # Early exit if Stop pressed before correlation
            if not self.running:
                self.after(0, lambda: self.status.config(text="Stopped"))
                return

            try:
                popt, hist, edges = self.qutau.RF_correlation(
                    runs, rate, nbins, target_freq_mhz=target_mhz, window_us=window_us
                )
                if len(popt) == 0 or hist is None or len(hist) == 0:
                    amp_norm = float('nan')
                    phase_pi = float('nan')
                else:
                    mean_counts = float(np.mean(hist)) if len(hist) else float('nan')
                    amp_norm = (popt[0] / mean_counts) if (np.isfinite(mean_counts) and mean_counts > 0) else float('nan')
                    phase_pi = popt[2] / np.pi
                result = dict(popt=popt, hist=hist, edges=edges,
                              amp_percent=amp_norm * 100.0 if np.isfinite(amp_norm) else np.nan,
                              phase_pi=phase_pi)
            except Exception as e:
                print("RF_correlation error:", e)
                result = dict(popt=[], hist=np.array([]), edges=np.array([]),
                              amp_percent=np.nan, phase_pi=np.nan)

            # If stopped during/after correlation, do not queue next step
            if not self.running:
                self.after(0, lambda: self.status.config(text="Stopped"))
                return

            self.after(0, lambda: self._on_step_done(result))

        self.worker = threading.Thread(target=_worker, daemon=True)
        self.worker.start()

    def _on_step_done(self, result):
        # Append results
        self.amps_percent.append(result["amp_percent"])
        self.phases_pi.append(result["phase_pi"])
        self.hist_list.append(np.array(result["hist"]))
        self.edges_list.append(np.array(result["edges"]))
        self.popt_list.append(np.array(result["popt"]))

        # Update plots
        self._update_scan_plot()
        self._update_hist_plot(result["hist"], result["edges"], result["popt"])

        self.idx += 1
        # Queue next
        if self.running:
            self.after(50, self._kickoff_step)
        else:
            self.status.config(text="Stopped")

    def _update_scan_plot(self):
        X_sofar = self.scan_vals[:len(self.amps_percent)]
        self.amp_line.set_data(X_sofar, self.amps_percent)
        self.phase_line.set_data(X_sofar, self.phases_pi)

        # Dynamic labels/titles
        self.ax_amp.set_xlabel(f'{self.scan_axis} (V)')
        self.ax_phase.set_xlabel(f'{self.scan_axis} (V)')
        self.ax_amp.set_title(f'RF correlation amplitude vs {self.scan_axis}')
        self.ax_phase.set_title(f'RF correlation phase vs {self.scan_axis}')

        if len(X_sofar) > 0:
            xmin, xmax = np.min(self.scan_vals), np.max(self.scan_vals)
            self.ax_amp.set_xlim(xmin, xmax)
            self.ax_phase.set_xlim(xmin, xmax)

            yA = np.array(self.amps_percent, dtype=float)
            if np.isfinite(yA).any():
                ymin = np.nanmin(yA); ymax = np.nanmax(yA)
                if np.isfinite(ymin) and np.isfinite(ymax):
                    if ymin == ymax:
                        ymin -= 1.0; ymax += 1.0
                    margin = 0.05 * abs(ymax - ymin)
                    self.ax_amp.set_ylim(ymin - margin, ymax + margin)

            yP = np.array(self.phases_pi, dtype=float)
            if np.isfinite(yP).any():
                pmin = np.nanmin(yP); pmax = np.nanmax(yP)
                if np.isfinite(pmin) and np.isfinite(pmax):
                    if pmin == pmax:
                        pmin -= 0.1; pmax += 0.1
                    pmargin = 0.05 * abs(pmax - pmin)
                    self.ax_phase.set_ylim(pmin - pmargin, pmax + pmargin)

        self.ax_amp.legend([self.amp_line], [self.amp_line.get_label()], loc="best")
        self.ax_phase.legend([self.phase_line], [self.phase_line.get_label()], loc="best")

        self.canvas.draw_idle()

    def _update_hist_plot(self, hist, edges, popt):
        self.ax_hist.cla()
        self.ax_hist.grid(True)
        # Make title reflect the current scan axis
        self.ax_hist.set_title(f'Histogram and fit (current {self.scan_axis})')
        self.ax_hist.set_xlabel('Time')
        self.ax_hist.set_ylabel('Counts')

        if hist is None or edges is None or len(hist) == 0 or len(edges) < 2:
            self.canvas.draw_idle()
            return

        centers = (edges[:-1] + edges[1:]) / 2.0
        # Plot histogram bars from counts
        self.ax_hist.hist(centers, bins=edges, weights=hist, label='Data', alpha=0.7)

        # Poissonian error bars: sigma = sqrt(N)
        try:
            yerr = np.sqrt(hist)
            # Overlay error bars at bin centers
            self.ax_hist.errorbar(centers, hist, yerr=yerr, fmt='.', color='k', capsize=2, label='Poissonian error')
        except Exception as e:
            print("Poissonian error calc error:", e)

        if popt is not None and len(popt) >= 4 and np.all(np.isfinite(popt[:4])):
            try:
                self.ax_hist.plot(centers, sine_wave_local(centers, *popt[:4]), label='Fit')
            except Exception as e:
                print("Fit plot error:", e)

        self.ax_hist.legend(loc='best')
        self.canvas.draw_idle()

    def save_data(self):
        if len(self.amps_percent) == 0:
            messagebox.showinfo("Save Data", "No data to save yet.")
            return

        base = filedialog.asksaveasfilename(
            title="Save scan data (base name)",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
        )
        if not base:
            return

        axis_label = self.scan_axis

        # Summary CSV
        try:
            with open(base, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow([axis_label, "Amplitude_percent", "Phase_pi"])
                for i, x in enumerate(self.scan_vals[:len(self.amps_percent)]):
                    amp = self.amps_percent[i] if i < len(self.amps_percent) else np.nan
                    ph = self.phases_pi[i] if i < len(self.phases_pi) else np.nan
                    w.writerow([x, amp, ph])
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to write CSV: {e}")
            return

        base_root = os.path.splitext(base)[0]

        # Fit parameters CSV
        popt_path = base_root + "_popt.csv"
        try:
            max_popt_len = max((len(p) if hasattr(p, "__len__") else 0) for p in self.popt_list) if self.popt_list else 0
            with open(popt_path, 'w', newline='') as f:
                w = csv.writer(f)
                header = [axis_label, "Amplitude_percent", "Phase_pi"] + [f"popt_{i}" for i in range(max_popt_len)]
                w.writerow(header)
                for i, x in enumerate(self.scan_vals[:len(self.amps_percent)]):
                    popt = np.array(self.popt_list[i]).ravel() if i < len(self.popt_list) and len(np.atleast_1d(self.popt_list[i])) > 0 else np.array([])
                    row = [
                        x,
                        self.amps_percent[i] if i < len(self.amps_percent) else np.nan,
                        self.phases_pi[i] if i < len(self.phases_pi) else np.nan,
                    ]
                    row += [popt[j] if j < len(popt) else "" for j in range(max_popt_len)]
                    w.writerow(row)
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to write fit CSV: {e}")
            return

        # Histograms CSV (long format)
        hist_path = base_root + "_hist.csv"
        try:
            with open(hist_path, 'w', newline='') as f:
                w = csv.writer(f)
                # Add Poissonian error column
                w.writerow(["step", axis_label, "bin", "edge_left", "edge_right", "center", "count", "count_err_poisson"])
                steps = len(self.hist_list)
                for i in range(steps):
                    x = self.scan_vals[i] if i < len(self.scan_vals) else np.nan
                    hist = np.asarray(self.hist_list[i]).astype(float) if i < len(self.hist_list) else np.array([])
                    edges = np.asarray(self.edges_list[i]).astype(float) if i < len(self.edges_list) else np.array([])
                    if hist.size == 0 or edges.size < 2:
                        continue
                    centers = (edges[:-1] + edges[1:]) / 2.0

                    # Compute Poissonian errors per bin: sigma = sqrt(N)
                    err = np.sqrt(hist)

                    for b in range(len(hist)):
                        w.writerow([i, x, b, edges[b], edges[b+1], centers[b], hist[b], err[b]])
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to write histogram CSV: {e}")
            return

        messagebox.showinfo("Save Data", f"Saved:\n{base}\n{popt_path}\n{hist_path}")


if __name__ == "__main__":
    app = RFScanApp()
    app.mainloop()