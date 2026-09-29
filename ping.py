import csv
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from PyQt5.QtCore import QObject, QPointF, QRectF, QRunnable, QThreadPool, QTimer, pyqtSignal, pyqtSlot, Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QAction, QApplication, QComboBox, QDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QMainWindow, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget
)

TARGET_IP = "8.8.8.8"
CSV_FILE = "ping_log.csv"
INTERVAL_MS = 1000

class PingWorkerSignals(QObject):
    result = pyqtSignal(str, str, object)

class PingWorker(QRunnable):
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
            flag_count = "-n" if os.name == "nt" else "-c"
            flag_timeout = "-w" if os.name == "nt" else "-W"
            timeout_val = "1000" if os.name == "nt" else "1"

            output = subprocess.check_output(
                ["ping", flag_count, "1", flag_timeout, timeout_val, self.target],
                shell=False, text=True, stderr=subprocess.DEVNULL
            )
            match = re.search(r"time[=<]([\d.]+)\s*ms", output, re.IGNORECASE)
            latency = float(match.group(1)) if match else "Timeout"
        except Exception:
            latency = "Timeout"

        file_exists = os.path.isfile(CSV_FILE)
        try:
            with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["date", "time (hh:mm:ss)", "ping"])
                writer.writerow([date_str, time_str, latency])
        except IOError:
            pass

        self.signals.result.emit(date_str, time_str, latency)

class LogCanvas(QWidget):
    """Custom canvas using QPainter to plot latency over time."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.records = []
        self.setMinimumHeight(350)
        self.setStyleSheet("background-color: #1e1e1e;")

    def set_data(self, records):
        self.records = records
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 65
        margin_right = 30
        margin_top = 25
        margin_bottom = 55

        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom

        # Background
        painter.fillRect(0, 0, w, h, QColor("#1e1e1e"))

        if not self.records or plot_w <= 10 or plot_h <= 10:
            painter.setPen(QColor("#777777"))
            painter.setFont(QFont("Arial", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, "No ping entries to display in this range.")
            return

        # Calculate Y scale (max ping, minimum 60ms baseline for aesthetics)
        numeric_pings = [r["ping"] for r in self.records if isinstance(r["ping"], (int, float))]
        max_ping = max(numeric_pings) if numeric_pings else 60.0
        max_y = max(60.0, max_ping * 1.15)

        # Draw Grid & Y-Axis Labels
        painter.setFont(QFont("Arial", 9))
        grid_steps = 4
        for i in range(grid_steps + 1):
            y_val = (max_y / grid_steps) * i
            y_pos = margin_top + plot_h - (y_val / max_y) * plot_h

            painter.setPen(QPen(QColor("#333333"), 1, Qt.DashLine))
            painter.drawLine(int(margin_left), int(y_pos), int(w - margin_right), int(y_pos))

            painter.setPen(QColor("#888888"))
            painter.drawText(QRectF(0, y_pos - 8, margin_left - 10, 16), Qt.AlignRight | Qt.AlignVCenter, f"{int(y_val)} ms")

        # Plot Axes
        painter.setPen(QPen(QColor("#555555"), 1))
        painter.drawLine(int(margin_left), int(margin_top), int(margin_left), int(margin_top + plot_h))
        painter.drawLine(int(margin_left), int(margin_top + plot_h), int(w - margin_right), int(margin_top + plot_h))

        n = len(self.records)
        step_x = plot_w / max(1, n - 1) if n > 1 else plot_w

        # Draw Points, Connections, and Timeouts
        line_path = QPainterPath()
        started_path = False
        points_to_draw = []

        for i, r in enumerate(self.records):
            x = margin_left + (i * step_x if n > 1 else plot_w / 2)
            val = r["ping"]

            if isinstance(val, (int, float)):
                y = margin_top + plot_h - (val / max_y) * plot_h
                if not started_path:
                    line_path.moveTo(x, y)
                    started_path = True
                else:
                    line_path.lineTo(x, y)
                points_to_draw.append((x, y, val))
            else:
                # Timeout visual representation
                started_path = False
                painter.setPen(QPen(QColor("#e74c3c"), 1.2, Qt.DashLine))
                painter.drawLine(int(x), int(margin_top), int(x), int(margin_top + plot_h))
                painter.fillRect(QRectF(x - 3, margin_top + plot_h - 6, 6, 6), QBrush(QColor("#e74c3c")))

        # Render Ping Curve
        painter.setPen(QPen(QColor("#3498db"), 2))
        painter.drawPath(line_path)

        # Render Nodes with Color Hierarchy
        for x, y, val in points_to_draw:
            if val < 45:
                pt_color = QColor("#2ecc71")
            elif val <= 120:
                pt_color = QColor("#f1c40f")
            else:
                pt_color = QColor("#e67e22")

            painter.setBrush(QBrush(pt_color))
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawEllipse(QPointF(x, y), 3.5, 3.5)

        # Draw X-Axis Time Labels (stride to avoid overcrowding)
        painter.setPen(QColor("#999999"))
        painter.setFont(QFont("Arial", 8))
        label_stride = max(1, n // 6)
        for i in range(0, n, label_stride):
            x = margin_left + (i * step_x if n > 1 else plot_w / 2)
            rec = self.records[i]
            
            # Show "MM-DD\nHH:MM:SS" or just time based on length
            lbl_text = f"{rec['date'][-5:]}\n{rec['time']}"
            painter.drawText(QRectF(x - 40, margin_top + plot_h + 8, 80, 35), Qt.AlignHCenter | Qt.AlignTop, lbl_text)


class GraphWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ping Telemetry Graph")
        self.resize(780, 520)
        self.parent_ref = parent
        layout = QVBoxLayout(self)

        # Control Panel
        controls_layout = QHBoxLayout()

        lbl_filter = QLabel("Filter:")
        self.combo_filter = QComboBox()
        self.combo_filter.addItems([
            "All Records",
            "This Session Only",
            "Today Only",
            "Last 1 Hour",
            "Last 15 Minutes",
            "Last 5 Minutes"
        ])
        self.combo_filter.currentIndexChanged.connect(self.refresh_graph)

        lbl_sort = QLabel("Order:")
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["Chronological (Old → New)", "Reverse Chronological (New → Old)"])
        self.combo_sort.currentIndexChanged.connect(self.refresh_graph)

        controls_layout.addWidget(lbl_filter)
        controls_layout.addWidget(self.combo_filter)
        controls_layout.addSpacing(15)
        controls_layout.addWidget(lbl_sort)
        controls_layout.addWidget(self.combo_sort)
        controls_layout.addStretch()

        # Legend
        lbl_legend = QLabel("🟢 <45ms  🟡 45-120ms  🔴 >120ms / Timeout")
        lbl_legend.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        controls_layout.addWidget(lbl_legend)
        layout.addLayout(controls_layout)

        # Canvas Widget
        self.canvas = LogCanvas(self)
        layout.addWidget(self.canvas)

        self.refresh_graph()

    def refresh_graph(self):
        if not self.parent_ref:
            return

        records = self.parent_ref.all_records[:]
        filter_mode = self.combo_filter.currentText()
        now = datetime.now()

        # Filtering logic
        if filter_mode == "This Session Only":
            records = [r for r in records if r["is_session"]]
        elif filter_mode == "Today Only":
            today_str = now.strftime("%Y-%m-%d")
            records = [r for r in records if r["date"] == today_str]
        elif filter_mode in ["Last 1 Hour", "Last 15 Minutes", "Last 5 Minutes"]:
            delta_map = {
                "Last 5 Minutes": timedelta(minutes=5),
                "Last 15 Minutes": timedelta(minutes=15),
                "Last 1 Hour": timedelta(hours=1)
            }
            cutoff = now - delta_map[filter_mode]
            records = [r for r in records if r["dt"] and r["dt"] >= cutoff]

        # Sorting logic
        reverse_order = (self.combo_sort.currentIndex() == 1)
        records.sort(key=lambda x: x["dt"] if x["dt"] else datetime.min, reverse=reverse_order)

        self.canvas.set_data(records)


class LogWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ping Logs Context")
        self.resize(650, 480)
        self.parent_ref = parent
        layout = QVBoxLayout(self)

        controls_layout = QHBoxLayout()
        lbl_sort = QLabel("Sort:")
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["Reverse Chronological (Newest)", "Chronological (Oldest)"])
        self.combo_sort.currentIndexChanged.connect(self.refresh_table_view)

        lbl_filter = QLabel("Filter:")
        self.combo_filter = QComboBox()
        self.combo_filter.addItems([
            "All Records",
            "This Session Only",
            "Today Only",
            "Last 1 Hour",
            "Timeouts Only"
        ])
        self.combo_filter.currentIndexChanged.connect(self.refresh_table_view)

        controls_layout.addWidget(lbl_sort)
        controls_layout.addWidget(self.combo_sort)
        controls_layout.addSpacing(15)
        controls_layout.addWidget(lbl_filter)
        controls_layout.addWidget(self.combo_filter)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Date", "Time (HH:MM:SS)", "Ping (ms)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        
        self.refresh_table_view()

    def refresh_table_view(self):
        if not self.parent_ref:
            return

        records = self.parent_ref.all_records[:]
        filter_mode = self.combo_filter.currentText()
        now = datetime.now()

        if filter_mode == "This Session Only":
            records = [r for r in records if r["is_session"]]
        elif filter_mode == "Today Only":
            today_str = now.strftime("%Y-%m-%d")
            records = [r for r in records if r["date"] == today_str]
        elif filter_mode == "Last 1 Hour":
            cutoff = now - timedelta(hours=1)
            records = [r for r in records if r["dt"] and r["dt"] >= cutoff]
        elif filter_mode == "Timeouts Only":
            records = [r for r in records if r["ping"] == "Timeout"]

        reverse_order = (self.combo_sort.currentIndex() == 0)
        records.sort(key=lambda x: x["dt"] if x["dt"] else datetime.min, reverse=reverse_order)

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(records))
        for row_idx, r in enumerate(records):
            item_date = QTableWidgetItem(r["date"])
            item_time = QTableWidgetItem(r["time"])
            item_ping = QTableWidgetItem(str(r["ping"]))

            item_date.setTextAlignment(Qt.AlignCenter)
            item_time.setTextAlignment(Qt.AlignCenter)
            item_ping.setTextAlignment(Qt.AlignCenter)

            self.table.setItem(row_idx, 0, item_date)
            self.table.setItem(row_idx, 1, item_time)
            self.table.setItem(row_idx, 2, item_ping)

        self.table.setUpdatesEnabled(True)

    def append_live_row(self):
        self.refresh_table_view()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Live Monitor - Pinging {TARGET_IP}")
        self.resize(650, 310)
        self.threadpool = QThreadPool()
        self.start_dt = datetime.now()
        self.start_time_str = self.start_dt.strftime("%H:%M:%S")
        self.log_window = None
        self.graph_window = None

        self.all_records = []
        self.load_historical_csv()

        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.trigger_ping_worker)
        self.timer.start(INTERVAL_MS)
        self.trigger_ping_worker()

    def load_historical_csv(self):
        if not os.path.isfile(CSV_FILE):
            return
        try:
            with open(CSV_FILE, mode="r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            if len(rows) <= 1:
                return

            data_rows = rows[1:] if "date" in rows[0][0].lower() else rows
            for r in data_rows:
                if len(r) < 3:
                    continue
                date_str, time_str, val_str = r[0].strip(), r[1].strip(), r[2].strip()
                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dt = None

                ping_val = float(val_str) if val_str.replace('.', '', 1).isdigit() else "Timeout"
                self.all_records.append({
                    "dt": dt,
                    "date": date_str,
                    "time": time_str,
                    "ping": ping_val,
                    "is_session": False
                })
        except Exception as e:
            print(f"Error loading historical CSV: {e}")

    def init_ui(self):
        # Toolbar with side-by-side table & graph options
        toolbar = self.addToolBar("Logs Navigation")
        
        open_logs_action = QAction("📋 Open Log Table", self)
        open_logs_action.triggered.connect(self.open_log_window)
        toolbar.addAction(open_logs_action)

        open_graph_action = QAction("📈 Open Log Graph", self)
        open_graph_action.triggered.connect(self.open_graph_window)
        toolbar.addAction(open_graph_action)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Average Range Selector
        filter_bar = QHBoxLayout()
        lbl_avg_scope = QLabel("Average Calculation Range:")
        lbl_avg_scope.setStyleSheet("color: #cccccc; font-weight: bold; font-size: 12px;")
        
        self.combo_avg_scope = QComboBox()
        self.combo_avg_scope.addItems([
            "Session Only (Default)",
            "All Time (Entire CSV History)",
            "Last 1 Minute",
            "Last 5 Minutes",
            "Last 15 Minutes",
            "Last 1 Hour",
            "Today Only"
        ])
        self.combo_avg_scope.currentIndexChanged.connect(self.recalculate_average)

        filter_bar.addWidget(lbl_avg_scope)
        filter_bar.addWidget(self.combo_avg_scope)
        filter_bar.addStretch()
        main_layout.addLayout(filter_bar)

        # Metrics Panels
        metrics_layout = QHBoxLayout()

        self.left_frame = QFrame()
        self.left_frame.setStyleSheet("background-color: #2b2b2b; border-radius: 8px; padding: 10px;")
        left_layout = QVBoxLayout(self.left_frame)
        lbl_curr_title = QLabel("CURRENT PING")
        lbl_curr_title.setStyleSheet("color: #aaaaaa; font-weight: bold;")
        self.lbl_current = QLabel("Initializing...")
        self.lbl_current.setFont(QFont("Arial", 28, QFont.Bold))
        self.lbl_current.setStyleSheet("color: #ffffff;")
        left_layout.addWidget(lbl_curr_title)
        left_layout.addWidget(self.lbl_current)

        self.right_frame = QFrame()
        self.right_frame.setStyleSheet("background-color: #2b2b2b; border-radius: 8px; padding: 10px;")
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

        self.lbl_time_info = QLabel(f"Session Frame Info | Start: {self.start_time_str}  →  Latest Update: Waiting...")
        self.lbl_time_info.setStyleSheet("color: #888888; font-size: 11px; margin-top: 5px;")
        main_layout.addWidget(self.lbl_time_info)

    def trigger_ping_worker(self):
        worker = PingWorker(TARGET_IP)
        worker.signals.result.connect(self.update_metrics_ui)
        self.threadpool.start(worker)

    @pyqtSlot(str, str, object)
    def update_metrics_ui(self, date_str, time_str, latency):
        now = datetime.now()
        self.lbl_time_info.setText(f"Session Frame Info | Start: {self.start_time_str}  →  Latest Update: {time_str}")

        record = {
            "dt": now,
            "date": date_str,
            "time": time_str,
            "ping": latency,
            "is_session": True
        }
        self.all_records.append(record)

        if latency == "Timeout":
            self.lbl_current.setText("Timeout")
            self.lbl_current.setStyleSheet("color: #ff3333;")
        else:
            self.lbl_current.setText(f"{latency} ms")
            self.lbl_current.setStyleSheet(self.get_color_style(latency))

        self.recalculate_average()

        if self.log_window and self.log_window.isVisible():
            self.log_window.append_live_row()

        if self.graph_window and self.graph_window.isVisible():
            self.graph_window.refresh_graph()

    def recalculate_average(self):
        scope = self.combo_avg_scope.currentText()
        now = datetime.now()
        target_pings = []

        if scope == "Session Only (Default)":
            target_pings = [r["ping"] for r in self.all_records if r["is_session"] and isinstance(r["ping"], (int, float))]
        elif scope == "All Time (Entire CSV History)":
            target_pings = [r["ping"] for r in self.all_records if isinstance(r["ping"], (int, float))]
        elif scope == "Today Only":
            today_str = now.strftime("%Y-%m-%d")
            target_pings = [r["ping"] for r in self.all_records if r["date"] == today_str and isinstance(r["ping"], (int, float))]
        elif scope in ["Last 1 Minute", "Last 5 Minutes", "Last 15 Minutes", "Last 1 Hour"]:
            minutes_map = {
                "Last 1 Minute": 1,
                "Last 5 Minutes": 5,
                "Last 15 Minutes": 15,
                "Last 1 Hour": 60
            }
            cutoff = now - timedelta(minutes=minutes_map[scope])
            target_pings = [
                r["ping"] for r in self.all_records
                if r["dt"] and r["dt"] >= cutoff and isinstance(r["ping"], (int, float))
            ]

        if target_pings:
            avg_val = sum(target_pings) / len(target_pings)
            self.lbl_average.setText(f"{avg_val:.1f} ms")
            self.lbl_average.setStyleSheet(self.get_color_style(avg_val))
        else:
            self.lbl_average.setText("N/A")
            self.lbl_average.setStyleSheet("color: #888888;")

    def get_color_style(self, ms_val):
        if ms_val < 45:
            return "color: #2ecc71;"
        elif ms_val <= 120:
            return "color: #f1c40f;"
        else:
            return "color: #e74c3c;"

    def open_log_window(self):
        if not self.log_window:
            self.log_window = LogWindow(self)
        else:
            self.log_window.refresh_table_view()
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def open_graph_window(self):
        if not self.graph_window:
            self.graph_window = GraphWindow(self)
        else:
            self.graph_window.refresh_graph()
        self.graph_window.show()
        self.graph_window.raise_()
        self.graph_window.activateWindow()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())