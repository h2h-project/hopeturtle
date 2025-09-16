#!/usr/bin/env python3
"""
HopeTurtle GPS one-shot logger
Logs one GPS snapshot to CSV and appends a JSON export prototype
suited for later upload to the HopeTurtle server.

Default: Read GPS via software-serial on a spare GPIO using pigpio
(so the full UART /dev/serial0 can be used by the SIM900 modem).

Set via environment variables (see Section 2).
Always exits with code 0 so the systemd timer remains green.
"""

# ============================================================
# (1) Imports & Setup
# ============================================================
import os, sys, time, json, csv
from datetime import datetime, timezone

# ============================================================
# (2) Configuration & Environment Variables
# ============================================================
MODE = os.getenv("HT_GPS_MODE", "soft").lower()   # "soft" (default) or "hard"
SOFT_RX_PIN = int(os.getenv("HT_GPS_SOFT_RX", "17"))  # GPIO pin for GPS TX -> Pi RX
DEFAULT_HARD_PORT = "/dev/ttyS0"                       # mini-UART
GPS_PORT = os.getenv("HT_GPS_PORT", DEFAULT_HARD_PORT)
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
# ============================================================
def dm_to_deg(dm: str, hemi: str):
    """Convert NMEA ddmm.mmmm / dddmm.mmmm to signed decimal degrees."""
    if not dm:
        return None
    if hemi in ("N", "S"):
        d, m = int(dm[:2]), float(dm[2:])
    else:
        d, m = int(dm[:3]), float(dm[3:])
    val = d + m / 60.0
    return -val if hemi in ("S", "W") else val

def parse_rmc_time_date(r_time: str, r_date: str):
    """Build UTC datetime from RMC hhmmss(.sss), ddmmyy; return None if invalid."""
    try:
        if not r_time or not r_date:
            return None
        hh, mm, ss = int(r_time[0:2]), int(r_time[2:4]), int(r_time[4:6])
        dd, MM, yy = int(r_date[0:2]), int(r_date[2:4]), int(r_date[4:6])
        year = 2000 + yy if yy < 80 else 1900 + yy
        return datetime(year, MM, dd, hh, mm, ss, tzinfo=timezone.utc)
    except Exception:
        return None

def write_row(csv_path, write_header, row):
    """Append one CSV row; create header if file was new."""
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(row)

def safe_now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def truncate(val, ndigits=6):
    """Truncate floats safely to ndigits (default 6)."""
    try:
        return round(float(val), ndigits)
    except Exception:
        return val

# ============================================================
# (4) GPS Read Functions
# ============================================================
def read_nmea_lines_soft(baud: int, window_s: int, rx_pin: int):
    lines = []
    try:
        import pigpio
    except ImportError as e:
        return lines, f"error_soft_serial:missing_pigpio:{e}"

    pi = pigpio.pi()
    if not pi.connected:
        return lines, "error_soft_serial:pigpiod_not_connected"

    try:
        pi.set_mode(rx_pin, pigpio.INPUT)
        pi.bb_serial_read_open(rx_pin, baud, 8)
    except Exception as e:
        pi.stop()
        return lines, f"error_soft_serial:open_failed:{e}"

    t0 = time.time()
    buf = b""
    try:
        while time.time() - t0 < window_s:
            n, data = pi.bb_serial_read(rx_pin)
            if n > 0:
                buf += data
                *complete, buf = buf.split(b"\n")
                for raw in complete:
                    line = raw.decode("ascii", errors="ignore").strip()
                    if line:
                        lines.append(line)
            else:
                time.sleep(0.02)
    finally:
        try:
            pi.bb_serial_read_close(rx_pin)
        except Exception:
            pass
        pi.stop()

    return lines, None

def read_nmea_lines_hard(port: str, baud: int, window_s: int):
    lines = []
    try:
        import serial
    except ImportError as e:
        return lines, f"error_hard_serial:missing_pyserial:{e}"

    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        return lines, f"error_open_serial:{e}"

    t0 = time.time()
    try:
        while time.time() - t0 < window_s:
            try:
                line = ser.readline().decode("ascii", errors="ignore").strip()
            except Exception as e:
                ser.close()
                return lines, f"error_read_serial:{e}"
            if line:
                lines.append(line)
            else:
                time.sleep(0.02)
    finally:
        ser.close()

    return lines, None

# ============================================================
# (5) Parse NMEA
# ============================================================
def parse_nmea_to_row(nmea_lines):
    lat = lon = alt = hdop = None
    sats = fixq = None
    speed_kmh = course_deg = None
    r_date = r_time = ""
    gps_dt = None
    had_nmea = False
    fix_status = "no_fix"

    for line in nmea_lines:
        if not line.startswith("$"):
            continue
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
                try:
                    fixq = int(p[6]) if p[6] else 0
                except Exception:
                    fixq = 0
                try:
                    sats = int(p[7]) if p[7] else None
                except Exception:
                    sats = None
                hdop = float(p[8]) if p[8] else None
                alt = float(p[9]) if p[9] else None

        if fix_status == "fix":
            break

    # Timestamp
    if gps_dt and fix_status == "fix":
        ts = gps_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        status = "fix"
    elif datetime.now(timezone.utc).year > 2020:
        ts = safe_now_utc_str()
        status = "system_time_no_fix" if had_nmea else "system_time_no_nmea"
    else:
        ts = ""
        status = "no_time"

    row = {
        "timestamp_utc": ts,
        "lat": truncate(lat),
        "lon": truncate(lon),
        "alt_m": truncate(alt),
        "sats": sats or "",
        "hdop": truncate(hdop, 2),
        "speed_kmh": truncate(speed_kmh, 3),
        "course_deg": truncate(course_deg, 1),
        "fix_quality": fixq or 0,
        "raw_date_utc": r_date,
        "raw_time_utc": r_time,
        "status": status,
    }
    return row

# ============================================================
# (6) Main
# ============================================================
def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path = os.path.join(DATA_DIR, f"{today}_gps.csv")
    write_header = not os.path.exists(csv_path)

    # Read
    if MODE == "soft":
        nmea_lines, err = read_nmea_lines_soft(BAUD, READ_WINDOW_S, SOFT_RX_PIN)
        source_note = f"softGPIO{SOFT_RX_PIN}"
    else:
        nmea_lines, err = read_nmea_lines_hard(GPS_PORT, BAUD, READ_WINDOW_S)
        source_note = GPS_PORT

    # Error
    if err:
        ts = safe_now_utc_str()
        row = {k: "" for k in CSV_FIELDS}
        row.update({"timestamp_utc": ts, "fix_quality": 0, "status": err})
        write_row(csv_path, write_header, row)
        json_path = os.path.join(DATA_DIR, "JSON_export_prototype.txt")
        json_record = {
            "turtle_id": "HT-0001",
            "device_id": "pi-zero-2",
            "source": source_note,
            "fix": row
        }
        with open(json_path, "a") as jf:
            jf.write(json.dumps(json_record) + "\n")
        print(f"[WARN] GPS read failed ({err}) via {source_note} -> CSV+JSON saved")
        return 0

    # Parse
    row = parse_nmea_to_row(nmea_lines)
    write_row(csv_path, write_header, row)

    # JSON
    json_path = os.path.join(DATA_DIR, "JSON_export_prototype.txt")
    json_record = {
        "turtle_id": "HT-0001",
        "device_id": "pi-zero-2",
        "source": source_note,
        "sats": row.get("sats", ""),
        "fix": row
    }
    with open(json_path, "a") as jf:
        jf.write(json.dumps(json_record) + "\n")

    # Console
    ts = row["timestamp_utc"] or "(NO_TIME)"
    if row["status"] == "fix":
        print(f"Logged FIX: {ts} lat={row['lat']} lon={row['lon']} sats={row['sats']} -> CSV+JSON saved (GPS:{source_note})")
    else:
        print(f"Logged {row['status'].upper()}: {ts} -> CSV+JSON saved (GPS:{source_note})")

    return 0

# ============================================================
# (7) Entrypoint
# ============================================================
if __name__ == "__main__":
    sys.exit(main())
