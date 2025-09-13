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

# Ensure Python + serial support
echo "==> Installing dependencies..."
sudo apt-get update
sudo apt-get install -y python3-serial jq

# Ensure data dir exists
mkdir -p "$DATA_DIR"

# Configure mini UART for GPS (pins 11+13 -> /dev/ttyS0)
if ! grep -q "dtoverlay=uart1,txd1_pin=17,rxd1_pin=27" /boot/config.txt; then
  echo "dtoverlay=uart1,txd1_pin=17,rxd1_pin=27" | sudo tee -a /boot/config.txt
  echo "==> Configured mini UART overlay (reboot required for GPS)."
else
  echo "==> Mini UART overlay already present."
fi

# Install systemd units
echo "==> Installing systemd service + timer..."
sudo cp systemd/hopeturtle-gps.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hopeturtle-gps.timer

# GUI autostart of logs
AUTOSTART_DIR="$HOME_DIR/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cp scripts/show_logs.desktop "$AUTOSTART_DIR/"

# Trigger manual run
echo "==> Triggering one manual run..."
sudo systemctl start hopeturtle-gps.service || true

echo "✅ Install complete."
echo "⚠️ Please reboot now to activate mini UART for GPS."
