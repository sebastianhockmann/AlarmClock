"""Drehencoder mit Taster am MCP23017 testen.

Passiver Encoder mit fuenf Anschluessen (Belegung am Bauteil pruefen):
    A -> GPA0, B -> GPA1, gemeinsamer Anschluss C -> GND
    Tasterkontakt 1 -> GPA2, Tasterkontakt 2 -> GND
Modul mit CLK/DT/SW/+/GND: CLK -> GPA0, DT -> GPA1, SW -> GPA2,
    + -> 3,3 V, GND -> GND (Modul muss fuer 3,3 V geeignet sein).
MCP23017: VDD und RESET -> 3,3 V, VSS -> GND, SDA/SCL -> Pi-I2C.
A0/A1/A2 -> GND ergibt Adresse 0x20. Gemeinsame Masse verwenden.
Keine 5-V-Pull-ups an den Raspberry-Pi-I2C anschliessen.

Voraussetzung: MCP23017 im BANK=0-Modus (Zustand nach Reset).
Andere Programme mit Zugriff auf denselben Chip vorher beenden.
Kein Test fuer analoge Potentiometer: Dafuer ist ein ADC erforderlich.
Polling kann bei schnellem Drehen Schritte verpassen.

Start: .venv/bin/python encoder_test.py
Optionen: --address 0x21 --steps 2 --reverse --raw
Register: https://ww1.microchip.com/downloads/aemDocuments/documents/APID/ProductDocuments/DataSheets/MCP23017-Data-Sheet-DS20001952.pdf
"""

import argparse
import sys
import time

IODIRA = 0x00
IPOLA = 0x02
GPPUA = 0x0C
GPIOA = 0x12
INPUT_MASK = 0b111

# Positive Folge: 11 -> 01 -> 00 -> 10 -> 11.
# Gegenlaeufige Prellflanken heben sich gegenseitig auf.
TRANSITIONS = (0, -1, 1, 0, 1, 0, 0, -1,
               -1, 0, 0, 1, 0, 1, -1, 0)


class Decoder:
    def __init__(self, initial, steps=4):
        self.previous = initial
        self.steps = steps
        self.partial = 0

    def update(self, current):
        previous = self.previous
        self.previous = current
        if previous ^ current == 3:
            # Beide Bits gewechselt: Richtung unbekannt, Teilfolge verwerfen.
            self.partial = 0
            return 0
        self.partial += TRANSITIONS[(previous << 2) | current]
        if abs(self.partial) >= self.steps:
            direction = 1 if self.partial > 0 else -1
            self.partial = 0
            return direction
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bus', type=int, default=1)
    parser.add_argument('--address', type=lambda value: int(value, 0), default=0x20)
    parser.add_argument('--steps', type=int, choices=(1, 2, 4), default=4,
                        help='Signalwechsel pro Rastung (Standard: 4)')
    parser.add_argument('--reverse', action='store_true', help='Drehrichtung umkehren')
    parser.add_argument('--raw', action='store_true', help='Zusaetzlich A/B/SW-Pegel anzeigen')
    args = parser.parse_args()
    if not 0x20 <= args.address <= 0x27:
        parser.error('MCP23017-Adresse muss zwischen 0x20 und 0x27 liegen')
    if args.bus < 0:
        parser.error('Busnummer muss mindestens 0 sein')

    try:
        from smbus2 import SMBus
    except ImportError:
        print('smbus2 fehlt: .venv/bin/python -m pip install smbus2', file=sys.stderr)
        return 1

    try:
        with SMBus(args.bus) as bus:
            saved = {}
            try:
                for register in (IODIRA, IPOLA, GPPUA):
                    saved[register] = bus.read_byte_data(args.address, register)
                # Nur GPA0..GPA2 konfigurieren; andere Pins unveraendert lassen.
                bus.write_byte_data(args.address, IODIRA, saved[IODIRA] | INPUT_MASK)
                bus.write_byte_data(args.address, IPOLA, saved[IPOLA] & ~INPUT_MASK)
                bus.write_byte_data(args.address, GPPUA, saved[GPPUA] | INPUT_MASK)
                previous = bus.read_byte_data(args.address, GPIOA) & INPUT_MASK
                decoder = Decoder(previous & 3, args.steps)
                stable_button = candidate = bool(previous & 4)
                changed_at = time.monotonic()
                position = 0
                print(f'Encoder-Test: Bus {args.bus}, Adresse {args.address:#04x}')
                print('A=GPA0, B=GPA1, Taster=GPA2. Ende mit Strg+C.')
                print(f'Zaehler: 0; Taster: {"frei" if stable_button else "gedrueckt"}', flush=True)
                while True:
                    current = bus.read_byte_data(args.address, GPIOA) & INPUT_MASK
                    now = time.monotonic()
                    delta = decoder.update(current & 3)
                    if args.reverse:
                        delta = -delta
                    if delta:
                        position += delta
                        print(f'{"Rechts" if delta > 0 else "Links"}: Zaehler {position}', flush=True)
                    button = bool(current & 4)
                    if button != candidate:
                        candidate = button
                        changed_at = now
                    if candidate != stable_button and now - changed_at >= 0.03:
                        stable_button = candidate
                        print(f'Taster {"losgelassen" if stable_button else "gedrueckt"}', flush=True)
                    if args.raw and current != previous:
                        print(f'A={current & 1} B={(current >> 1) & 1} SW={(current >> 2) & 1}', flush=True)
                    previous = current
                    time.sleep(0.001)
            finally:
                # Richtung zuletzt wiederherstellen, solange die Pins noch Eingaenge sind.
                for register in (GPPUA, IPOLA, IODIRA):
                    if register in saved:
                        try:
                            bus.write_byte_data(args.address, register, saved[register])
                        except OSError as error:
                            print(f'Register {register:#04x} konnte nicht wiederhergestellt werden: {error}',
                                  file=sys.stderr)
    except KeyboardInterrupt:
        print('\nEncoder-Test beendet.')
    except OSError as error:
        print(f'I2C-Fehler: {error}. Bus, Adresse und Verkabelung pruefen.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
