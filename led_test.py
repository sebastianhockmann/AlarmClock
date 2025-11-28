#!/usr/bin/env python3
import time
import threading
import subprocess
import select
import fcntl
import os
from datetime import datetime
from RPLCD.i2c import CharLCD
from gpiozero import Button, Servo
import config
import alsaaudio

# LCD initialisieren
lcd = CharLCD('PCF8574', config.LCD_ADDRESS, cols=config.LCD_COLS, rows=config.LCD_ROWS)

# Button (mit Bounce-Time) und Servo initialisieren
button = Button(config.BUTTON_PIN, pull_up=True, bounce_time=0.5)
servo = Servo(config.SERVO_PIN)
servo.value = None  # Servo deaktivieren

# Alarmvariablen
alarm_triggered = False
last_alarm_day = None  # Damit der Alarm nur einmal pro Tag ausgelöst wird

# Flag, um zu verfolgen, ob der Alarm-Audio-Track bereits gestartet wurde
alarm_audio_started = False

# Variablen für Threads
servo_thread = None
servo_stop_event = threading.Event()

audio_thread = None
audio_stop_event = threading.Event()

# Variable für Buttonanzeige
button_pressed_flag = False
button_pressed_time = 0

def play_audio(stop_event):
    """
    Spielt die in config.MP3_FILE definierte MP3-Datei ab.
    Die Datei wird über mpg123 (mit --stdout) in PCM-Daten dekodiert und
    diese werden über alsaaudio an das ALSA-Gerät gesendet.
    Die Wiedergabe endet, wenn stop_event gesetzt ist oder das Dateiende erreicht wurde.
    """
    print("[Audio Thread] Wiedergabe gestartet.")

    ALSA_DEVICE = "plughw:3,0"  # Passe das ggf. an dein System an
    try:
        pcm = alsaaudio.PCM(alsaaudio.PCM_PLAYBACK, mode=alsaaudio.PCM_NORMAL, device=ALSA_DEVICE)
    except Exception as e:
        print("[Audio Thread] Fehler beim Öffnen des ALSA-Geräts:", e)
        return

    # Annahme: 2 Kanäle, 44100 Hz, 16-Bit (S16_LE)
    pcm.setchannels(2)
    pcm.setrate(44100)
    pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
    pcm.setperiodsize(1024)

    try:
        process = subprocess.Popen(
            ["mpg123", "-q", "--stdout", config.MP3_FILE],
            stdout=subprocess.PIPE
        )
    except Exception as e:
        print("[Audio Thread] Fehler beim Starten von mpg123:", e)
        pcm.close()
        return

    # Setze die stdout-Pipe auf nichtblockierend
    fd = process.stdout.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    block_size = 1024
    while not stop_event.is_set():
        # Falls mpg123 bereits beendet ist, beenden wir die Schleife
        if process.poll() is not None:
            break
        rlist, _, _ = select.select([process.stdout], [], [], 0.1)
        if rlist:
            try:
                data = process.stdout.read(block_size)
            except Exception as e:
                print("[Audio Thread] Fehler beim Lesen von stdout:", e)
                break
            if not data:
                break
            try:
                pcm.write(data)
            except Exception as e:
                print("[Audio Thread] Fehler beim Schreiben in PCM:", e)
                break
        else:
            continue

    if stop_event.is_set():
        try:
            process.kill()
        except Exception:
            pass
    process.wait()
    pcm.close()
    print("[Audio Thread] Wiedergabe beendet.")

def servo_waving(stop_event, servo):
    print("[Servo Thread] Servo waving thread gestartet.")
    while not stop_event.is_set():
        servo.value = -0.5  # Linke Position
        print("[Servo Thread] Servo auf -0.5 (links).")
        time.sleep(0.5)
        if stop_event.is_set():
            break
        servo.value = 0.5   # Rechte Position
        print("[Servo Thread] Servo auf 0.5 (rechts).")
        time.sleep(0.5)
    servo.value = None
    print("[Servo Thread] Stop-Event erkannt, Servo deaktiviert. Thread beendet.")

def stop_servo_waving():
    global servo_thread
    if servo_thread is not None and servo_thread.is_alive():
        print("[Main] Stoppe Servo waving thread.")
        servo_stop_event.set()
        servo_thread.join()
        servo_thread = None
        servo.value = None
        print("[Main] Servo waving thread gestoppt und Servo deaktiviert.")

def button_callback():
    global alarm_triggered, button_pressed_flag, button_pressed_time
    global audio_thread, audio_stop_event, alarm_audio_started
    print("[Callback] Button gedrückt.")
    button_pressed_flag = True
    button_pressed_time = time.time()
    
    # Falls Alarm aktiv ist, deaktiviere ihn und stoppe den Servo-Thread
    if alarm_triggered:
        alarm_triggered = False
        print("[Callback] Alarm durch Button deaktiviert.")
        stop_servo_waving()
    
    # Audio-Wiedergabe toggeln: Wenn Audio läuft, stoppen; ansonsten starten.
    if audio_thread is None or not audio_thread.is_alive():
        print("[Callback] Starte Audio Wiedergabe (manuell).")
        # Benutzerstart überschreibt den Alarmstart
        alarm_audio_started = False
        audio_stop_event.clear()
        audio_thread = threading.Thread(target=play_audio, args=(audio_stop_event,))
        audio_thread.start()
    else:
        print("[Callback] Stoppe Audio Wiedergabe.")
        audio_stop_event.set()
        audio_thread.join()
        audio_thread = None

button.when_pressed = button_callback

while True:
    now = datetime.now()
    time_str = now.strftime('%H:%M:%S')
    hour = now.hour

    # Gruß basierend auf der Uhrzeit bestimmen
    if 6 <= hour < 10:
        greeting = "Guten Morgen"
    elif 10 <= hour < 14:
        greeting = "Guten Mittag"
    elif 14 <= hour < 18:
        greeting = "Guten Tag"
    elif 18 <= hour < 21:
        greeting = "Guten Abend"
    else:
        greeting = "Gute Nacht"

    # Alarmprüfung (nur einmal pro Tag)
    if config.ALARM_ENABLED and not alarm_triggered:
        if now.hour == config.ALARM_HOUR and now.minute == config.ALARM_MINUTE and (last_alarm_day != now.day):
            alarm_triggered = True
            last_alarm_day = now.day
            print(f"[Main] Alarm ausgelöst um {time_str}.")

    # Automatisch Audio starten, wenn Alarm erreicht ist und noch nicht gestartet wurde
    if alarm_triggered and not alarm_audio_started:
        if audio_thread is None or not audio_thread.is_alive():
            print("[Main] Starte Alarm-Audio Wiedergabe.")
            audio_stop_event.clear()
            audio_thread = threading.Thread(target=play_audio, args=(audio_stop_event,))
            audio_thread.start()
            alarm_audio_started = True

    # LCD: Zeile 0 zeigt die aktuelle Uhrzeit
    lcd.cursor_pos = (0, 0)
    lcd.write_string(time_str.center(config.LCD_COLS))
    
    # LCD: Zeile 1 zeigt "Hi Tiago" (bei Buttondruck), "ALARM!" oder den Gruß
    if button_pressed_flag:
        line1 = "Hi Tiago".center(config.LCD_COLS)
        if time.time() - button_pressed_time >= 2:
            button_pressed_flag = False
    elif alarm_triggered:
        line1 = "     ALARM!    "
    else:
        line1 = greeting.center(config.LCD_COLS)
    lcd.cursor_pos = (1, 0)
    lcd.write_string(line1)
    
    # Wenn Alarm aktiv ist und der Servo-Thread nicht läuft, starte ihn
    if alarm_triggered and (servo_thread is None or not servo_thread.is_alive()):
        print("[Main] Starte Servo waving thread.")
        servo_stop_event.clear()
        servo_thread = threading.Thread(target=servo_waving, args=(servo_stop_event, servo))
        servo_thread.start()

    time.sleep(0.1)
