#!/usr/bin/env python3
"""
HopeTurtle OLED Status Display
- Shows short status messages or a 5s swimming animation on a 0.96" I2C SSD1306.
- NEW: "distance" command shows km from last valid GPS fix to Al Mawasi (configurable).
- NEW: "brief" command shows last fix coords, sats, and km to Mawasi.
- Fails gracefully if OLED or libraries are missing (prints to stdout, exits 0).

Usage:
  python3 oled_status.py boot-waking
  python3 oled_status.py boot-alive
  python3 oled_status.py gps-searching
  python3 oled_status.py swim
  python3 oled_status.py distance
  python3 oled_status.py brief
"""

import os, sys, time, traceback, glob, csv, math
from datetime import datetime, timezone

# ---------- Config ----------
DATA_DIR = os.path.expanduser(os.getenv("HT_DATA_DIR", "~/hopeturtle/data"))

# Default reference: Al Mawasi, Gaza Strip (approx)
REF_LAT = float(os.getenv("HT_REF_LAT", "31.283"))
REF_LON = float(os.getenv("HT_REF_LON", "34.234"))

# Beta testing: YES = messages persist until overridden, NO = auto-clear after hold_s
BETA_TEST_MODE = os.getenv("HT_OLED_BETA", "YES").upper()

def _init_device():
    try:
        from luma.core.interface.serial import i2c
        from luma.oled.device import ssd1306
        serial = i2c(port=1, address=0x3C)
        return ssd1306(serial)
    except Exception as e:
        print(f"[OLED] Not available: {e.__class__.__name__}: {e}")
        return None

def _prep_canvas(device):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("1", (device.width, device.height), 0)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except Exception:
        font = ImageFont.load_default()
    return img, draw, font

def _show_lines(device, lines, hold_s=2.5, center=False):
    """Render up to 5 lines of short text."""
    if device is None:
        print("[OLED] (simulated) " + " | ".join([str(x) for x in lines]))
        time.sleep(hold_s)
        return
    from PIL import Image
    img, draw, font = _prep_canvas(device)
    W, H = device.width, device.height
    line_h = 14
    total_h = len(lines) * line_h
    y0 = (H - total_h)//2 if center else 0
    for i, t in enumerate(lines[:5]):
        if not isinstance(t, str):  # safety
            t = str(t)
        l, t0, r, b = draw.textbbox((0,0), t, font=font)
        w, h = r - l, b - t0
        x = (W - w)//2 if center else 0
        draw.text((x, y0 + i*line_h), t, fill=1, font=font)
    device.display(img)
    if BETA_TEST_MODE == "NO":
        time.sleep(hold_s)

def _clear(device):
    if device is None:
        return
    from PIL import Image
    img = Image.new("1", (device.width, device.height), 0)
    device.display(img)

def _swim_animation(device, duration_s=5.0, fps=12):
    frames = [
        [
            "   _________    ____ ",
            "  /           \\ |  o |",
            " |            |/ ___\\|",
            " |____________|_/    ",
            "   |__|  |__|        ",
        ],
        [
            "   _________    ____ ",
            "  /           \\ |  o |",
            " |            |/ ___\\|",
            " |____________|_/    ",
            "   |_  |__|  _|      ",
        ],
    ]
    if device is None:
        print("[OLED] (simulated) swimming turtle for 5s…")
        time.sleep(duration_s)
        return
    from PIL import Image, ImageDraw
    W, H = device.width, device.height
    start = time.time()
    x = -20
    dx = 3
    frame_i = 0
    while time.time() - start < duration_s:
        img = Image.new("1", (W, H), 0)
        draw = ImageDraw.Draw(img)
        sprite = frames[frame_i % len(frames)]
        sy = H//2 - len(sprite)//2
        for row_idx, row in enumerate(sprite):
            for col_idx, ch in enumerate(row):
                if ch not in (" ",):
                    px = x + col_idx
                    py = sy + row_idx
                    if 0 <= px < W and 0 <= py < H:
                        draw.point((px, py), 1)
        device.display(img)
        time.sleep(1.0/fps)
        frame_i += 1
        x += dx
        if x > W:
            x = -len(sprite[0])
    _clear(device)

# ---------- Distance helpers ----------
def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def _find_last_fix_from_csvs(data_dir: str):
    files = sorted(glob.glob(os.path.join(data_dir, "*_gps.csv")), key=os.path.getmtime, reverse=True)
    for fp in files:
        try:
            rows = list(csv.DictReader(open(fp)))
            for row in reversed(rows):
                if (row.get("status") or "").lower() == "fix" and row.get("lat") and row.get("lon"):
                    return fp, row.get("timestamp_utc"), float(row["lat"]), float(row["lon"]), row.get("sats") or "?"
        except Exception:
            continue
    return None, None, None, None, None

def _show_last_distance(device):
    fp, ts, lat, lon, sats = _find_last_fix_from_csvs(DATA_DIR)
    if not fp:
        _show_lines(device, ["No last fix", "found"], hold_s=3, center=True)
        return
    km = _haversine_km(lat, lon, REF_LAT, REF_LON)
    lines = [f"{km:.1f} km → Mawasi", f"({lat:.3f},{lon:.3f})", f"Sats: {sats}", ts]
    _show_lines(device, lines, hold_s=4, center=True)

def _show_brief(device):
    fp, ts, lat, lon, sats = _find_last_fix_from_csvs(DATA_DIR)
    if not fp:
        _show_lines(device, ["No fix yet", "Check GPS..."], hold_s=3, center=True)
        return
    km = _haversine_km(lat, lon, REF_LAT, REF_LON)
    lines = [f"{lat:.3f},{lon:.3f}", f"{km:.1f} km → Mawasi", f"Sats: {sats}"]
    _show_lines(device, lines, hold_s=4, center=True)

# ---------- Main ----------
def main():
    if len(sys.argv) < 2:
        print("Usage: oled_status.py [boot-waking|boot-alive|gps-searching|swim|distance|brief]")
        return 0
    device = _init_device()
    cmd = sys.argv[1].lower()
    try:
        if cmd == "boot-waking":
            _show_lines(device, ["Hope Turtle", "is waking up!"], hold_s=3, center=True)
        elif cmd == "boot-alive":
            _show_lines(device, ["Hope Turtle", "is alive!"], hold_s=3, center=True)
        elif cmd == "gps-searching":
            _show_lines(device, ["GPS:", "Searching satellites…"], hold_s=3, center=True)
        elif cmd == "swim":
            _swim_animation(device)
        elif cmd == "distance":
            _show_last_distance(device)
        elif cmd == "brief":
            _show_brief(device)
        else:
            _show_lines(device, [f"Unknown cmd:", cmd], hold_s=2, center=True)
    except Exception:
        traceback.print_exc()
    finally:
        if BETA_TEST_MODE == "NO":
            _clear(device)
    return 0

if __name__ == "__main__":
    sys.exit(main())
