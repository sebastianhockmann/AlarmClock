from lcd import lcd_show
from datetime import datetime
import time

print("Teste LCD...")

texts = [
    "Hallo",
    "1234567890123456",
    "Test",
    "Frohe Weihnacht",
    "Schnee",
    "Hi!"
]

while True:
    for t in texts:
        lcd_show(datetime.now(), t)
        time.sleep(1)
