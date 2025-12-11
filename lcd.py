from RPLCD.i2c import CharLCD
import config

lcd = CharLCD('PCF8574',
              config.LCD_ADDRESS,
              cols=config.LCD_COLS,
              rows=config.LCD_ROWS)

_backlight_manual = False
_backlight_state = True

def lcd_show(now, text):
    lcd.cursor_pos = (0, 0)
    lcd.write_string(now.strftime("%H:%M:%S").center(config.LCD_COLS))

    lcd.cursor_pos = (1, 0)
    lcd.write_string(text[:config.LCD_COLS].center(config.LCD_COLS))

def lcd_set_backlight(toggle=False, state=None):
    global _backlight_manual, _backlight_state
    
    if toggle:
        _backlight_manual = True
        _backlight_state = not _backlight_state
    elif state is not None:
        if not _backlight_manual:
            _backlight_state = state

    lcd.backlight_enabled = _backlight_state
