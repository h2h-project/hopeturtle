#!/usr/bin/env bash
set -euo pipefail

# --- HopeTurtle first-time installer ---
# Use this for the very first setup on a Pi.
# It delegates to update.sh and suggests a reboot
# so GUI autostart + group membership take effect.

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Make sure update.sh is executable
chmod +x "$REPO_DIR/scripts/update.sh"

# Run the updater
"$REPO_DIR/scripts/update.sh"

echo
echo "✅ Install complete."
echo "If this was your first run on this Pi, consider rebooting now so:"
echo " - GUI autostart (log terminal) kicks in"
echo " - New 'dialout' group membership is active for your user"
echo
read -r -p "Reboot now? [y/N] " ans || true
if [[ "${ans:-N}" =~ ^[Yy]$ ]]; then
  sudo reboot
else
  echo "You can reboot later with: sudo reboot"
fi

