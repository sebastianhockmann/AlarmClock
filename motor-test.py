#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time

# Definiere den GPIO-Pin für das PWM-Signal (BCM-Nummerierung)
SERVO_PIN = 18

# Setup
GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)

# PWM mit 50Hz initialisieren (Standard für Servos)
pwm = GPIO.PWM(SERVO_PIN, 50)
pwm.start(7.5)  # 7.5 entspricht meist der Mittelstellung

print("Servo schwingt... Drücke STRG+C zum Beenden.")

try:
    while True:
        # Servo bewegt sich zur linken Position (ungefähr 0°)
        pwm.ChangeDutyCycle(5)  # ca. 5% Duty Cycle
        time.sleep(1)
        
        # Servo bewegt sich zur rechten Position (ungefähr 180°)
        pwm.ChangeDutyCycle(10)  # ca. 10% Duty Cycle
        time.sleep(1)
except KeyboardInterrupt:
    print("Programm wird beendet.")
finally:
    pwm.stop()
    GPIO.cleanup()
