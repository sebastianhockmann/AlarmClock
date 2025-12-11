from RPLCD.i2c import CharLCD
import config

lcd = CharLCD(
    'PCF8574',
    config.LCD_ADDRESS,
    cols=config.LCD_COLS,
    rows=config.LCD_ROWS
)

_backlight_manual = False
_backlight_state = True

def _sanitize(text: str) -> str:
    """Nur ASCII, LCD-kompatibel, exakt 16 Zeichen."""
    if text is None:
        text = ""

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
    # Zeile 0
    line1 = now.strftime("%H:%M:%S").ljust(config.LCD_COLS)
    lcd.cursor_pos = (0, 0)
    lcd.write_string(line1)

    # Zeile 1
    safe = _sanitize(text)
    lcd.cursor_pos = (1, 0)
    lcd.write_string(safe)


def lcd_set_backlight(toggle=False, state=None):
    global _backlight_manual, _backlight_state

    if toggle:
        _backlight_manual = True
        _backlight_state = not _backlight_state
    elif state is not None:
        if not _backlight_manual:
            _backlight_state = state

    lcd.backlight_enabled = _backlight_state
