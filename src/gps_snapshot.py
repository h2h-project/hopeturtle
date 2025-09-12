#!/usr/bin/env python3
"""
HopeTurtle GPS one-shot logger
Logs one GPS snapshot to CSV and also appends a JSON export prototype
that can later be sent to the HopeTurtle server.
"""

# ============================================================
# (1) Imports & Setup
# Standard libraries for time, file handling, etc.
# ============================================================
import csv, os, sys, time, json
from datetime import datetime, timezone

try:
    import serial  # pyserial library for UART access
except ImportError:
    print("[ERR] pyserial not installed. Run: sudo apt install -y python3-serial", file=sys.stderr)
    sys.exit(0)  # exit 0 so systemd doesn’t mark failure


# ============================================================
# (2) Configuration & Environment Variables
# Allows overrides from environment (set in systemd service).
# ============================================================
PORT = os.getenv("HT_SERIAL_PORT", "/dev/serial0")
BAUD = int(os.getenv("HT_BAUD", "9600"))
READ_WINDOW_S = int(os.getenv("HT_READ_WINDOW_S", "12"))
DATA_DIR = os.path.expanduser(os.getenv("HT_DATA_DIR", "~/hopeturtle/data"))

CSV_FIELDS = [
    "timestamp_utc", "lat", "lon", "alt_m", "sats", "hdop",
    "speed_kmh", "course_deg", "fix_quality", "raw_date_utc",
    "raw_time_utc", "status"
]


# ============================================================
# (3) Helper Functions
# Converting GPS formats, parsing time/date, etc.
# ============================================================
def dm_to_deg(dm: str, hemi: str):
    """Convert NMEA ddmm.mmmm to signed decimal degrees."""
    if not dm: return None
    if hemi in ("N", "S"):
        d, m = int(dm[:2]), float(dm[2:])
    else:
        d, m = int(dm[:3]), float(dm[3:])
    val = d + m / 60.0
    return -val if hemi in ("S", "W") else val

def parse_rmc_time_date(r_time: str, r_date: str):
    """Parse RMC sentence time/date into a Python datetime (UTC)."""
    try:
        if not r_time or not r_date: return None
        hh, mm, ss = int(r_time[0:2]), int(r_time[2:4]), int(r_time[4:6])
        dd, MM, yy = int(r_date[0:2]), int(r_date[2:4]), int(r_date[4:6])
        year = 2000 + yy if yy < 80 else 1900 + yy
        return datetime(year, MM, dd, hh, mm, ss, tzinfo=timezone.utc)
    except Exception:
        return None


# ============================================================
# (4) Main Logging Function
# Reads NMEA data, extracts fields, logs CSV + JSON prototype.
# ============================================================
def main():
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path = os.path.join(DATA_DIR, f"{today}_gps.csv")
    write_header = not os.path.exists(csv_path)

    # ---- Open serial port ----
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except Exception as e:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = {k: "" for k in CSV_FIELDS}
        row.update({"timestamp_utc": ts, "fix_quality": 0, "status": f"error_open_serial:{e}"})
        with open(csv_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if write_header: w.writeheader()
            w.writerow(row)
        print(f"[WARN] Could not open {PORT}: {e}")
        return 0

    # ---- Read NMEA sentences for a short window ----
    t0 = time.time()
    lat = lon = alt = hdop = None
    sats = fixq = None
    speed_kmh = course_deg = None
    r_date = r_time = ""
    gps_dt = None
    had_nmea = False
    fix_status = "no_fix"

    while time.time() - t0 < READ_WINDOW_S:
        try:
            line = ser.readline().decode("ascii", errors="ignore").strip()
        except Exception as e:
            print(f"[WARN] Serial read failed: {e}")
            break
        if not line.startswith("$"): continue
        had_nmea = True

        if line.startswith(("$GPRMC", "$GNRMC")):
            p = line.split(",")
            if len(p) >= 10:
                r_time, status, r_date = p[1], p[2], p[9]
                gps_dt = parse_rmc_time_date(r_time, r_date)
                if status == "A":  # Active fix
                    lat = dm_to_deg(p[3], p[4])
                    lon = dm_to_deg(p[5], p[6])
                    speed_kmh = float(p[7]) * 1.852 if p[7] else None
                    course_deg = float(p[8]) if p[8] else None
                    fix_status = "fix"

        elif line.startswith(("$GPGGA", "$GNGGA")):
            p = line.split(",")
            if len(p) >= 10:
                fixq = int(p[6]) if p[6] else 0
                sats = int(p[7]) if p[7] else None
                hdop = float(p[8]) if p[8] else None
                alt = float(p[9]) if p[9] else None

        if fix_status == "fix":
            break

    ser.close()

    # ---- Choose timestamp source ----
    if gps_dt and fix_status == "fix":
        ts = gps_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        status = "fix"
    elif datetime.now(timezone.utc).year > 2020:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        status = "system_time_no_fix" if had_nmea else "system_time_no_nmea"
    else:
        ts = ""
        status = "no_time"

    # ---- Prepare row ----
    row = {
        "timestamp_utc": ts,
        "lat": lat or "",
        "lon": lon or "",
        "alt_m": alt or "",
        "sats": sats or "",
        "hdop": hdop or "",
        "speed_kmh": round(speed_kmh,3) if speed_kmh else "",
        "course_deg": course_deg or "",
        "fix_quality": fixq or 0,
        "raw_date_utc": r_date,
        "raw_time_utc": r_time,
        "status": status,
    }

    # ---- Write CSV ----
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header: w.writeheader()
        w.writerow(row)

    # ============================================================
    # (5) JSON Export Prototype
    # Build JSON record, append to JSON_export_prototype.txt
    # ============================================================
    json_record = {
        "turtle_id": "HT-0001",     # TODO: replace with config
        "device_id": "pi-zero-xyz", # TODO: replace with real ID
        "fix": row
    }

    json_path = os.path.join(DATA_DIR, "JSON_export_prototype.txt")
    with open(json_path, "a") as jf:
        jf.write(json.dumps(json_record) + "\n")

    # ---- Console feedback ----
    if status == "fix":
        print(f"Logged FIX: {ts} lat={row['lat']} lon={row['lon']} -> CSV+JSON saved")
    else:
        print(f"Logged {status.upper()}: {ts if ts else '(NO_TIME)'} -> CSV+JSON saved")

    return 0


# ============================================================
# (6) Entrypoint
# Ensures script runs cleanly under systemd (always exits 0).
# ============================================================
if __name__ == "__main__":
    sys.exit(main())
