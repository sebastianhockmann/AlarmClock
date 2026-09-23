"""Kurzer Klick-Ton als akustisches Feedback fuer Tastendruecke.

Laeuft ueber `aplay` als eigener, kurzlebiger Prozess statt ueber die
AudioPlayer-Klasse aus audio.py: die stoppt vor jedem play() das laufende
Stueck, ein Klick wuerde also Alarm/Musik unterbrechen. `plughw:3,0` (siehe
config.ALSA_DEVICE) erlaubt aber ohnehin nur einen Besitzer gleichzeitig -
laeuft schon etwas, schlaegt aplay mit "device busy" fehl und wird ignoriert;
der Klick faellt dann eben aus, statt den Wecker zu stoeren.
"""
import subprocess
import config

CLICK_SOUND = config.BASE_DIR / 'sounds' / 'click.wav'


def play_click():
    try:
        subprocess.Popen(
            ['aplay', '-q', '-D', config.ALSA_DEVICE, str(CLICK_SOUND)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
