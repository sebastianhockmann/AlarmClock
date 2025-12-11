import threading
import time
from gpiozero import Servo
import config

servo = Servo(config.SERVO_PIN)
servo.value = None

stop_event = threading.Event()
thread = None

def _wave():
    while not stop_event.is_set():
        servo.value = -0.5
        time.sleep(0.5)
        if stop_event.is_set(): break
        servo.value = 0.5
        time.sleep(0.5)
    servo.value = None

def start_servo_waving():
    global thread
    stop_event.clear()
    thread = threading.Thread(target=_wave)
    thread.start()

def stop_servo_waving():
    stop_event.set()
    if thread:
        thread.join()
