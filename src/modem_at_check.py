#!/usr/bin/env python3
import os, sys, time
import serial

MODEM_PORT = os.getenv("HT_MODEM_PORT", "/dev/serial0")  # full UART on pins 8/10
BAUD = int(os.getenv("HT_MODEM_BAUD", "9600"))

def at(ser, cmd, wait=0.3):
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode())
    time.sleep(wait)
    out = ser.read_all().decode(errors="ignore")
    print(f">>> {cmd}\n{out.strip()}\n")
    return out

def main():
    try:
        ser = serial.Serial(MODEM_PORT, BAUD, timeout=1)
    except Exception as e:
        print(f"[ERR] open {MODEM_PORT}: {e}")
        return 1

    at(ser, "AT")
    at(ser, "ATE0")            # echo off
    at(ser, "AT+CPIN?")        # SIM ready?
    at(ser, "AT+CSQ")          # signal quality
    at(ser, "AT+CREG?")        # network registration
    at(ser, "AT+CGATT?")       # GPRS attached?
    at(ser, "AT+COPS?")        # operator
    at(ser, "AT+CCID")         # SIM card ID (some firmwares)
    ser.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
