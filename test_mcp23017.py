from smbus2 import SMBus
import time

I2C_BUS = 1
ADDRESS = 0x21

# MCP23017 Register bei BANK=0
IODIRA = 0x00
IODIRB = 0x01

GPPUA = 0x0C
GPPUB = 0x0D

GPIOA = 0x12
GPIOB = 0x13

bus = SMBus(I2C_BUS)

# Alle 16 Pins als Eingang
bus.write_byte_data(ADDRESS, IODIRA, 0xFF)
bus.write_byte_data(ADDRESS, IODIRB, 0xFF)

# Interne Pull-ups einschalten
bus.write_byte_data(ADDRESS, GPPUA, 0xFF)
bus.write_byte_data(ADDRESS, GPPUB, 0xFF)


def read_gpio():
    a = bus.read_byte_data(ADDRESS, GPIOA)
    b = bus.read_byte_data(ADDRESS, GPIOB)

    return a | (b << 8)


def pin_name(pin):
    if pin < 8:
        return f"PA{pin}"
    else:
        return f"PB{pin - 8}"


previous = read_gpio()

print("MCP23017 Encoder-Test")
print("---------------------")
print("Drehknöpfe langsam drehen oder drücken.")
print("Abbruch mit Ctrl+C\n")

try:
    while True:
        current = read_gpio()

        changed = previous ^ current

        if changed:
            for pin in range(16):
                mask = 1 << pin

                if changed & mask:
                    state = "HIGH" if current & mask else "LOW"

                    print(f"{pin_name(pin):3} -> {state}")

        previous = current

        time.sleep(0.005)

except KeyboardInterrupt:
    print("\nTest beendet.")

finally:
    bus.close()