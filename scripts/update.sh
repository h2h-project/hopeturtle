#!/bin/bash
set -e

echo "==> HopeTurtle updater starting..."

REPO_DIR="$HOME/hopeturtle"

cd "$REPO_DIR"

# ---- Pull from GitHub ----
echo "==> Pulling latest from Git..."
git fetch origin
git reset --hard origin/main

# ---- Ensure scripts are executable ----
chmod +x scripts/install.sh scripts/update.sh

# ---- Run installer (handles services, UART, OLED, etc.) ----
echo "==> Running full install/update..."
./scripts/install.sh

# ---- Summary ----
echo "✅ Update complete."
echo "💡 Both hopeturtle-gps.timer and hopeturtle-boot.service should now be active."

# ---- Summary ----
cat <<'EOF'

    _________    ____
  /           \ |  o |
 |            |/ ___\|
 |____________|_/
   |__|  |__|

 Hope Turtle Code is updated! 🐢

EOF

# OLED notify (safe if OLED missing)
python3 src/oled_status.py notify-update || true

