#!/usr/bin/env python3
"""Uhr mit zwei Drehknöpfen und 4x4-Tastatur auf I2C-Hardware.

Hardware:
- LCD: 0x20 (PCF8574 / PCF8574A)
- MCP23017: 0x21
  - Drehknopf 1: PB6 (A), PB7 (B), PB5 (Taster)
  - Drehknopf 2: PA0 (A), PA1 (B), PA2 (Taster)
- 4x4-Matrix: 0x27 (PCF8574 / PCF8574A)

Das Programm zeigt standardmäßig die Uhrzeit mit Sekunden. Wenn einer der beiden
Drehknöpfe gedreht wird, wechselt die Anzeige kurzzeitig auf das aktuelle Datum.
Beim Drücken einer Matrix-Taste wird die Taste auf dem Display angezeigt.
"""

import time
from datetime import datetime

from RPLCD.i2c import CharLCD
from smbus2 import SMBus

I2C_BUS = 1

LCD_ADDRESS = 0x27
LCD_COLS = 16
LCD_ROWS = 2

MCP_ADDRESS = 0x21
KEYPAD_ADDRESS = 0x20

IODIRA = 0x00
IODIRB = 0x01
GPPUA = 0x0C
GPPUB = 0x0D
GPIOA = 0x12
GPIOB = 0x13

# Bit-Positionen im 16-Bit-GPIO-Wort:
# PA0..PA7 = Bits 0..7, PB0..PB7 = Bits 8..15
# Gemäß den Messungen: Linker Encoder auf PB6/PB7, Taster auf PB5;
# rechter Encoder auf PA0/PA1, Taster auf PA2.
ENC1 = {"a": 14, "b": 15, "button": 13}  # PB6, PB7, PB5
ENC2 = {"a": 0, "b": 1, "button": 2}     # PA0, PA1, PA2

KEYS = ("123A", "456B", "789C", "*0#D")

# Quadratur-Tableau: 00 -> 01 -> 11 -> 10 -> 00
TRANSITIONS = (
    0, -1, 1, 0,
    1, 0, 0, -1,
    -1, 0, 0, 1,
    0, 1, -1, 0,
)


class QuadDecoder:
    """Decodiert eine 2-bit Quadratur-Quelle (A/B)."""

    def __init__(self, initial_state):
        self.previous = int(initial_state) & 0b11
        self.partial = 0

    def update(self, current):
        current = int(current) & 0b11
        previous = self.previous
        self.previous = current

        if (previous ^ current) == 0b11:
            self.partial = 0
            return 0

        self.partial += TRANSITIONS[(previous << 2) | current]
        if abs(self.partial) >= 2:
            direction = 1 if self.partial > 0 else -1
            self.partial = 0
            return direction
        return 0


class InputState:
    def __init__(self):
        self.button_pressed = False
        self.last_button = False


class MCPInput:
    def __init__(self, bus):
        self.bus = bus
        self.encoders = {
            "left": QuadDecoder(self._read_encoder_state(ENC1["a"], ENC1["b"])),
            "right": QuadDecoder(self._read_encoder_state(ENC2["a"], ENC2["b"])),
        }
        self.button_state = {
            "left": InputState(),
            "right": InputState(),
        }
        self.last_gpio = self._read_gpio()

    def _read_gpio(self):
        a = self.bus.read_byte_data(MCP_ADDRESS, GPIOA)
        b = self.bus.read_byte_data(MCP_ADDRESS, GPIOB)
        return a | (b << 8)

    def _read_encoder_state(self, a_bit, b_bit):
        gpio = self._read_gpio()
        return ((gpio >> a_bit) & 1) | (((gpio >> b_bit) & 1) << 1)

    def poll(self):
        gpio = self._read_gpio()
        changes = []

        left_state = ((gpio >> ENC1["a"]) & 1) | (((gpio >> ENC1["b"]) & 1) << 1)
        right_state = ((gpio >> ENC2["a"]) & 1) | (((gpio >> ENC2["b"]) & 1) << 1)

        left_delta = self.encoders["left"].update(left_state)
        right_delta = self.encoders["right"].update(right_state)

        if left_delta:
            changes.append(("left", left_delta))
        if right_delta:
            changes.append(("right", right_delta))

        left_button = bool((gpio >> ENC1["button"]) & 1)
        right_button = bool((gpio >> ENC2["button"]) & 1)

        if left_button != self.button_state["left"].last_button:
            self.button_state["left"].last_button = left_button
            self.button_state["left"].button_pressed = not left_button
            if self.button_state["left"].button_pressed:
                changes.append(("left_button", 1))

        if right_button != self.button_state["right"].last_button:
            self.button_state["right"].last_button = right_button
            self.button_state["right"].button_pressed = not right_button
            if self.button_state["right"].button_pressed:
                changes.append(("right_button", 1))

        self.last_gpio = gpio
        return changes


def init_mcp(bus):
    # Für die Messung waren alle MCP23017-Pins als Eingänge konfiguriert. Das ist
    # die robusteste Ausgangsbasis für Encoder- und Tastendaten.
    bus.write_byte_data(MCP_ADDRESS, IODIRA, 0xFF)
    bus.write_byte_data(MCP_ADDRESS, IODIRB, 0xFF)
    bus.write_byte_data(MCP_ADDRESS, GPPUA, 0xFF)
    bus.write_byte_data(MCP_ADDRESS, GPPUB, 0xFF)
    return MCPInput(bus)


def scan_keypad(bus, address):
    """Wandelt eine 4x4-Matrix in einen Tastencode um."""
    KEYS = ("123A", "456B", "789C", "*0#D")
    rows = (0, 1, 2, 3)
    cols = (4, 5, 6, 7)

    pressed = set()
    try:
        for row, pin in enumerate(rows):
            bus.write_byte(address, 0xFF & ~(1 << pin))
            time.sleep(0.001)
            value = bus.read_byte(address)
            for col, col_pin in enumerate(cols):
                if not (value & (1 << col_pin)):
                    pressed.add((row, col))
    finally:
        bus.write_byte(address, 0xFF)

    if len(pressed) != 1:
        return None
    row, col = next(iter(pressed))
    return KEYS[row][col]


def write_line(lcd, row, text):
    line = str(text)[:LCD_COLS].ljust(LCD_COLS)
    lcd.cursor_pos = (row, 0)
    lcd.write_string(line)


def display_time(lcd, now, date_visible=False, key_text=None):
    if key_text:
        write_line(lcd, 0, f"Taste: {key_text}")
        write_line(lcd, 1, now.strftime("%H:%M:%S"))
        return

    if date_visible:
        write_line(lcd, 0, now.strftime("%d.%m.%Y"))
        write_line(lcd, 1, now.strftime("%H:%M:%S"))
    else:
        write_line(lcd, 0, now.strftime("%H:%M:%S"))
        write_line(lcd, 1, "")


def main():
    lcd = CharLCD(
        "PCF8574",
        LCD_ADDRESS,
        cols=LCD_COLS,
        rows=LCD_ROWS,
        port=I2C_BUS,
    )
    lcd.clear()
    lcd.backlight_enabled = True

    with SMBus(I2C_BUS) as bus:
        mcp = init_mcp(bus)
        bus.write_byte(KEYPAD_ADDRESS, 0xFF)

        date_display_until = 0.0
        key_display_until = 0.0
        last_key = None

        try:
            while True:
                now = datetime.now()
                current_time = time.monotonic()

                for event in mcp.poll():
                    name, value = event
                    if name in ("left", "right"):
                        date_display_until = current_time + 4.0
                    elif name.endswith("_button"):
                        pass

                key = scan_keypad(bus, KEYPAD_ADDRESS)
                if key and key != last_key:
                    last_key = key
                    key_display_until = current_time + 2.5
                elif not key:
                    last_key = None

                if key_display_until > current_time:
                    display_time(lcd, now, date_visible=False, key_text=last_key)
                elif date_display_until > current_time:
                    display_time(lcd, now, date_visible=True, key_text=None)
                else:
                    display_time(lcd, now, date_visible=False, key_text=None)

                time.sleep(0.02)
        except KeyboardInterrupt:
            print("Abbruch durch Benutzer.")
        finally:
            lcd.close(clear=True)


if __name__ == "__main__":
    main()
