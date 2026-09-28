import csv
import os
import re
import subprocess
import time
from datetime import datetime

# CONFIGURATION
TARGET_IP = "8.8.8.8"
CSV_FILE = "ping_log.csv"
INTERVAL_SECONDS = 1  # Time to wait between pings
DURATION_MINUTES = 5  # Total time to run the script


def get_ping_latency(target):
    """Sends a single ping and parses the response latency in ms."""
    try:
        # Determine the correct flag based on the OS (Windows uses -n, Unix uses -c)
        flag = "-n" if os.name == "nt" else "-c"

        # Execute a single ping command
        output = subprocess.check_output(
            ["ping", flag, "1", target],
            shell=False,
            text=True,
            stderr=subprocess.DEVNULL,
        )

        # Regex to extract time value (e.g., 'time=24ms' or 'time=24.5 ms')
        match = re.search(r"time[=<]([\d.]+)\s*ms", output, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return "Timeout"  # Found no match or packet dropped

    except subprocess.CalledProcessError:
        return "Timeout"  # Host unreachable or packet dropped


def main():
    # Write CSV header if the file does not already exist
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["date", "time (hh:mm:ss)", "ping"])

    print(f"Starting ping monitoring for {TARGET_IP}...")
    print(f"Logging data to '{CSV_FILE}' every {INTERVAL_SECONDS}s.")
    print("Press Ctrl+C to stop manually.")

    start_time = time.time()
    end_time = start_time + (DURATION_MINUTES * 60)

    try:
        while time.time() < end_time:
            loop_start = time.time()

            # Capture current date, time, and latency
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M:%S")
            latency = get_ping_latency(TARGET_IP)

            # Append data to the CSV
            with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([date_str, time_str, latency])

            print(f"[{date_str} {time_str}] Latency: {latency} ms")

            # Maintain strict interval timing by factoring in execution time
            elapsed = time.time() - loop_start
            sleep_time = max(0, INTERVAL_SECONDS - elapsed)
            time.sleep(sleep_time)

        print(f"\nMonitoring complete. Data saved to {CSV_FILE}.")

    except KeyboardInterrupt:
        print(f"\nMonitoring stopped by user. Data saved to {CSV_FILE}.")


if __name__ == "__main__":
    main()
