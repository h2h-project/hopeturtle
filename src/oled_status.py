#!/usr/bin/env python3
"""
HopeTurtle OLED Status Display
- Shows messages & simple animations on a 0.96" SSD1306 I2C OLED.
- Commands: boot-waking, boot-alive, gps-searching, swim, distance, brief,
            notify-install, notify-update
- Fails gracefully if OLED or libs are missing (prints to stdout, exits 0).

BETA MODE:
- Set BETA_FLAG below to "YES" to keep messages on-screen until the next message.
- Set to "NO" to auto-clear after 5 seconds.
- You can also override via environment variable HT_OLED_BETA=YES|NO.
"""

import os, sys, time, traceback, glob, csv, math
from datetime import datetime, timezone

# ---------- Beta Toggle (edit here) ----------
BETA_FLAG = "YES"   # <--- change to "YES" to keep messages up until next update
BETA_TESTING = (os.getenv("HT_OLED_BETA", BETA_FLAG).upper() == "YES")

# ---------- Config ----------
DATA_DIR = os.path.expanduser(os.getenv("HT_DATA_DIR", "~/hopeturtle/data"))
# Default reference: Al Mawasi, Gaza Strip (approx)
REF_LAT = float(os.getenv("HT_REF_LAT", "31.283"))
REF_LON = float(os.getenv("HT_REF_LON", "34.234"))

def _init_device():
    try:
        from luma.core.interface.serial import i2c
        from luma.oled.device import ssd1306
        serial = i2c(port=1, address=0x3C)  # common address
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

def _show_lines(device, lines, center=False):
    """
    Render up to 5 short lines. Behavior:
      - BETA=YES  -> draw and return (no sleep, no clear; persists)
      - BETA=NO   -> draw, sleep 5s, then (main) clears
    """
    hold_s = 0 if BETA_TESTING else 5.0

    if device is None:
        print("[OLED] (simulated) " + " | ".join(str(l) for l in lines))
        if hold_s:
            time.sleep(hold_s)
        return

    from PIL import Image
    img, draw, font = _prep_canvas(device)
    W, H = device.width, device.height
    line_h = 14
    total_h = min(len(lines), 5) * line_h
    y0 = (H - total_h)//2 if center else 0
    for i, t in enumerate(lines[:5]):
        t = str(t)
        l, t0, r, b = draw.textbbox((0,0), t, font=font)
        w, h = r - l, b - t0
        x = (W - w)//2 if center else 0
        draw.text((x, y0 + i*line_h), t, fill=1, font=font)
    device.display(img)
    if hold_s:
        time.sleep(hold_s)

def _clear(device):
    if device is None:
        return
    from PIL import Image
    img = Image.new("1", (device.width, device.height), 0)
    device.display(img)

def _swim_animation(device, duration_s=5.0, fps=2):
    """
    Swim animation using HopeTurtle ASCII.
    BETA=YES: leaves last frame up (no clear).
    BETA=NO : clears (via main) after returning.
    """
    frames = [
        [
            "      ___________    _____",
            "  /               \\ |  o  |",
            " |                |/   __\\|",
            " |  _______________  /    ",
            "   |_|_|     |_|_|          ",
        ],
        [
            "      ___________    _____",
            "  /               \\ |  o  |",
            " |                |/   __\\|",
            " |  _______________  /    ",
            "   |_  |_|     |_|  _|     ",
        ],
    ]

    if device is None:
        print("[OLED] (simulated) swimming turtle…")
        time.sleep(duration_s)
        return

    from PIL import Image, ImageDraw
    W, H = device.width, device.height
    start = time.time()
    frame_i = 0
    last_img = None
    while time.time() - start < duration_s:
        img = Image.new("1", (W, H), 0)
        draw = ImageDraw.Draw(img)
        sprite = frames[frame_i % len(frames)]
        sy = H//2 - len(sprite)//2
        y = sy
        for row in sprite:
            draw.text((0, y), row, fill=1)
            y += 10
        device.display(img)
        last_img = img
        time.sleep(1.0/fps)
        frame_i += 1
    if not BETA_TESTING:
        # main() will clear; we do nothing here
        pass
    else:
        # Leave last frame visible
        if last_img is not None:
            device.display(last_img)

# ---------- Distance helpers ----------
def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def _find_last_fix_from_csvs(data_dir: str):
    files = sorted(glob.glob(os.path.join(data_dir, "*_gps.csv")), key=os.path.getmtime, reverse=True)
    for fp in files:
        try:
            with open(fp, "r", newline="") as f:
                rows = list(csv.DictReader(f))
            for row in reversed(rows):
                status = (row.get("status") or "").lower()
                lat = row.get("lat") or ""
                lon = row.get("lon") or ""
                if status == "fix" and lat and lon:
                    ts = row.get("timestamp_utc") or ""
                    return fp, ts, float(lat), float(lon), row.get("sats") or "?"
        except Exception as e:
            print(f"[OLED] Could not parse {fp}: {e}")
            continue
    return None, None, None, None, None

def _show_last_distance(device):
    fp, ts, lat, lon, _ = _find_last_fix_from_csvs(DATA_DIR)
    if not fp:
        _show_lines(device, ["No last fix", "found in data/"], center=True)
        return
    try:
        km = _haversine_km(lat, lon, REF_LAT, REF_LON)
    except Exception as e:
        _show_lines(device, ["Fix parse error", str(e)], center=True)
        return
    _show_lines(device, [
        "Last FIX → Mawasi",
        f"{km:.1f} km",
        f"({lat:.4f},{lon:.4f})",
        ts or "unknown UTC"
    ], center=True)

def _show_brief(device):
    fp, ts, lat, lon, sats = _find_last_fix_from_csvs(DATA_DIR)
    if not fp:
        _show_lines(device, ["No fix yet", "Check GPS..."], center=True)
        return
    try:
        km = _haversine_km(lat, lon, REF_LAT, REF_LON)
        _show_lines(device, [
            f"{lat:.3f},{lon:.3f}",
            f"{km:.1f} km → Mawasi",
            f"Sats: {sats}"
        ], center=True)
    except Exception as e:
        _show_lines(device, ["Err parsing fix", str(e)], center=True)

# ---------- Main ----------
def main():
    if len(sys.argv) < 2:
        print("Usage: oled_status.py [boot-waking|boot-alive|gps-searching|swim|distance|brief|notify-install|notify-update]")
        return 0

    cmd = sys.argv[1]
    if not isinstance(cmd, str):
        print("[OLED] Invalid command: not a string")
        return 0
    cmd = cmd.lower()

    device = _init_device()

    try:
        if cmd == "boot-waking":
            _show_lines(device, [
                "  _________     ____",
                " /          \\  |  0 |",
                "|            |/ ___\\|",
                "|____________|_/",
                "  |__|  |__|",
            ], center=True)
            _show_lines(device, ["Hope Turtle", "is waking up!"], center=True)

        elif cmd == "boot-alive":
            _show_lines(device, [
                "  _________     ____",
                " /          \\  |  0 |",
                "|            |/ ___\\|",
                "|____________|_/",
                "  |__|  |__|",
            ], center=True)
            _show_lines(device, ["Hope Turtle", "is alive!"], center=True)

        elif cmd == "gps-searching":
            _show_lines(device, ["GPS:", "Searching for satellites…"], center=True)

        elif cmd == "swim":
            _swim_animation(device, duration_s=5.0, fps=2)

        elif cmd == "distance":
            _show_last_distance(device)

        elif cmd == "brief":
            _show_brief(device)

        elif cmd == "notify-install":
            _show_lines(device, ["Hope Turtle", "Fresh install!", "🐢 ready"], center=True)

        elif cmd == "notify-update":
            _show_lines(device, ["Hope Turtle", "Code updated!", "🐢 go!"], center=True)

        else:
            _show_lines(device, [f"Unknown cmd:", cmd], center=True)

    except Exception:
        traceback.print_exc()
    finally:
        # Only auto-clear when NOT in beta mode
        if not BETA_TESTING:
            _clear(device)
    return 0

if __name__ == "__main__":
    sys.exit(main())
