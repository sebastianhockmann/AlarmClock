# servo_control.py
from gpiozero import Servo
from time import sleep
import threading
import config

servo = Servo(config.SERVO_PIN)
stop_event = threading.Event()
thread = None


def _waving_thread():
    while not stop_event.is_set():
        servo.value = -0.5
        sleep(0.5)
        servo.value = 0.5
        sleep(0.5)
    servo.value = None  # Servo stromlos machen


def start_servo_waving():
    global thread
    stop_event.clear()
    thread = threading.Thread(target=_waving_thread)
    thread.start()


def stop_servo_waving():
    stop_event.set()
    if thread:
        thread.join()
    servo.value = None
