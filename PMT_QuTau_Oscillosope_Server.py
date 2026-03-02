from adriq.Counters import *
from adriq.Servers import *
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFrame
from PyQt5.QtCore import QTimer
import sys

# Import your oscilloscope plotter and reader
from adriq.Rigol_Oscilloscope import ScopePlotter, ScopeReader
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = QMainWindow()
    main_window.setWindowTitle("PMT Reader Live Counts")

    # Create the main widget and main vertical layout
    central_widget = QWidget()
    main_layout = QVBoxLayout()

    # --- Top row: PMT and QuTau plotters side by side ---
    top_row = QHBoxLayout()
    plotter1 = LivePlotter(PMT_Reader)
    plotter2 = LivePlotter(QuTau_Reader)
    square_size = 500  # Define the desired square size

    plotter1.setFixedSize(square_size, square_size)
    plotter2.setFixedSize(square_size, square_size)
    top_row.addWidget(plotter1)
    top_row.addWidget(plotter2)

    # --- Bottom row: Oscilloscope plotter spanning both columns ---
    osc_plotter = ScopePlotter(ScopeReader)
    osc_plotter.setFixedSize(2 * square_size, int(0.8*square_size))

    # Add layouts and widgets to the main layout
    main_layout.addLayout(top_row)
    main_layout.addWidget(osc_plotter)

    # Set layout to the central widget
    central_widget.setLayout(main_layout)
    main_window.setCentralWidget(central_widget)

    # Set main window size
    main_window.setFixedSize(2 * square_size, int(1.8 * square_size))

    main_window.show()
    sys.exit(app.exec_())