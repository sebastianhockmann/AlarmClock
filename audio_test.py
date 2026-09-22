"""MP3-Wiedergabe ueber AudioPlayer/mpg123 (ALSA) hoerbar testen.

Spielt eine Testdatei ueber das im Projekt genutzte ALSA-Geraet ab, damit
sich Verkabelung/Kartenwahl ohne den vollen Wecker-Ablauf pruefen lassen.
Verfuegbare Geraete auflisten: aplay -l

Start (Standarddatei aus config.py, Standardgeraet):
    .venv/bin/python audio_test.py
Beispiel mit anderer Datei/Geraet/Lautstaerke/Dauer:
    .venv/bin/python audio_test.py --file mp3/xmas/jingle_bells..mp3 \\
        --device plughw:3,0 --volume 60 --duration 5
Ende vor Ablauf der Dauer: Strg+C.
"""

import argparse
import sys
import time

import config
from audio import AudioPlayer


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=config.DATE_SONGS[0]["file"],
                        help="MP3-Datei, absolut oder relativ zum Projektverzeichnis")
    parser.add_argument("--device", default=config.ALSA_DEVICE,
                        help="ALSA-Geraet, z. B. plughw:3,0 (siehe aplay -l)")
    parser.add_argument("--volume", type=int, default=80,
                        help="Lautstaerke in Prozent (0-100)")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="Wiedergabedauer in Sekunden, 0 = bis Dateiende/Strg+C")
    args = parser.parse_args()
    if not 0 <= args.volume <= 100:
        parser.error("Lautstaerke muss zwischen 0 und 100 liegen")
    if args.duration < 0:
        parser.error("Dauer darf nicht negativ sein")

    player = AudioPlayer(device=args.device)
    print(f"Geraet: {args.device}")
    print(f"Datei: {args.file}")
    print(f"Lautstaerke: {args.volume}%")
    try:
        player.play(args.file)
    except FileNotFoundError as error:
        print(f"Datei nicht gefunden: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"mpg123 liess sich nicht starten: {error}. Installiert? (sudo apt install mpg123)",
              file=sys.stderr)
        return 1
    player.set_volume(args.volume)
    time.sleep(0.3)  # mpg123 braucht einen Moment, bis der erste Statuswert eintrifft.

    print("Wiedergabe gestartet. Ende: Strg+C." if args.duration == 0
          else f"Wiedergabe fuer {args.duration:g}s. Vorzeitig beenden: Strg+C.")
    try:
        start = time.monotonic()
        while args.duration == 0 or time.monotonic() - start < args.duration:
            if not player.is_playing:
                print("Wiedergabe beendet (Datei zu Ende oder mpg123 gestoppt).")
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
    finally:
        player.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
