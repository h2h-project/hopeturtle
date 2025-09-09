# The Hope Turtle Project
The code to track, navigate and propel the autonomous hope turtle— low-tech, low-cost bamboo marine vehicles designed to deliver humanitarian aid by leveraging currents, wind, and solar power. Unlike conventional high-tech solutions, this approach emphasizes accessibility, affordability, and ecological sustainability.

## Version One

Currently, we are focused on the version one hope turtle software: with the simple goal of acheiving GPS logging for tracking.  Later version 2 will build upon this foundation.  We are using a Raspberry Pi Zero 2 W.

## HopeTurtle GPS

One-shot GPS logger using the Ublox NEO-6M/8M (via /dev/serial0). Appends a CSV row every 5 minutes via systemd timer.

## Wiring
- GPS VCC → Pi 5V (Pin 2) **or** 3V3 (Pin 1) *depending on your module; most NEO-6M/8M breakouts want 5V*
- GPS GND → Pi GND (Pin 6)
- GPS TX → Pi RXD0 (Pin 10 / GPIO15)
- GPS RX → Pi TXD0 (Pin 8 / GPIO14)

## First-time Pi setup
```bash
sudo raspi-config  # Interface Options → Serial: login shell = No, hardware = Yes
echo 'enable_uart=1' | sudo tee -a /boot/firmware/config.txt
sudo reboot

