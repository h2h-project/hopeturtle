#!/usr/bin/env bash
set -euo pipefail

# --- HopeTurtle one-command updater ---
# What it does:
# - git pull
# - ensure deps
# - install/update systemd timer + service (paths/user auto-detected)
# - (re)start timer

# Detect repo root (this script lives in ./scripts/)
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Detect user/home (prefer the invoking user if run with sudo)
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
REPO_NAME="$(basename "$REPO_DIR")"

SERVICE_NAME="hopeturtle-gps.service"
TIMER_NAME="hopeturtle-gps.timer"

PYTHON_BIN="/usr/bin/python3"
SERIAL_DEV="${HT_SERIAL_PORT:-/dev/serial0}"
BAUD_DEFAULT="${HT_BAUD:-9600}"
DATA_DIR_DEFAULT="${HT_DATA_DIR:-$REAL_HOME/$REPO_NAME/data}"

echo "==> Repo: $REPO_DIR"
echo "==> Using user: $REAL_USER (home: $REAL_HOME)"
echo "==> Data dir default: $DATA_DIR_DEFAULT"

# 1) Pull latest
if command -v git >/dev/null 2>&1; then
  echo "==> Pulling latest from Git..."
  git pull --ff-only || true
else
  echo "!! git not installed; installing"
  sudo apt update && sudo apt install -y git
  git pull --ff-only || true
fi

# 2) Ensure Python deps
echo "==> Ensuring Python dependencies..."
sudo apt update
sudo apt install -y python3-serial

# 3) Create data dir and fix ownership
mkdir -p "$DATA_DIR_DEFAULT"
sudo chown -R "$REAL_USER:$REAL_USER" "$REPO_DIR"
chmod -R u+rwX,g+rX "$REPO_DIR"
chmod 755 "$REAL_HOME" || true

# 4) Prepare /etc/default (optional overrides; only create if missing)
DEFAULTS_FILE="/etc/default/hopeturtle-gps"
if [ ! -f "$DEFAULTS_FILE" ]; then
  echo "==> Creating optional $DEFAULTS_FILE (edit to override env)..."
  sudo tee "$DEFAULTS_FILE" >/dev/null <<EOF
# HopeTurtle service overrides (optional)
#HT_SERIAL_PORT=/dev/serial0
#HT_BAUD=9600
HT_DATA_DIR="$DATA_DIR_DEFAULT"
EOF
fi

# 5) Install TIMER (copy as-is from repo)
if [ -f "$REPO_DIR/systemd/$TIMER_NAME" ]; then
  echo "==> Installing timer unit..."
  sudo cp "$REPO_DIR/systemd/$TIMER_NAME" /etc/systemd/system/
else
  echo "!! Missing $REPO_DIR/systemd/$TIMER_NAME"
  exit 1
fi

# 6) Generate SERVICE with correct user/paths (based on repo file but patched)
if [ -f "$REPO_DIR/systemd/$SERVICE_NAME" ]; then
  echo "==> Generating service unit for user=$REAL_USER..."
  # Read original and patch lines
  TMP_SERVICE="$(mktemp)"
  awk -v u="$REAL_USER" -v home="$REAL_HOME" -v repo="$REPO_DIR" -v py="$PYTHON_BIN" '
    BEGIN{wd=repo; exec=py " " repo "/src/gps_snapshot.py"}
    {
      if ($0 ~ /^User=/) { print "User=" u; next }
      if ($0 ~ /^Group=/) { print "Group=" u; next }
      if ($0 ~ /^WorkingDirectory=/) { print "WorkingDirectory=" wd; next }
      if ($0 ~ /^ExecStart=/) { print "ExecStart=" exec; next }
      if ($0 ~ /^Environment=HT_DATA_DIR=/) {
        print "Environment=HT_DATA_DIR=" home "/" gensub(".*/","",1,wd) "/data"; next
      }
      print
    }
  ' "$REPO_DIR/systemd/$SERVICE_NAME" > "$TMP_SERVICE"
  sudo cp "$TMP_SERVICE" /etc/systemd/system/$SERVICE_NAME
  rm -f "$TMP_SERVICE"
else
  echo "!! Missing $REPO_DIR/systemd/$SERVICE_NAME"
  exit 1
fi

# 7) Make sure user can access serial
if ! id -nG "$REAL_USER" | grep -qw dialout; then
  echo "==> Adding $REAL_USER to dialout group (serial access)..."
  sudo usermod -aG dialout "$REAL_USER"
  ADDED_DIALOUT=1
else
  ADDED_DIALOUT=0
fi

# 8) Reload systemd & enable timer
echo "==> Reloading systemd and (re)starting timer..."
sudo systemctl daemon-reload
sudo systemctl enable --now "$TIMER_NAME"

# 9) Kick the service once to verify
echo "==> Triggering one manual run..."
sudo systemctl start "$SERVICE_NAME" || true
sleep 1
echo "==> Last service logs:"
journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true

# 10) Final notes
echo
echo "✅ Done. Timer status:"
systemctl status "$TIMER_NAME" --no-pager || true
echo
echo "CSVs live in: $DATA_DIR_DEFAULT"
if [ "${ADDED_DIALOUT:-0}" -eq 1 ]; then
  echo "⚠️ You were just added to the 'dialout' group. A reboot/log out may be required for interactive shells."
fi
