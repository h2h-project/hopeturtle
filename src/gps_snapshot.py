#!/usr/bin/env python3
"""
HopeTurtle GPS one-shot logger
- Reads NMEA from /dev/serial0 (NEO-6M/8M default 9600 baud)
- Appends one CSV row to ~/hopeturtle/data/YYYY-MM-DD_gps.csv
- Always exits 0 so systemd timers don't show failures when no fix yet

Env overrides:
  HT_SERIAL_PORT  (default: /dev/serial0)
  HT_BAUD         (default: 9600)
  HT_DATA_DIR     (default: ~/hopeturtle/data)
  HT_READ_WINDOW_S (default: 12)   # seconds to wait for sentences
"""
import csv
import os
import sys
import time
from datetime import datetime, timezone

try:
    import serial  # from python3-serial
except ImportError:
    print("[ERR] pyserial not installed. Run: sudo apt install -y python3-serial", file=sys.stderr)
    sys.exit(0)  # still exit 0 to keep systemd green; log makes the issue obvious

PORT = os.getenv("HT_SERIAL_PORT", "/dev/serial0")
BAUD = int(os.getenv("HT_BAUD", "9600"))
READ_WINDOW_S = int(os.getenv("HT_READ_WINDOW_S", "12"))
DATA_DIR = os.path.expanduser(os.getenv("HT_DATA_DIR", "~/hopeturtle/data"))

CSV_FIELDS = [
    "timestamp_utc", "lat", "lon", "alt_m", "sats", "hdop",
    "speed_kmh", "course_deg", "fix_quality", "raw_date_utc", "raw_time_utc", "status"
]

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

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path = os.path.join(DATA_DIR, f"{today}_gps.csv")
    write_header = not os.path.exists(csv_path)

    # Try to open serial
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except Exception as e:
        # Log an empty/no-fix row so we keep cadence + have error breadcrumbs
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = {
            "timestamp_utc": ts, "lat": "", "lon": "", "alt_m": "",
            "sats": "", "hdop": "", "speed_kmh": "", "course_deg": "",
            "fix_quality": 0, "raw_date_utc": "", "raw_time_utc": "",
            "status": f"error_open_serial:{e}"
        }
        with open(csv_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if write_header:
                w.writeheader()
            w.writerow(row)
        print(f"[WARN] Could not open {PORT} @ {BAUD}: {e}")
        return 0  # Always exit 0

    # Read NMEA for a short window
    t0 = time.time()
    lat = lon = alt = hdop = None
    sats = fixq = None
    speed_kmh = course_deg = None
    r_date = r_time = ""
    had_nmea = False

    while time.time() - t0 < READ_WINDOW_S:
        try:
            line = ser.readline().decode("ascii", errors="ignore").strip()
        except Exception as e:
            print(f"[WARN] Serial read failed: {e}")
            break
        if not line.startswith("$"):
            continue
        had_nmea = True

        if line.startswith(("$GPRMC", "$GNRMC")):
            p = line.split(",")
            # $..RMC: time(1), status(2), lat(3), N/S(4), lon(5), E/W(6), speed_kn(7), course(8), date(9)
            if len(p) >= 10:
                r_time, status, r_date = p[1], p[2], p[9]
                if status == "A":  # valid fix
                    lat = dm_to_deg(p[3], p[4])
                    lon = dm_to_deg(p[5], p[6])
                    speed_kmh = float(p[7]) * 1.852 if p[7] else None
                    course_deg = float(p[8]) if p[8] else None

        elif line.startswith(("$GPGGA", "$GNGGA")):
            p = line.split(",")
            # $..GGA: time(1), lat(2), N/S(3), lon(4), E/W(5), fix(6), sats(7), hdop(8), alt(9)
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

        if lat is not None and lon is not None:
            break  # we have a usable position

    ser.close()

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = "fix" if (lat is not None and lon is not None) else ("no_nmea" if not had_nmea else "no_fix")

    row = {
        "timestamp_utc": ts,
        "lat": lat if lat is not None else "",
        "lon": lon if lon is not None else "",
        "alt_m": alt if alt is not None else "",
        "sats": sats if sats is not None else "",
        "hdop": hdop if hdop is not None else "",
        "speed_kmh": round(speed_kmh, 3) if speed_kmh is not None else "",
        "course_deg": course_deg if course_deg is not None else "",
        "fix_quality": fixq if fixq is not None else 0,
        "raw_date_utc": r_date,
        "raw_time_utc": r_time,
        "status": status,
    }

    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(row)

    # Clear, human-friendly console line
    if status == "fix":
        print(f"Logged FIX: {ts} lat={row['lat']} lon={row['lon']} sats={row['sats']} hdop={row['hdop']}")
    else:
        print(f"Logged {status.upper()}: {ts} (no valid position yet)")

    return 0  # <-- always succeed for systemd

if __name__ == "__main__":
    sys.exit(main())
