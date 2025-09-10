#!/usr/bin/env bash
set -euo pipefail

# --- HopeTurtle one-command updater ---
# - git pull
# - ensure deps
# - install/update systemd timer + service (paths/user auto-detected)
# - set up GUI autostart terminal to show live logs
# - (re)start timer and one manual run

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
DATA_DIR_DEFAULT="${HT_DATA_DIR:-$REAL_HOME/$REPO_NAME/data}"

echo "==> Repo: $REPO_DIR"
echo "==> Using user: $REAL_USER (home: $REAL_HOME)"
echo "==> Data dir default: $DATA_DIR_DEFAULT"

# 1) Pull latest
if ! command -v git >/dev/null 2>&1; then
  echo "==> Installing git..."
  sudo apt update && sudo apt install -y git
fi
echo "==> Pulling latest from Git..."
git pull --ff-only || true

# 2) Ensure Python deps
echo "==> Ensuring Python dependencies..."
sudo apt update
sudo apt install -y python3-serial

# 3) Ensure repo perms & data dir
mkdir -p "$DATA_DIR_DEFAULT"
sudo chown -R "$REAL_USER:$REAL_USER" "$REPO_DIR"
chmod -R u+rwX,g+rX "$REPO_DIR"
chmod 755 "$REAL_HOME" || true

# 4) Optional overrides file for service env
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

# 5) Install TIMER
if [ -f "$REPO_DIR/systemd/$TIMER_NAME" ]; then
  echo "==> Installing timer unit..."
  sudo cp "$REPO_DIR/systemd/$TIMER_NAME" /etc/systemd/system/
else
  echo "!! Missing $REPO_DIR/systemd/$TIMER_NAME"
  exit 1
fi

# 6) Generate SERVICE for this machine (patch user/paths without gensub)
if [ -f "$REPO_DIR/systemd/$SERVICE_NAME" ]; then
  echo "==> Generating service unit for user=$REAL_USER..."
  TMP_SERVICE="$(mktemp)"
  awk -v u="$REAL_USER" -v home="$REAL_HOME" -v repo="$REPO_DIR" -v py="$PYTHON_BIN" -v name="$REPO_NAME" '
    BEGIN{
      wd = repo
      exec = py " " repo "/src/gps_snapshot.py"
      datadir = home "/" name "/data"
    }
    {
      if ($0 ~ /^User=/)                    { print "User=" u; next }
      if ($0 ~ /^Group=/)                   { print "Group=" u; next }
      if ($0 ~ /^WorkingDirectory=/)        { print "WorkingDirectory=" wd; next }
      if ($0 ~ /^ExecStart=/)               { print "ExecStart=" exec; next }
      if ($0 ~ /^Environment=HT_DATA_DIR=/) { print "Environment=HT_DATA_DIR=" datadir; next }
      print
    }
  ' "$REPO_DIR/systemd/$SERVICE_NAME" > "$TMP_SERVICE"
  sudo cp "$TMP_SERVICE" /etc/systemd/system/$SERVICE_NAME
  rm -f "$TMP_SERVICE"
else
  echo "!! Missing $REPO_DIR/systemd/$SERVICE_NAME"
  exit 1
fi

# 7) Ensure serial access: add user to dialout (first-time only)
if ! id -nG "$REAL_USER" | grep -qw dialout; then
  echo "==> Adding $REAL_USER to dialout group (serial access)..."
  sudo usermod -aG dialout "$REAL_USER"
  ADDED_DIALOUT=1
else
  ADDED_DIALOUT=0
fi

# 8) GUI autostart: open terminal with show_logs on login (if script exists)
AUTOSTART_DIR="$REAL_HOME/.config/autostart"
AUTOSTART_DESKTOP="$AUTOSTART_DIR/hopeturtle-logs.desktop"
if [ -f "$REPO_DIR/scripts/show_logs.sh" ]; then
  echo "==> Setting up GUI autostart for log viewer..."
  mkdir -p "$AUTOSTART_DIR"
  # Make sure the log script is executable
  chmod +x "$REPO_DIR/scripts/show_logs.sh"
  # Create .desktop entry (works for Raspberry Pi OS desktop)
  cat > "$AUTOSTART_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=HopeTurtle Logs
Comment=Show HopeTurtle GPS service logs at login
Exec=sh -c 'x-terminal-emulator -e "$HOME/$REPO_NAME/scripts/show_logs.sh" || lxterminal -e "$HOME/$REPO_NAME/scripts/show_logs.sh"'
X-GNOME-Autostart-enabled=true
EOF
  chown "$REAL_USER:$REAL_USER" "$AUTOSTART_DESKTOP"
else
  echo "==> Skipping GUI autostart (scripts/show_logs.sh not found)."
fi

# 9) Reload systemd & enable timer
echo "==> Reloading systemd and (re)starting timer..."
sudo systemctl daemon-reload
sudo systemctl enable --now "$TIMER_NAME"

# 10) Trigger one manual run & show logs
echo "==> Triggering one manual run..."
sudo systemctl start "$SERVICE_NAME" || true
sleep 1
echo "==> Last service logs:"
journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true

echo
echo "✅ Done. Timer status:"
systemctl status "$TIMER_NAME" --no-pager || true
echo
echo "CSV directory: $DATA_DIR_DEFAULT"
if [ "${ADDED_DIALOUT:-0}" -eq 1 ]; then
  echo "⚠️  You were just added to the 'dialout' group. Log out/in or reboot for shells to pick up the new group."
fi
echo "💡 On the desktop, a terminal will auto-open with live logs at next login."
