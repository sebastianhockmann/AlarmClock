# audio.py
import alsaaudio
import subprocess
import fcntl
import os
import select
import threading
import time
import struct
import config

# Fade-Dauern
FADE_IN_TIME = 3.0
FADE_OUT_TIME = 2.0

# PCM-Parameter
CHANNELS = 2
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
FRAME_SIZE = CHANNELS * SAMPLE_WIDTH
FRAMES_PER_BLOCK = 1024
BLOCK_SIZE = FRAMES_PER_BLOCK * FRAME_SIZE


class AudioPlayer:
    def __init__(self, device=None):
        self.device = device or config.ALSA_DEVICE
        self.thread = None
        self.stop_event = threading.Event()
        self.fade_out_event = threading.Event()

    def _apply_volume(self, pcm_bytes, volume):
        """Skaliert PCM-Daten (Signed 16-bit little endian)."""
        if volume >= 0.999:
            return pcm_bytes

        sample_count = len(pcm_bytes) // SAMPLE_WIDTH
        samples = struct.unpack("<" + "h" * sample_count, pcm_bytes)

        scaled = [int(s * volume) for s in samples]
        return struct.pack("<" + "h" * sample_count, *scaled)

    def _player_thread(self, filename):
        print(f"[Audio] Starte: {filename} (Fade-In)")

        try:
            pcm = alsaaudio.PCM(
                alsaaudio.PCM_PLAYBACK,
                mode=alsaaudio.PCM_NORMAL,
                device=self.device
            )
        except Exception as e:
            print("[Audio] Fehler Öffnen PCM:", e)
            return

        pcm.setchannels(CHANNELS)
        pcm.setrate(44100)
        pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
        pcm.setperiodsize(FRAMES_PER_BLOCK)

        # mpg123 Start
        process = subprocess.Popen(
            ["mpg123", "-q", "--stdout", filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # stdout nonblocking
        fd = process.stdout.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        start_time = time.time()

        while not self.stop_event.is_set():
            if process.poll() is not None:
                break

            r, _, _ = select.select([process.stdout], [], [], 0.05)
            if not r:
                continue

            data = process.stdout.read(BLOCK_SIZE)
            if not data:
                break

            # FADE IN
            t = time.time() - start_time
            if t < FADE_IN_TIME:
                volume = t / FADE_IN_TIME
            else:
                volume = 1.0

            # FADE OUT
            if self.fade_out_event.is_set():
                elapsed = time.time() - self.fade_start
                remaining = max(0.0, 1.0 - (elapsed / FADE_OUT_TIME))
                volume = min(volume, remaining)
                if remaining <= 0.0:
                    break

            data = self._apply_volume(data, volume)

            try:
                pcm.write(data)
            except Exception:
                break

        # mpg123 beenden
        try:
            process.kill()
        except:
            pass
        process.wait()

        pcm.close()
        print("[Audio] Wiedergabe beendet.")

    # ---------------------------------------------------
    # Public API
    # ---------------------------------------------------

    def play(self, filename):
        self.stop()  # laufende Wiedergabe beenden
        self.stop_event.clear()
        self.fade_out_event.clear()
        self.thread = threading.Thread(
            target=self._player_thread,
            args=(filename,),
            daemon=True
        )
        self.thread.start()

    def stop(self):
        if self.thread and self.thread.is_alive():
            print("[Audio] Fade-Out ...")
            self.fade_start = time.time()
            self.fade_out_event.set()
            self.thread.join()
        self.thread = None

    def toggle(self):
        if self.thread and self.thread.is_alive():
            self.stop()
        else:
            from scheduler import get_today_wake_item
            item = get_today_wake_item()
            self.play(item["file"])
