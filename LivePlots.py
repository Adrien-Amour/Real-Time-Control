import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPushButton
)
from PyQt5.QtCore import QTimer
from adriq.Rigol_Oscilloscope import ScopePlotter, ScopeReader
from adriq.Counters import PMT_Reader, QuTau_Reader, LivePlotter
from Lock_App import PIDApp
from adriq.Trap_RF_Board import Trap_RF_Lock_App

class PMTQuTauOscilloscopePage(QWidget):
    def __init__(self, parent_tabs=None, tab_index=None):
        super().__init__()
        self.parent_tabs = parent_tabs
        self.tab_index = tab_index
        main_layout = QVBoxLayout()

        # Top row: PMT and QuTau plotters side by side
        top_row = QHBoxLayout()
        self.plotter1 = LivePlotter(PMT_Reader)
        self.plotter2 = LivePlotter(QuTau_Reader)
        square_size = 500

        self.plotter1.setFixedSize(square_size, square_size)
        self.plotter2.setFixedSize(square_size, square_size)
        top_row.addWidget(self.plotter1)
        top_row.addWidget(self.plotter2)

        # --- Add Reopen Plotters Button ---
        self.reopen_button = QPushButton("Reopen Plotters (refresh whole page)")
        self.reopen_button.setStyleSheet("font-size: 14pt; padding: 8px; background-color: orange; color: black;")
        self.reopen_button.clicked.connect(self.reopen_plotters)
        main_layout.addLayout(top_row)
        main_layout.addWidget(self.reopen_button)

        # Bottom row: Oscilloscope plotter spanning both columns
        self.osc_plotter = ScopePlotter(ScopeReader)
        self.osc_plotter.setFixedSize(2 * square_size, int(0.8 * square_size))

        main_layout.addWidget(self.osc_plotter)
        self.setLayout(main_layout)

    def _teardown(self):
        """Best-effort stop of any timers/threads inside child widgets.

        This prevents multiple LivePlotter poll loops lingering after refresh,
        which can make QuTau reads and stdout feel progressively slower.
        """
        # Stop any QTimers under this page (LivePlotter commonly uses QTimer).
        for timer in self.findChildren(QTimer):
            try:
                timer.stop()
            except Exception:
                pass

        # Best-effort stop/close on known child plotters.
        for w in (getattr(self, "plotter1", None), getattr(self, "plotter2", None), getattr(self, "osc_plotter", None)):
            if w is None:
                continue
            for method_name in ("stop", "shutdown", "close"):
                method = getattr(w, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass

    def closeEvent(self, event):
        self._teardown()
        super().closeEvent(event)

    def reopen_plotters(self):
        # Refresh the entire page by replacing the tab with a new instance
        if self.parent_tabs is not None and self.tab_index is not None:
            old_page = self.parent_tabs.widget(self.tab_index)

            # Remove the tab first (Qt does not delete the widget on removeTab).
            self.parent_tabs.removeTab(self.tab_index)

            # Stop any polling loops in the old page, then schedule deletion.
            if old_page is not None:
                try:
                    if hasattr(old_page, "_teardown"):
                        old_page._teardown()
                except Exception:
                    pass
                try:
                    old_page.setParent(None)
                except Exception:
                    pass
                try:
                    old_page.deleteLater()
                except Exception:
                    pass

            new_page = PMTQuTauOscilloscopePage(self.parent_tabs, self.tab_index)
            self.parent_tabs.insertTab(self.tab_index, new_page, "PMT/QuTau/Oscilloscope")
            self.parent_tabs.setCurrentIndex(self.tab_index)

class LockAppPage(PIDApp):
    def __init__(self):
        super().__init__()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LivePlots - Multi Page App")
        self.setGeometry(100, 100, 1100, 1000)

        tabs = QTabWidget()
        # Pass reference and index to the page
        pmt_page = PMTQuTauOscilloscopePage(tabs, 0)
        tabs.addTab(pmt_page, "PMT/QuTau/Oscilloscope")
        tabs.addTab(LockAppPage(), "Lock App")  # bugs out if not on channel 'c'
        # --- New third page: Trap drive lock app ---
        tabs.addTab(Trap_RF_Lock_App(sample_ms=200), "Trap Drive Lock")

        self.setCentralWidget(tabs)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())