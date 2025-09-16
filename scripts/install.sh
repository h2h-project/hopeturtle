#!/bin/bash
set -e

echo "==> HopeTurtle installer starting..."

USER=$(whoami)
HOME_DIR=$(eval echo ~$USER)
REPO_DIR="$HOME_DIR/hopeturtle"
DATA_DIR="$REPO_DIR/data"

echo "==> Repo: $REPO_DIR"
echo "==> Using user: $USER (home: $HOME_DIR)"
echo "==> Data dir: $DATA_DIR"

# ---- Ensure dependencies ----
echo "==> Installing dependencies..."
sudo apt-get update
sudo apt-get install -y python3-serial python3-pigpio pigpio jq python3-pil python3-numpy

# ---- Ensure pigpio daemon runs at boot (needed for soft-serial GPS) ----
echo "==> Enabling pigpiod..."
sudo systemctl enable --now pigpiod

# ---- Ensure data dir exists ----
mkdir -p "$DATA_DIR"

# ---- Enable full UART for SIM900 on pins 8/10 ----
if ! grep -q "^enable_uart=1" /boot/firmware/config.txt; then
  echo "enable_uart=1" | sudo tee -a /boot/firmware/config.txt
  echo "==> Enabled full UART for SIM900 (pins 8/10). Reboot required."
else
  echo "==> UART already enabled."
fi

# ---- Install systemd services + timers ----
echo "==> Installing systemd service + timer..."
sudo cp systemd/hopeturtle-gps.* /etc/systemd/system/
sudo cp systemd/hopeturtle-boot.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now hopeturtle-gps.timer
sudo systemctl enable hopeturtle-boot.service

# ---- GUI autostart of logs ----
AUTOSTART_DIR="$HOME_DIR/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cp scripts/show_logs.desktop "$AUTOSTART_DIR/"

# ---- Trigger one manual GPS run ----
echo "==> Triggering one manual GPS run..."
sudo systemctl start hopeturtle-gps.service || true

# ---- Summary ----
cat <<'EOF'

    _________    ____
  /           \ |  o |
 |            |/ ___\|
 |____________|_/
   |__|  |__|

 Fresh Hope Turtle Code installed! 🐢

EOF

# OLED notify (safe if OLED missing)
python3 src/oled_status.py notify-install || true


# ---- Summary ----
echo "✅ Install complete."
echo "⚠️ If 'enable_uart=1' was just added, please reboot for SIM900 to work."
echo "💡 GPS will read via pigpio soft-serial on GPIO17 (pin 11)."
echo "💡 OLED boot messages will now appear at startup via hopeturtle-boot.service."
