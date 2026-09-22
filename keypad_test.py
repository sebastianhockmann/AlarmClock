"""4x4-Matrix am PCF8574 testen; Ausgabe im Terminal, Ende mit Strg+C.

Beispiel (Adresse und Verdrahtung zuvor pruefen):
    .venv/bin/python keypad_test.py --address 0x20
Vorgabe: R1..R4 an P0..P3, C1..C4 an P4..P7.
Chip-Grundlage: https://www.ti.com/lit/ds/symlink/pcf8574.pdf
"""

import argparse
import sys
import time

import config

KEYS = ("123A", "456B", "789C", "*0#D")


def pins(value):
    try:
        result = tuple(int(pin) for pin in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Pins als 0,1,2,3 angeben") from error
    if len(result) != 4 or len(set(result)) != 4 or any(p not in range(8) for p in result):
        raise argparse.ArgumentTypeError("Vier verschiedene Pins zwischen 0 und 7 angeben")
    return result


def scan(bus, address, rows, cols):
    pressed = set()
    try:
        for row, pin in enumerate(rows):
            # PCF8574: HIGH gibt einen Pin zum Einlesen frei.
            bus.write_byte(address, 0xFF & ~(1 << pin))
            time.sleep(0.001)
            value = bus.read_byte(address)
            for col, col_pin in enumerate(cols):
                if not value & (1 << col_pin):
                    pressed.add((row, col))
    finally:
        bus.write_byte(address, 0xFF)
    return pressed


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--address", required=True, type=lambda v: int(v, 0),
                        help="I2C-Adresse des Tastenfelds, z. B. 0x20 (nicht die LCD-Adresse)")
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--rows", type=pins, default=(0, 1, 2, 3), help="Pins fuer R1..R4")
    parser.add_argument("--cols", type=pins, default=(4, 5, 6, 7), help="Pins fuer C1..C4")
    args = parser.parse_args()
    if not (0x20 <= args.address <= 0x27 or 0x38 <= args.address <= 0x3F):
        parser.error("PCF8574/A-Adresse muss 0x20..0x27 oder 0x38..0x3f sein")
    if args.bus < 0:
        parser.error("Busnummer muss mindestens 0 sein")
    if set(args.rows) & set(args.cols):
        parser.error("Zeilen und Spalten muessen verschiedene Pins verwenden")
    if args.bus == config.LCD_I2C_PORT and args.address == config.LCD_ADDRESS:
        parser.error("Diese Adresse ist in config.py bereits fuer das LCD eingetragen")
    try:
        from smbus2 import SMBus
    except ImportError:
        print("smbus2 fehlt. Installieren: .venv/bin/python -m pip install smbus2", file=sys.stderr)
        return 1

    try:
        with SMBus(args.bus) as bus:
            bus.write_byte(args.address, 0xFF)
            print(f"Tastenfeld auf Bus {args.bus}, Adresse {args.address:#04x}", flush=True)
            print(f"Zeilen: {args.rows}; Spalten: {args.cols}")
            print("Bitte einzeln druecken (Mehrfachdruck kann Ghosting erzeugen). Ende: Strg+C.")
            stable = set()
            candidate = set()
            changed_at = time.monotonic()
            while True:
                current = scan(bus, args.address, args.rows, args.cols)
                now = time.monotonic()
                if current != candidate:
                    candidate = current
                    changed_at = now
                if candidate != stable and now - changed_at >= 0.04:
                    for row, col in sorted(candidate - stable):
                        print(f"Gedrueckt: {KEYS[row][col]} (Zeile {row + 1}, Spalte {col + 1})", flush=True)
                    for row, col in sorted(stable - candidate):
                        print(f"Losgelassen: {KEYS[row][col]}", flush=True)
                    stable = candidate.copy()
                time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nTastenfeld-Test beendet.")
    except OSError as error:
        print(f"I2C-Fehler: {error}. Bus, Adresse und Verkabelung pruefen.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
