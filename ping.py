import csv
import os
import re
import subprocess
import sys
from datetime import datetime
from PyQt5.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# CONFIGURATION
TARGET_IP = "8.8.8.8"
CSV_FILE = "ping_log.csv"
INTERVAL_MS = 1000  # 1 second between pings


class PingWorkerSignals(QObject):
    """Signals to communicate ping results back to the main UI thread."""

    result = pyqtSignal(str, str, object)  # date, time, latency (float or "Timeout")


class PingWorker(QRunnable):
    """Worker thread tasked with firing the native ping command without freezing the UI."""

    def __init__(self, target):
        super().__init__()
        self.target = target
        self.signals = PingWorkerSignals()

    @pyqtSlot()
    def run(self):
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        try:
            flag = "-n" if os.name == "nt" else "-c"
            output = subprocess.check_output(
                ["ping", flag, "1", self.target],
                shell=False,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            match = re.search(r"time[=<]([\d.]+)\s*ms", output, re.IGNORECASE)
            latency = float(match.group(1)) if match else "Timeout"
        except Exception:
            latency = "Timeout"

        # Append immediately to CSV file
        file_exists = os.path.isfile(CSV_FILE)
        try:
            with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["date", "time (hh:mm:ss)", "ping"])
                writer.writerow([date_str, time_str, latency])
        except IOError:
            pass  # Fail gracefully if file is temporarily locked

        self.signals.result.emit(date_str, time_str, latency)


class LogWindow(QDialog):
    """Secondary pop-up window containing historical log data rendered inside a clean table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ping Logs Context")
        self.resize(500, 400)

        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Date", "Time (HH:MM:SS)", "Ping (ms)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        self.load_csv_data()

    def load_csv_data(self):
        if not os.path.isfile(CSV_FILE):
            return

        try:
            with open(CSV_FILE, mode="r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            if not rows:
                return

            # Skip header row if it matches schema strings
            data_rows = (
                rows[1:] if rows[0] and "date" in rows[0][0].lower() else rows
            )

            self.table.setRowCount(len(data_rows))
            for row_idx, row_data in enumerate(data_rows):
                for col_idx, value in enumerate(row_data):
                    item = QTableWidgetItem(value)
                    self.table.setItem(row_idx, col_idx, item)

            self.table.scrollToBottom()
        except Exception as e:
            print(f"Error parsing log file: {e}")


class MainWindow(QMainWindow):
    """Primary application interface monitoring connection metrics."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Live Monitor - Pinging {TARGET_IP}")
        self.resize(550, 260)

        self.threadpool = QThreadPool()
        self.valid_pings = []
        self.start_time = datetime.now().strftime("%H:%M:%S")

        self.init_ui()

        # Timer setup to coordinate non-blocking worker threads
        self.timer = QTimer()
        self.timer.timeout.connect(self.trigger_ping_worker)
        self.timer.start(INTERVAL_MS)

        # Trigger first metric collection instantly
        self.trigger_ping_worker()

    def init_ui(self):
        # Toolbar setup
        toolbar = self.addToolBar("Logs Navigation")
        open_logs_action = QAction("📋 Open Log Table", self)
        open_logs_action.triggered.connect(self.open_log_window)
        toolbar.addAction(open_logs_action)

        # Core central widgets layout layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Dashboard layout split
        metrics_layout = QHBoxLayout()

        # Left display container (Current Latency)
        self.left_frame = QFrame()
        self.left_frame.setStyleSheet(
            "background-color: #2b2b2b; border-radius: 8px; padding: 10px;"
        )
        left_layout = QVBoxLayout(self.left_frame)
        lbl_curr_title = QLabel("CURRENT PING")
        lbl_curr_title.setStyleSheet("color: #aaaaaa; font-weight: bold;")
        self.lbl_current = QLabel("Initializing...")
        self.lbl_current.setFont(QFont("Arial", 28, QFont.Bold))
        self.lbl_current.setStyleSheet("color: #ffffff;")
        left_layout.addWidget(lbl_curr_title)
        left_layout.addWidget(self.lbl_current)

        # Right display container (Session Average)
        self.right_frame = QFrame()
        self.right_frame.setStyleSheet(
            "background-color: #2b2b2b; border-radius: 8px; padding: 10px;"
        )
        right_layout = QVBoxLayout(self.right_frame)
        lbl_avg_title = QLabel("AVERAGE PING")
        lbl_avg_title.setStyleSheet("color: #aaaaaa; font-weight: bold;")
        self.lbl_average = QLabel("0.0 ms")
        self.lbl_average.setFont(QFont("Arial", 28, QFont.Bold))
        self.lbl_average.setStyleSheet("color: #ffffff;")
        right_layout.addWidget(lbl_avg_title)
        right_layout.addWidget(self.lbl_average)

        metrics_layout.addWidget(self.left_frame)
        metrics_layout.addWidget(self.right_frame)
        main_layout.addLayout(metrics_layout)

        # Footer window session timing references
        self.lbl_time_info = QLabel(
            f"Session Frame Info | Start: {self.start_time}  →  Latest Update: Waiting..."
        )
        self.lbl_time_info.setStyleSheet(
            "color: #666666; font-size: 11px; margin-top: 5px;"
        )
        main_layout.addWidget(self.lbl_time_info)

    def trigger_ping_worker(self):
        worker = PingWorker(TARGET_IP)
        worker.signals.result.connect(self.update_metrics_ui)
        self.threadpool.start(worker)

    @pyqtSlot(str, str, object)
    def update_metrics_ui(self, date_str, time_str, latency):
        # Construct updated timestamps label string
        self.lbl_time_info.setText(
            f"Session Frame Info | Start: {self.start_time}  →  Latest Update: {time_str}"
        )

        # Handle dropped packets context
        if latency == "Timeout":
            self.lbl_current.setText("Timeout")
            self.lbl_current.setStyleSheet("color: #ff3333;")  # Pure Red Alert
            return

        # Handle successful calculations sequence loop
        self.lbl_current.setText(f"{latency} ms")
        self.valid_pings.append(latency)

        # Re-tally moving rolling standard average matrix
        avg_latency = sum(self.valid_pings) / len(self.valid_pings)
        self.lbl_average.setText(f"{avg_latency:.1f} ms")

        # Color spectrum classification hierarchy bounds checking
        # Green (< 45ms) -> Yellow (45ms - 120ms) -> Red (> 120ms)
        def get_color_style(ms_val):
            if ms_val < 45:
                return "color: #2ecc71;"  # Green
            elif ms_val <= 120:
                return "color: #f1c40f;"  # Yellow
            else:
                return "color: #e74c3c;"  # Red

        self.lbl_current.setStyleSheet(get_color_style(latency))
        self.lbl_average.setStyleSheet(get_color_style(avg_latency))

    def open_log_window(self):
        dialog = LogWindow(self)
        dialog.exec_()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
