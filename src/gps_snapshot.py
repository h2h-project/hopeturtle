#!/usr/bin/env python3
"""
HopeTurtle: take one GPS reading and append to today's CSV.
Works directly from /dev/serial0 (NEO-6M/8M default 9600 baud).

CSV columns:
timestamp_utc, lat, lon, alt_m, sats, hdop, speed_kmh, course_deg, fix_quality, raw_date_utc, raw_time_utc
"""
import csv, os, time, sys
from datetime import datetime, timezone
import serial

PORT = os.getenv("HT_SERIAL_PORT", "/dev/serial0")
BAUD = int(os.getenv("HT_BAUD", "9600"))
READ_WINDOW_S = int(os.getenv("HT_READ_WINDOW_S", "12"))  # how long to wait for sentences
DATA_DIR = os.getenv("HT_DATA_DIR", "/home/pi/hope-turtle-code/data")

def dm_to_deg(dm: str, hemi: str):
    if not dm: return None
    if hemi in ("N","S"):
        d, m = int(dm[:2]), float(dm[2:])
    else:
        d, m = int(dm[:3]), float(dm[3:])
    v = d + m/60.0
    return -v if hemi in ("S","W") else v

def main() -> int:
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path = os.path.join(DATA_DIR, f"{today}_gps.csv")
    write_header = not os.path.exists(csv_path)

    # Open GPS
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except Exception as e:
        print(f"[ERR] open serial failed: {e}", file=sys.stderr)
        return 2

    # Read for up to READ_WINDOW_S to gather a fix
    t0 = time.time()
    lat = lon = alt = hdop = None
    sats = fixq = None
    speed_kmh = course_deg = None
    r_date = r_time = ""

    while time.time() - t0 < READ_WINDOW_S:
        try:
            line = ser.readline().decode("ascii", errors="ignore").strip()
        except Exception as e:
            print(f"[ERR] read failed: {e}", file=sys.stderr); break
        if not line.startswith("$"): 
            continue

        if line.startswith(("$GPRMC", "$GNRMC")):
            p = line.split(",")
            # $..RMC: time(1), status(2), lat(3), N/S(4), lon(5), E/W(6), speed_kn(7), course(8), date(9)
            if len(p) >= 10:
                r_time, status, r_date = p[1], p[2], p[9]
                if status == "A":  # valid
                    lat = dm_to_deg(p[3], p[4])
                    lon = dm_to_deg(p[5], p[6])
                    speed_kmh = float(p[7])*1.852 if p[7] else None
                    course_deg = float(p[8]) if p[8] else None

        elif line.startswith(("$GPGGA", "$GNGGA")):
            p = line.split(",")
            # $..GGA: time(1), lat(2), N/S(3), lon(4), E/W(5), fix(6), sats(7), hdop(8), alt(9)
            if len(p) >= 10:
                try: fixq = int(p[6]) if p[6] else 0
                except: fixq = 0
                try: sats = int(p[7]) if p[7] else None
                except: sats = None
                hdop = float(p[8]) if p[8] else None
                alt = float(p[9]) if p[9] else None

        if lat is not None and lon is not None:
            break  # got usable position

    ser.close()

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    }

    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header: w.writeheader()
        w.writerow(row)

    print("Logged:", row)
    return 0 if (lat is not None and lon is not None) else 1

if __name__ == "__main__":
    sys.exit(main())
