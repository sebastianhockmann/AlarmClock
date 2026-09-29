#!/usr/bin/env python3
# test_sound.py
#
# Testet Fade-In und Fade-Out unabhängig vom Hauptprogramm.

import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektmodule (tools/ liegt eine Ebene tiefer)
import config
import settings
from audio import AudioPlayer


def main():
    print("=== SOUND TEST START ===")

    player = AudioPlayer()

    # Standardlied aus den Einstellungen (Weboberflaeche) laden
    filename = settings.get("music")["default_song"]
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
