# Raspberry-Pi-Wecker mit WLED

Lichtwecker für den Raspberry Pi: I2C-LCD (Uhrzeit + Spruch), MP3-Wiedergabe
über ALSA (`mpg123`), WLED-LED-Streifen über HTTP, zwei Drehencoder und ein
4×4-Tastenfeld über I2C, Weboberfläche zum Einstellen. Tasten lassen sich frei
belegen – mit Lichteffekten, Musik, Wetter, Alexa, Home Assistant oder
beliebigen HTTP-Aufrufen.

## Überblick

| Was | Wo |
|---|---|
| Weckzeiten (mehrere, je Wochentag) | Weboberfläche → **Wecker** |
| Weckprogramm (Licht-Sonnenaufgang, leise startende Musik, Ende nach dem Lied, Schlummern) | Weboberfläche → **Weckprogramm** |
| Tastenbelegung | Weboberfläche → **Tasten** |
| MP3s, Lieder für bestimmte Tage, Rotation | Weboberfläche → **Musik** |
| WLED-Host, Effektbibliothek | Weboberfläche → **Licht** |
| Alexa, Home Assistant, Wetter-Ort | Weboberfläche → **Smart Home** |
| Begrüßungstexte und Display-Licht je Uhrzeit | Weboberfläche → **Anzeige** |
| Hardware (I2C-Adressen, ALSA-Gerät, Ports) | `config/hardware.json` (von Hand) |

## Konfiguration: der Ordner `config/`

| Datei | Inhalt | Versioniert | Wer schreibt |
|---|---|---|---|
| `config/hardware.json` | LCD, I2C-Adressen, Eingabemodul, ALSA-Gerät, Web-/Steuer-Port, Pfad zum Alexa-Skript, Debug | ja | von Hand, danach Neustart |
| `config/defaults.json` | Standardwerte für alles, was die Weboberfläche ändern kann | ja | von Hand |
| `config/effects.json` | Standard-Effektbibliothek (WLED-Zustände mit numerischer `fx`-ID) | ja | von Hand |
| `config/settings.json` | Änderungen aus der Weboberfläche | **nein** (gitignored) | Weboberfläche |
| `config/__init__.py` | Lädt `hardware.json` und stellt die Werte als `config.LCD_ADDRESS` usw. bereit | ja | – |

Regeln:

- Die Weboberfläche schreibt **nur** `config/settings.json`. Objekte (z. B.
  `wake`, `wled`) werden feldweise mit `defaults.json` zusammengeführt, Listen
  (Wecker, Effekte, Begrüßungen) ersetzen den Standard komplett.
  „Standard wiederherstellen“ in der Oberfläche löscht den Abschnitt wieder aus
  `settings.json`.
- Jeder Wert wird beim Speichern geprüft (verständliche Fehlermeldung in der
  Oberfläche). Ist eine Datei später doch kaputt, fällt der Wecker **pro Feld**
  auf den Standard zurück und läuft weiter.
- Wecker und Weboberfläche lesen `defaults.json`/`settings.json`/`effects.json`
  live (Änderungszeit wird geprüft) – **kein Neustart nötig**. Nur
  `hardware.json` wird beim Start gelesen.
- Adressen in `hardware.json` dürfen als Text (`"0x27"`) oder Zahl stehen.
- Umgebungsvariablen haben Vorrang vor `hardware.json`: `ALARM_ALSA_DEVICE`,
  `ALARM_DEBUG=0`, `ALARM_WEB_HOST`, `ALARM_WEB_PORT`; `WLED_HOST` (Rückfall
  `WLED_URL`) ersetzt den WLED-Host aus `defaults.json`.

**Umzug alter Dateien:** Beim ersten Start übernimmt der Wecker eine alte
`settings.json` (Weckzeit, WLED) und `mp3_mapping.json` (Datum → Lied) aus dem
Projektstamm nach `config/settings.json` und benennt die alten Dateien in
`*.migrated` um.

## Installation und Start

Benötigt: Python 3.9+, `mpg123`, `aplay`, aktiviertes I2C und die Pakete aus
`requirements.txt`.

```sh
sudo apt install mpg123 python3-venv i2c-tools
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python alarm_clock.py     # Wecker (braucht die Pi-Hardware)
.venv/bin/python webserver.py       # Weboberfläche zum Entwickeln, Port 8080
```

Dauerbetrieb siehe [systemd + nginx](#dauerhafter-betrieb-systemd--nginx).

## Architektur

Zwei Prozesse:

| Prozess | Einstieg | Aufgabe |
|---|---|---|
| Wecker | `alarm_clock.py` | 20-ms-Hauptschleife: Wecker prüfen, Eingaben abarbeiten, LCD |
| Weboberfläche | `webserver.py` (Flask) | Einstellungen, MP3-Verwaltung, Tests |

Die Weboberfläche spielt **selbst nichts ab**. Abspielen, Tasten testen,
Weck-Test und Lautstärke schickt sie über einen lokalen UDP-Steuerkanal
(`ipc.py`, `127.0.0.1:8099`) an den Wecker. So gibt es genau einen Besitzer
für Audio, LCD und WLED (früher kollidierten Web-Vorhören und Wecker am
ALSA-Gerät). Läuft der Wecker nicht, meldet die Oberfläche das oben rechts.

Module:

- `config/` – Konfiguration (siehe oben), `settings.py` – Laden/Prüfen/Speichern
  der web-editierbaren Einstellungen, Umzug alter Dateien.
- `scheduler.py` – `AlarmScheduler` (wann welcher Wecker fällig ist, Licht-Vorlauf,
  einmal pro Datum), nächster Wecker, Liedauswahl, Begrüßung.
- `wake.py` – `WakeSession`: ein laufender Weckvorgang (Licht- und
  Lautstärkerampe, Ende nach dem Lied, Schlummern).
- `controller.py` – `ClockController`: Lebenszyklus des Weckvorgangs und alle
  Eingabe-Ereignisse inkl. Tastenaktionen. Hardwareunabhängig, voll getestet.
- `integrations.py` – HTTP-Aufrufe, Home Assistant, Alexa (im Hintergrund-Thread).
- `weather.py` – Wetter von Open-Meteo fürs LCD.
- `ipc.py` – Steuerkanal Weboberfläche → Wecker.
- `lighting.py` – `WLEDManager` (Hintergrund-Thread, Warteschlange behält nur
  den neuesten Befehl), `EffectBrowser` (alle Geräteeffekte am linken Knopf).
- `audio.py` – `mpg123 -R`; Lautstärke live, erkennt Liedende.
- `controls_mcp.py` – Drehencoder (MCP23017) und Tastenfeld (PCF8574).
- `lcd.py`, `chime.py` (Klickton), `button.py` (alter GPIO-Taster, aus).
- `tools/` – Hardware-Testskripte (`encoder_test.py`, `keypad_test.py`,
  `wled_effect_list.py`, …), nicht Teil der Tests. Aufruf aus dem Projektordner,
  z. B. `.venv/bin/python tools/wled_effect_list.py --search sun`.

Grundsätze: Module importieren keine Hardware (LCD erst in `main()`);
Netzwerk und I2C laufen in Hintergrund-Threads, nur die Hauptschleife ändert
LCD und Zustand; jeder Hardware-/Netzwerkfehler wird gemeldet, der Wecker läuft
weiter.

## Wecker und Weckprogramm

**Wecker:** beliebig viele, jeweils mit Uhrzeit, Name und Wochentagen
(z. B. „Schule“ Mo–Fr 06:15, „Wochenende“ Sa+So 08:00). Der Schalter
„Wecker aktiv“ in der Übersicht pausiert alle (Urlaub). Jeder Wecker löst pro
Datum einmal aus; die Sperre gilt bis zum Neustart – ein Neustart innerhalb
der Weckminute kann erneut auslösen, verpasste Termine werden nicht nachgeholt.

**Weckprogramm** (gilt für alle Wecker):

1. *Licht-Vorlauf* (optional, 0–60 min vor der Weckzeit): der gewählte Effekt
   startet mit „Helligkeit Start“ und wird über „Heller werden über“ Minuten
   bis „Helligkeit Ende“ heller. Alle 2 s geht ein neuer Helligkeitswert mit
   WLED-Überblendung (`tt`) raus, dadurch wirkt es weich. Jeder Schritt enthält
   den vollen Effektzustand, ein verlorenes Paket schadet also nicht.
   Standard-Effekt „Morgenlicht“ (warmes Orange).
2. *Musik* zur Weckzeit: Tageslied, Zufallssong oder keine (nur Licht).
   Beginnt mit „Lautstärke Start“ und wird über „Lauter werden über“ Sekunden
   bis „Lautstärke Ende“ lauter. Dreht man am rechten Knopf, endet die Rampe –
   die Hand hat Vorrang.
3. *Ende:* wenn das Lied vorbei ist (oder: Lied wiederholen), spätestens nach
   „Spätestens aus nach“ Minuten. Danach wird das Licht ausgeblendet oder bleibt
   an („Licht danach“).
4. *Schlummern:* Standardmäßig bedeutet **jede Taste** des Tastenfelds während
   des Weckens „Schlummern“ (9 min); das LCD zählt herunter, das Licht bleibt an,
   danach startet die Musik neu. Der **rechte Knopf** beendet den Wecker.
   Drückt man ihn schon im Licht-Vorlauf, fällt die Musik für heute aus.

Der Ablauf wird in der Oberfläche als Zeitleiste angezeigt; „Jetzt testen“
startet das Programm sofort (ohne Vorlauf).

**Liedauswahl „Tageslied“:** konkretes Datum (`2026-12-24`) → jährliches Datum
(`12-24`) → tägliche Rotation → Standardlied. „Zufallssong“ wählt aus allen
MP3s im Ordner `mp3/` (inkl. Unterordnern). Der Spruch erscheint im LCD.

## Bedienung am Gerät

| Element | Funktion |
|---|---|
| Links drehen | alle WLED-Effekte live durchblättern (`12/187 Aurora`); schnell drehen springt (`effect_fast_*` in `hardware.json`) |
| Links drücken | Licht an/aus |
| Rechts drehen | Lautstärke (Schrittweite `audio.volume_step`) |
| Rechts drücken | Wecker aus / Musik an/aus (Tageslied) |
| Rechts 2 s halten | „Alles normal“: Musik aus, Licht an, Display wieder automatisch |
| Tastenfeld | frei belegbar (Weboberfläche → Tasten), mit Klickton |

### Tastenaktionen

| Typ | Wirkung |
|---|---|
| Lichteffekt | Effekt aus der Bibliothek an WLED |
| Licht an/aus | umschalten, an oder aus |
| Musik | Zufallssong, Tageslied, an/aus, stopp |
| Wetter im Display | Wetterbericht in Zeile 2 (Open-Meteo) |
| Display an/aus | LCD-Hintergrundlicht manuell |
| Schlummern | wie oben |
| Wecker an/aus | alle Wecker pausieren/aktivieren |
| Weckprogramm testen | Weckprogramm sofort starten |
| Alexa (Sprachbefehl) | Befehl an ein bestimmtes Echo, siehe unten |
| HTTP-Aufruf | GET/POST an eine URL (Alexa-Routine-Trigger, Voice Monkey, IFTTT, HA-Webhook …) |
| Home Assistant | Service-Aufruf, z. B. `light.toggle` auf `light.deckenlampe` |

Jede Aktion hat einen optionalen Anzeige-Text fürs LCD. Externe Aktionen laufen
im Hintergrund; schlagen sie fehl, erscheint die Fehlermeldung im LCD. In der
Oberfläche testet „Am Wecker testen“ die Taste wie echt gedrückt, „Direkt
testen“ ruft externe Aktionen aus der Oberfläche auf und zeigt das Ergebnis.

**Vorschlag für die Belegung (Standard):**

```
 1 Solid       2 Breathe      3 Colorloop    A Deckenlampe (Smart Home)
 4 Rainbow     5 Theater      6 Chase Rainb. B Amazon Music (Alexa)
 7 Candle      8 Fire 2012    9 Twinklefox   C Wetter im Display
 * Zufallssong 0 Licht aus    # Musik-Licht  D Display an/aus
```

Die Zahlen bleiben Lieblingseffekte (leicht zu merken für Kinder), die
Buchstabenspalte ist „Haus & Info“. `#` ist ein Effekt, der aufs Mikrofon
reagiert – zusammen mit `*` (Zufallssong) ergibt das eine kleine Disco.
Weitere sinnvolle Belegungen: „Einschlaflicht“ (Candle, geringe Helligkeit)
plus Alexa-Routine „Einschlafgeräusche“, „Wecker an/aus“ fürs Wochenende,
„Alexa → Wetterbericht“ statt der LCD-Anzeige.

## Alexa

Echo-Geräte haben **keine lokale Schnittstelle**. Eine IP-Adresse hilft deshalb
nicht – gesteuert wird immer über die Amazon-Cloud, und das Zielgerät wird über
seinen **Namen** aus der Alexa-App gewählt (z. B. „Echo Kinderzimmer“). So
unterscheidet man auch die beiden Alexas.

Wer trotzdem die IP braucht (z. B. für eine feste DHCP-Zuweisung): Alexa-App →
Geräte → Echo & Alexa → Gerät → Info zeigt die MAC-Adresse; in der
Router-Oberfläche (Fritzbox: Heimnetz → Netzwerk) steht die zugehörige IP.
Auf dem Pi listet `ip neigh` bzw. `sudo nmap -sn 10.150.1.0/24` die Geräte im
Netz (Hersteller „Amazon Technologies“).

Drei Wege, per Taste Alexa zu steuern:

1. **HTTP-Aufruf → Alexa-Routine** (empfohlen, kein Login auf dem Pi):
   Skill „URL Routine Trigger“ oder „Voice Monkey“ in der Alexa-App aktivieren,
   dort einen Auslöser anlegen (erscheint in der App als Gerät/Türklingel).
   Dann in der Alexa-App eine Routine bauen: *Wenn* Auslöser → *Aktion* z. B.
   „Musik: Amazon Music, Playlist X auf Echo Kinderzimmer“, „Smart Home:
   Deckenlampe an“ oder „Wetter“. Die Trigger-URL bei der Taste als
   HTTP-Aufruf (GET) eintragen. Die URL enthält ein Geheimnis – nicht teilen.
2. **Alexa (Sprachbefehl)** über
   [alexa-remote-control](https://github.com/thorsten-gehrig/alexa-remote-control):
   schickt Befehle wie gesprochen an ein bestimmtes Echo („spiele Amazon Music“,
   „schalte die Deckenlampe an“), außerdem Routinen per Name, Vorlesen und
   Wetterbericht. Einrichtung:
   ```sh
   cd /home/pi && git clone https://github.com/thorsten-gehrig/alexa-remote-control.git
   sudo apt install jq
   # Refresh-Token einmalig mit alexa-cookie-cli erzeugen (siehe README des Projekts)
   # und oben im Skript eintragen: REFRESH_TOKEN, AMAZON='amazon.de',
   # ALEXA='alexa.amazon.de', LANGUAGE='de-DE'
   alexa-remote-control/alexa_remote_control.sh -a          # Geräte auflisten
   alexa-remote-control/alexa_remote_control.sh -d "Echo Kinderzimmer" -e speak:"Hallo"
   ```
   Pfad steht in `config/hardware.json` → `alexa.script` (absichtlich nicht in
   der Weboberfläche). „Geräte abfragen“ unter Smart Home füllt die Namensliste.
   Das Token ist ein Amazon-Zugang – die Datei gut schützen (`chmod 600`).
3. **Home Assistant** mit der Integration „Alexa Media Player“ (HACS) –
   dann ist jedes Echo ein `media_player` und die Deckenlampe ein `light`.

**Skills testen:** Routinen in der Alexa-App über ▶ („Abspielen“) direkt starten;
die Trigger-URL mit `curl "https://…"` aufrufen; im Terminal
`alexa_remote_control.sh -d "…" -e textcommand:"wie spät ist es"`; eigene
Skills in der Alexa Developer Console im Reiter „Test“. In der Weboberfläche
löst „Direkt testen“ die Aktion aus und zeigt HTTP-Status bzw. Fehlermeldung.

## Mikrofon am ESP32 (WLED Audio Reactive)

Der verbaute Controller (WLED 16.0.1, ESP32) hat den Usermod **AudioReactive**
bereits aktiv, mit einem I2S-Mikrofon (Typ „Generic I2S“, Pins SD 33, WS 25,
SCK 26, AGC an). Einstellen in der WLED-Oberfläche unter *Config → Usermods →
AudioReactive*: Squelch (Rauschschwelle, höher = reagiert erst bei lauteren
Geräuschen), Gain bzw. AGC, Pins. In der Info-Seite zeigt „Audio Source … peak“,
ob Ton ankommt.

Nutzen: Effekte mit Tonreaktion wählen. In der Weboberfläche unter **Licht →
Effektliste vom WLED laden** sind sie markiert (♪ = Lautstärke, ♫ = Frequenzen),
z. B. Gravimeter (132), Juggles (130), Puddlepeak (144), Ripple Peak (148),
Freqmap (155), DJ Light (159), Waterfall (140). 2D-Effekte (GEQ, Waverly …)
passen nicht zu einem einzelnen Streifen. Der Effekt „Musik (Mikrofon)“ in der
Bibliothek (Taste `#`) nutzt Gravimeter. Das Mikrofon hört die Musik aus dem
Lautsprecher des Weckers einfach mit – eine Verbindung zwischen Pi und WLED für
Audio ist nicht nötig. Alternativ könnte der Pi Audio-Sync per UDP (Port 11988)
senden; das ist nicht umgesetzt.

## Wetter

Unter **Smart Home → Wetter** den Ort suchen (Open-Meteo, kostenlos, ohne
Schlüssel), übernehmen, speichern, „Wetter abrufen“ zum Prüfen. Danach zeigt
eine Taste mit „Wetter im Display“ z. B.
`Jetzt 12C, heute 9-19C, Regenrisiko 40%, wolkig`, und im Weckprogramm kann
„Wetter im Display“ den Wetterbericht an den Weckspruch anhängen. Soll der
Wetterbericht **gesprochen** werden, eine Alexa-Aktion „Wetterbericht“ nehmen
(oder eine Routine mit Wetter per HTTP-Trigger) – Alexa kennt den Ort aus der
App und klingt besser als eine Sprachsynthese auf dem Pi.

## WLED

Host als Hostname oder IP (`wled.local`, `alarm-led.local`, `10.150.1.50`),
optional mit Port, ohne Pfad. `.local`-Namen gehen per mDNS, wenn Pi und WLED
im selben Netz sind. Timeout 0,5–30 s. Lichtbefehle laufen im Hintergrund und
blockieren nie Audio, Display oder Eingaben; bei vielen Befehlen bleibt nur der
neueste in der Warteschlange, es gibt keine Wiederholungen.

Prüfen auf dem Pi:

```sh
getent hosts wled.local
curl --max-time 3 http://wled.local/json/info
```

**Effektbibliothek:** Effekte verweisen über die numerische WLED-Effekt-ID
(`seg[0].fx`) auf das Gerät, nicht über den Namen – die Bibliothek funktioniert
also auch, wenn WLED beim Start nicht erreichbar ist. Die passende ID zeigt die
Weboberfläche (Effektliste vom WLED laden) oder
`.venv/bin/python tools/wled_effect_list.py --search aurora`. In der Oberfläche
lassen sich Name, Effekt-Nr., Helligkeit und Farbe ändern, mit 👁 direkt am
Streifen ansehen und unter „JSON“ beliebige WLED-Zustände eintragen
(Paletten, Presets `{"ps": 3}` …). Effekte, die eine Taste oder das
Weckprogramm nutzt, lassen sich nicht löschen.

## I2C-Anbindung: Drehencoder und Tastenfeld

`controls_mcp.py` (per `inputs.module` in `hardware.json`), vermessen mit
`i2cdetect -y 1` und `tools/rotary_clock.py`:

- Tastenfeld (PCF8574) `0x20`: Zeilen P0–P3, Spalten P4–P7.
- MCP23017 `0x21`: linker Encoder A/B PB6/PB7, Taster PB5; rechter Encoder
  A/B PA0/PA1, Taster PA2.
- LCD (PCF8574) `0x27`, gemeinsamer Bus 1.

Ein eigener Polling-Thread scannt Encoder und Tastenfeld; `emit()` legt nur
Ereignisse in die Warteschlange. Schlägt die Initialisierung fehl, läuft der
Wecker ohne Tastenfeld/Encoder weiter. Ein eigenes Eingabemodul muss
`open_controls(emit)` bereitstellen und ein Objekt mit `close()` liefern;
Ereignisse: `left_rotate` (±1), `left_press`, `key` ("1"…"D"),
`right_rotate`, `right_press`, `right_hold`.

## Debug-Ausgaben

`debug` in `hardware.json` (oder `ALARM_DEBUG=0`) schaltet Konsolenausgaben:
`[Eingabe]` Rohereignisse aus `controls_mcp.py`, `[Event]` Ereignis in der
Warteschlange, `[Controller]` abgeleitete Aktion, `[WLED] Sende an …` das
gesendete JSON, `[Aktion]` Ergebnis externer Aktionen. Kommt bei Tastendruck
nur `[Eingabe]`/`[Event]` und keine Aktion, liegt es an der Belegung; bleibt
auch `[Eingabe]` aus, an Verkabelung/I2C-Adresse.

## Weboberfläche

`http://<Pi-IP>/` (über nginx) bzw. beim Entwickeln `http://<Pi-IP>:8080`.
**Keine Anmeldung** – nur im vertrauenswürdigen Heimnetz betreiben, keine
Portweiterleitung ins Internet. Der Home-Assistant-Token wird nie an den
Browser zurückgegeben (leeres Feld = Token behalten); Trigger-URLs sind
dagegen sichtbar.

MP3-Upload: mehrere Dateien auf einmal, bereinigte Dateinamen, max. 32 MiB pro
Anfrage (`web.max_upload_mb`, passend zu `client_max_body_size` in nginx),
keine Überschreibung. ▶ spielt am Wecker, 🎧 im Browser. Dateien, die als
Standardlied, Datum oder Rotation verwendet werden, lassen sich nicht löschen.

JSON-API (für eigene Skripte): `GET /api/state`,
`PUT|DELETE /api/settings/<bereich>` (`alarms`, `alarms_enabled`, `wake`,
`music`, `keys`, `effects`, `wled`, `greetings`, `home_assistant`, `alexa`,
`weather`), `POST /api/control` (`{"event": "play_random"}`, `play_today`,
`play_file`, `stop_audio`, `wake_test`, `wake_stop`, `key`, `volume`),
`POST /api/action/test`, `GET /api/wled/test`, `GET /api/wled/effects`,
`GET /api/weather/test`, `GET /api/weather/search?q=Ort`.

## Dauerhafter Betrieb (systemd + nginx)

```sh
.venv/bin/pip install -r requirements.txt
sudo cp systemd/alarmclock.service systemd/alarmclock-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now alarmclock.service alarmclock-web.service

sudo apt install nginx
sudo cp nginx/alarmclock.conf /etc/nginx/sites-available/alarmclock
sudo ln -s /etc/nginx/sites-available/alarmclock /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

`alarmclock-web.service` startet `waitress-serve --host=127.0.0.1`, nach außen
zeigt nur nginx (Port 80).

```sh
sudo systemctl restart alarmclock.service alarmclock-web.service   # nach Code-Änderungen
journalctl -u alarmclock.service -f
journalctl -u alarmclock-web.service -f
```

Änderungen an `config/hardware.json` brauchen einen Neustart der Dienste,
alles aus der Weboberfläche nicht.

## Prüfung

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q *.py config tools
```

Die Tests brauchen keine Hardware: Einstellungen werden in ein
Temp-Verzeichnis umgeleitet, Audio/WLED/HTTP/Alexa gemockt. Nebenbei prüfen
sie, dass `config/defaults.json` und `config/effects.json` gültig sind und alle
eingetragenen MP3s existieren.

### GPIO-Taster: fehlender Treiber beim Start

Der alte GPIO17-Taster ist abgeschaltet (`inputs.legacy_button_enabled`).
Wird er eingeschaltet und fehlt ein GPIO-Treiber (`No module named 'lgpio'`,
`/sys/class/gpio/gpio17/value: Invalid argument`), meldet der Wecker das und
läuft ohne Taster weiter. Abhilfe: `.venv/bin/pip install lgpio` und
`GPIOZERO_PIN_FACTORY=lgpio`
([GPIOZero Pin-Factories](https://gpiozero.readthedocs.io/en/stable/api_pins.html)).
