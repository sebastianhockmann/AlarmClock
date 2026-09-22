from RPLCD.i2c import CharLCD
import config

lcd = CharLCD(
    'PCF8574',
    config.LCD_ADDRESS,
    cols=config.LCD_COLS,
    port=config.LCD_I2C_PORT,
    rows=config.LCD_ROWS
)

_backlight_manual = False
_backlight_state = True
_last_lines = [None, None]

def _sanitize(text: str) -> str:
    """Nur ASCII, LCD-kompatibel, exakt 16 Zeichen."""
    if text is None:
        text = ""

    for original, replacement in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"),
                                  ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        text = text.replace(original, replacement)

    # Nicht ASCII → ersetzen
    filtered = ''.join(
        ch if 32 <= ord(ch) < 127 else ' '
        for ch in text
    )

    # Kürzen + fill auf exakt 16 Zeichen
    filtered = filtered[:config.LCD_COLS].ljust(config.LCD_COLS)

    return filtered


def lcd_show(now, text):
    """Zeigt Uhrzeit + 1 Textzeile. Beide exakt 16 Zeichen."""
    lines = [_sanitize(now.strftime("%H:%M:%S")), _sanitize(text)]
    for row, line in enumerate(lines):
        if _last_lines[row] != line:
            lcd.cursor_pos = (row, 0)
            lcd.write_string(line)
            _last_lines[row] = line


def lcd_set_backlight(toggle=False, state=None, force=False):
    global _backlight_manual, _backlight_state

    if toggle:
        _backlight_manual = True
        _backlight_state = not _backlight_state
    elif state is not None:
        if not _backlight_manual:
            _backlight_state = state

    target = bool(state) if force and state is not None else _backlight_state
    if lcd.backlight_enabled != target:
        lcd.backlight_enabled = target


def lcd_close():
    lcd.close(clear=True)
