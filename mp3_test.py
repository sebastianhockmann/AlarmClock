#!/usr/bin/env python3

import sys
import alsaaudio
from pydub import AudioSegment

# Hinweis: ggf. den ALSA-Gerätenamen anpassen
ALSA_DEVICE = "plughw:3,0"

def main():
    if len(sys.argv) < 2:
        print(f"Aufruf: {sys.argv[0]} <m4a-datei>")
        sys.exit(1)

    m4a_file = sys.argv[1]

    # 1) M4A-Datei mit pydub einlesen und dekodieren
    try:
        # Format explizit angeben, falls nötig:
        audio = AudioSegment.from_file(m4a_file, format="m4a")
    except Exception as e:
        print("Fehler beim Einlesen der M4A-Datei:", e)
        sys.exit(1)

    # Parameter aus dem AudioSegment auslesen
    channels = audio.channels           # z.B. 2 bei Stereo
    sample_width = audio.sample_width   # z.B. 2 bei 16-Bit
    frame_rate = audio.frame_rate       # z.B. 44100 Hz
    raw_data = audio.raw_data           # dekodierte PCM-Daten

    # 2) ALSA-Ausgabegerät öffnen
    try:
        pcm = alsaaudio.PCM(type=alsaaudio.PCM_PLAYBACK,
                            mode=alsaaudio.PCM_NORMAL,
                            device=ALSA_DEVICE)
    except Exception as e:
        print("Fehler beim Öffnen des ALSA-Geräts:", e)
        sys.exit(1)

    # 3) ALSA-Parameter setzen: Kanäle, Abtastrate, Format
    pcm.setchannels(channels)
    pcm.setrate(frame_rate)

    # Sample-Width -> ALSA-Format
    if sample_width == 1:
        pcm.setformat(alsaaudio.PCM_FORMAT_U8)
    elif sample_width == 2:
        pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
    else:
        print(f"Das Beispiel unterstützt aktuell keine {sample_width*8}-Bit-Daten.")
        sys.exit(1)

    # Optional: Puffergröße konfigurieren
    pcm.setperiodsize(1024)

    # 4) PCM-Daten in kleinen Blöcken an ALSA senden
    block_size = 1024
    for i in range(0, len(raw_data), block_size):
        chunk = raw_data[i : i + block_size]
        written = pcm.write(chunk)
        if written < 0:
            print("Fehler beim Schreiben in ALSA-Device.")
            break

    print("Wiedergabe beendet.")

if __name__ == "__main__":
    main()
