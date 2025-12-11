import threading
import subprocess
import time
import alsaaudio
from log import log
import config

class AudioPlayer:
    def __init__(self, device=None):
        self.device = device or config.ALSA_DEVICE
        self.thread = None
        self.stop_event = threading.Event()

    def _play_thread(self, filename):
        log("[Audio] Starte Wiedergabe:", filename)

        try:
            pcm = alsaaudio.PCM(
                alsaaudio.PCM_PLAYBACK,
                alsaaudio.PCM_NORMAL,
                device=self.device
            )
            pcm.setchannels(2)
            pcm.setrate(44100)
            pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            pcm.setperiodsize(1024)
        except Exception as e:
            log("[Audio] Fehler beim Öffnen des ALSA-Geräts:", e)
            return

        try:
            process = subprocess.Popen(
                ["mpg123", "-q", "--stdout", filename],
                stdout=subprocess.PIPE
            )
        except Exception as e:
            log("[Audio] mpg123 Fehler:", e)
            return

        while not self.stop_event.is_set():
            data = process.stdout.read(1024)
            if not data:
                break
            try:
                pcm.write(data)
            except Exception as e:
                log("[Audio] PCM Fehler:", e)
                break

        # Clean up
        try:
            process.kill()
        except:
            pass

        log("[Audio] Wiedergabe beendet")

    def play(self, filename):
        # Laufende Wiedergabe stoppen
        self.stop()

        # neuen Thread starten
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._play_thread, args=(filename,), daemon=True)
        self.thread.start()

    def stop(self):
        if self.thread and self.thread.is_alive():
            log("[Audio] Stoppe aktuelle Wiedergabe…")
            self.stop_event.set()
            self.thread.join(timeout=0.5)
        self.thread = None
