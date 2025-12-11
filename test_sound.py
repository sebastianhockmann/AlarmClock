#!/usr/bin/env python3
# test_sound.py
#
# Testet Fade-In und Fade-Out unabhängig vom Hauptprogramm.

import time
import config
from audio import AudioPlayer


def main():
    print("=== SOUND TEST START ===")

    player = AudioPlayer()

    # Default-Song aus config.py laden
    filename = getattr(config, "DEFAULT_SONG", "mp3/happy.mp3")
    print(f"Starte Fade-In Test mit Datei: {filename}")

    # Fade-In + Start
    player.play(filename)

    # 10 Sekunden Musik laufen lassen
    time.sleep(10)

    print("Starte Fade-Out Test...")
    player.stop()

    print("=== SOUND TEST ENDE ===")


if __name__ == "__main__":
    main()
