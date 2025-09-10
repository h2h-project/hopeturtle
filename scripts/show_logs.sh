#!/usr/bin/env bash
set -euo pipefail

clear
cat <<'BANNER'
#      ___________    _____
#  /               \ |  o  | 
# |                |/   __\| 
# |  _______________  /     
#   |_|_|     |_|_|
#
# HopeTurtle GPS Service is live! 🐢
BANNER
echo
echo "Following: journalctl -fu hopeturtle-gps.service"
echo "Press Ctrl+C to exit."
echo

# Follow logs from the last few minutes and keep tailing
journalctl -u hopeturtle-gps.service --since "10 min ago" --no-pager
echo
journalctl -fu hopeturtle-gps.service
