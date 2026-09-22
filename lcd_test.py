from RPLCD.i2c import CharLCD
from time import sleep

print("Starte LCD-Test...")

lcd = CharLCD(
    i2c_expander='PCF8574',
    address=0x27,
    port=1,
    cols=16,
    rows=2,
    charmap='A00',
    auto_linebreaks=False
)

print("LCD initialisiert")

lcd.backlight_enabled = True
lcd.clear()

lcd.cursor_pos = (0, 0)
lcd.write_string("Hallo Raspberry")

lcd.cursor_pos = (1, 0)
lcd.write_string("I2C 0x27 OK")

print("Text gesendet")

sleep(30)

lcd.clear()