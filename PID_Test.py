# Trap Drive Board GUI: scan -> choose lock range -> enable PID -> live plots (last 5 min)
# All serial I/O at 9600 baud; every method opens/closes its own handle.
# Requires: PyQt5, pyqtgraph, pyserial

import sys, time, struct, csv, os
from datetime import datetime
from collections import deque
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg

import tkinter as tk
from tkinter import ttk
from adriq.Trap_RF_Board import *
import multiprocessing as mp



# Helper to run the PyQt LiveApp in a separate process
def _run_qt_liveapp(sample_ms=200):
    # client created inside LiveApp now
    app = QtWidgets.QApplication(sys.argv)
    w = Trap_RF_Lock_App(sample_ms=sample_ms)
    w.show()
    sys.exit(app.exec_())

# ---- main ----
if __name__ == "__main__":
    # Start or restart the Trap_Drive_Board server (listens on port 9009)
    port_arg = "COM7" if len(sys.argv) < 2 else sys.argv[1]
    Server.master(Trap_Drive_Board, 5, port_arg)

    # Launch the PyQt LiveApp in a separate process
    qt_proc = mp.Process(target=_run_qt_liveapp, args=(200,), daemon=True)
    qt_proc.start()

    # Start the Tk app with the simple trap control widget
    root = tk.Tk()
    root.title("Trap Depth Control (Tk)")
    widget = TrapControlWidget(root)
    widget.pack(fill="both", expand=True, padx=8, pady=8)
    try:
        root.mainloop()
    finally:
        if qt_proc.is_alive():
            qt_proc.terminate()
