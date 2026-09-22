"""MP3 playback through ALSA via mpg123's remote-control mode.

Remote mode (-R) keeps one mpg123 process reachable over stdin (LOAD/VOLUME/
QUIT), which is what makes live volume changes during playback possible;
mpg123 still negotiates the source audio format itself. Relative paths are
resolved against the project directory.
"""
from pathlib import Path
import subprocess
import threading
import config

# mpg123 remote-control play states reported on "@P n" status lines.
STATE_STOPPED, STATE_PAUSED, STATE_PLAYING = 0, 1, 2


class AudioPlayer:
    def __init__(self, device=None):
        self.device = device or config.ALSA_DEVICE
        self.process = None
        self._lock = threading.RLock()
        self._state = STATE_STOPPED
        self._volume = 100

    @property
    def is_playing(self):
        with self._lock:
            return self.process is not None and self.process.poll() is None and self._state == STATE_PLAYING

    @property
    def volume(self):
        return self._volume

    def play(self, filename):
        path = Path(filename)
        if not path.is_absolute():
            path = config.BASE_DIR / path
        if not path.is_file():
            raise FileNotFoundError(path)
        with self._lock:
            self.stop()
            self.process = subprocess.Popen(
                ['mpg123', '-q', '-R', '-o', 'alsa', '-a', self.device],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
            self._state = STATE_STOPPED
            threading.Thread(target=self._read_status, args=(self.process,), daemon=True).start()
            self._send(f'SILENCE\nVOLUME {self._volume}\nLOAD {path}')

    def set_volume(self, percent):
        percent = max(0, min(100, int(percent)))
        with self._lock:
            self._volume = percent
            self._send(f'VOLUME {percent}')
        return percent

    def _send(self, commands):
        if self.process is not None and self.process.stdin is not None:
            try:
                self.process.stdin.write(commands + '\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def _read_status(self, process):
        try:
            for line in process.stdout:
                if line.startswith('@P '):
                    with self._lock:
                        if self.process is process:
                            self._state = int(line.split()[1])
        except (OSError, ValueError):
            pass

    def stop(self):
        with self._lock:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
                self.process = None
                self._state = STATE_STOPPED
