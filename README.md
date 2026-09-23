# Raspberry-Pi-Wecker mit WLED

## Analyse und aktueller Stand

Der Ausgangsstand war ein Weihnachtswecker mit einem GPIO-Taster, I2C-LCD,
USB/ALSA-Audio und Servo. WLED, zwei Drehtaster und ein Tastenfeld waren noch
nicht implementiert. Der Alarmimpuls wurde im nächsten Schleifendurchlauf
als Alarmende interpretiert: Die Wiedergabe stoppte nach etwa 0,1 Sekunden.

Jetzt trennt `controller.py` Auslösung und Alarmdauer. Der Alarm bleibt bis
zum Stoppen oder maximal `ALARM_DURATION_SECONDS` aktiv. Das Lied wird einmal
abgespielt, der Spruch bleibt für die Alarmdauer sichtbar. Der Termin wird pro
vollständigem Datum einmal ausgelöst; diese Sperre gilt nur bis zum Neustart.
Ein Neustart innerhalb der Weckminute kann erneut auslösen. Verpasste Termine
werden nicht nachgeholt. Uhrzeit und Zeitzone des Pi müssen korrekt sein.

`audio.py` startet mpg123 im Fernsteuerungsmodus (`-R`) mit ALSA. Dadurch
übernimmt mpg123 die Formatbehandlung auch bei unterschiedlichen Abtastraten
und Kanalzahlen, und die Lautstärke lässt sich per `VOLUME`-Kommando über
stdin ändern, während ein Titel läuft (`set_volume()`, rechter Drehknopf).
`SILENCE` unterdrückt dabei den sonst sehr häufigen `@F`-Fortschritts-Spam;
ein Hintergrund-Thread liest die `@P`-Statuszeilen für `is_playing`.
Stoppen beendet und wartet auf den Prozess; relative Musikpfade beziehen sich
auf das Projektverzeichnis. `lcd.py` schreibt nur geänderte Zeilen. Lange
Sprüche laufen durch die zweite Zeile, die erste zeigt die Uhrzeit.
Der frühere Servo und Watchdog sind nicht mehr in den Startpfad eingebunden;
ihre alten Dateien und Hardware-Testskripte bleiben als Referenz erhalten.

## Konfiguration und Start

Benötigt werden Python 3.9+, `mpg123`, aktiviertes I2C und die Python-Pakete
aus `requirements.txt`. GPIOZero ist nur für den bisherigen GPIO-Taster nötig.
Installation beispielsweise in einer eigenen Python-Umgebung:

```sh
sudo apt install mpg123 python3-venv i2c-tools
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python alarm_clock.py
```

In `config.py` festlegen:

- `ALARM_HOUR`, `ALARM_MINUTE`, `ALARM_ENABLED`, `ALARM_DURATION_SECONDS`.
  Stunde, Minute und Aktiv-Status lassen sich auch über die Weboberfläche
  ändern; sie überschreiben dann diese Defaults (gespeichert in `settings.json`).
- `WEB_HOST` (Standard `0.0.0.0`), `WEB_PORT` (Standard `8080`) für die
  Weboberfläche; überschreibbar per `ALARM_WEB_HOST`/`ALARM_WEB_PORT`.
- `WAKE_ITEMS`: Musik und Spruch, täglich zyklisch. Mindestens zwei verschiedene
  Dateien eintragen. Die vorhandenen Weihnachtslieder dienen als Startbibliothek.
- `DATE_SONGS`: feste jährliche Ausnahmen. Diese haben Vorrang vor der Rotation.
  Explizite Datumszuordnungen können Wiederholungen an benachbarten Tagen erzeugen.
- `LCD_ADDRESS`, `LCD_I2C_PORT`, `LCD_COLS=16`, `LCD_ROWS=2`.
- `ALSA_DEVICE`: vorhandener Standard `plughw:3,0`; mit `aplay -l` prüfen.
  Ein stabiler ALSA-Kartenname ist besser als eine wechselnde Kartennummer.
  Überschreiben ohne Codeänderung mit `ALARM_ALSA_DEVICE`.
- `WLED_HOST`: Hostname oder IP des WLED-Controllers, z. B. `alarm-led.local` oder `192.168.178.50`.
- `WLED_TIMEOUT_SECONDS`: HTTP-Timeout in Sekunden, Standard 3.
- `WLED_ENABLED`: aktiviert/deaktiviert den Controller.
- `ALARM_EFFECT`: optional die ID eines Effekts beim Wecken.
  Alarmende/Stoppen beendet Audio, lässt die Lichtszene bestehen.

Fehlende Dateien/Decoder werden gemeldet, ein Audio-Startfehler erscheint am LCD.
Spätere Decoder- oder ALSA-Fehler erscheinen in stderr; es gibt noch keinen
akustischen Ersatzalarm. Das System vor Verwendung als Wecker am Gerät testen.

## WLED

Der AlarmClock kann einen WLED-Controller über Hostname oder IP ansprechen.

Empfohlen:

- `alarm-led.local`

Alternativ:

- `wled.local`
- `192.168.x.x`

`.local`-Hostnamen funktionieren per mDNS, wenn Raspberry Pi und WLED im selben lokalen Netzwerk sind. Der Pi löst den Namen über das Betriebssystem auf; keine eigene mDNS-Implementierung oder harte IP-Kodierung ist nötig.

Die Defaults stehen ausschließlich in `config.py`: aktiv, `wled.local`, 3 Sekunden.
Die bestehende `settings.json` überschreibt diese Werte im Abschnitt `wled`:

```json
{
  "hour": 6,
  "minute": 15,
  "wled": {
    "enabled": true,
    "host": "alarm-led.local",
    "timeout": 3
  }
}
```

`WLED_HOST` aus der Umgebung kann den Default überschreiben; das bisherige
`WLED_URL` wird als Rückfall für den Host weiterhin eingelesen. Gespeicherte
Einstellungen haben Vorrang. `http://` ist optional, ein optionaler Port bleibt
erhalten. API-Pfade werden ausschließlich im `WLEDManager` ergänzt.
Der Timeout darf 0,5–30 Sekunden betragen. Er begrenzt Socket-Operationen;
die Dauer der Namensauflösung bestimmt das Betriebssystem. Lichtbefehle laufen
deshalb im Hintergrund, ohne Audio, Display oder Eingaben zu blockieren.
Es gibt keine automatischen Wiederholungen.

In der Admin-Oberfläche unter **WLED Controller** Aktiv, Hostname/IP und Timeout
ändern und **Speichern** drücken. Danach **Verbindung testen** wählen: Der Test
verwendet die gespeicherten Werte und aktualisiert den Status. Vor einem Test
steht dort „nicht geprüft“. Alternativ liefert `GET /api/wled/test` JSON mit
`success`, `host` und bei Fehlern `error`. Deaktiviert bedeutet: keine HTTP-Anfrage.
Der Wecker liest die Einstellungen vor jeder Anfrage neu; kein Neustart ist nötig.
Eine bereits laufende Anfrage verwendet noch die vorherigen Werte.

Manuell auf dem Raspberry Pi prüfen (der Name muss in WLED konfiguriert sein):

```sh
getent hosts alarm-led.local
curl --max-time 3 http://alarm-led.local/json
curl --max-time 5 http://127.0.0.1:8080/api/wled/test
```

Falls `getent` keinen Eintrag liefert, mDNS-Unterstützung des Pi (z. B. Avahi/NSS)
und das gemeinsame lokale Netzwerk prüfen.

`lighting.WLEDManager()` verwendet die zentrale Konfiguration. `send(state)`,
`set_power(True)`, `set_brightness(80)` und `activate_preset(3)` stellen Befehle
in die begrenzte Warteschlange; sie bestätigen keine erfolgreiche Zustellung.
`get_status()` und `is_available()` fragen synchron ab und gehören nicht in die
Wecker-Hauptschleife. Damit ist die Schnittstelle für spätere Szenen vorhanden;
eine neue Szenenlogik ist nicht enthalten. `WLEDClient` bleibt nur als dünner
Kompatibilitätsadapter bestehen und hat keine eigene HTTP-Implementierung.

## Effektbibliothek und Bedienung

`effects.json` enthält eine geordnete Liste mit eindeutiger `id`, `name`, optionaler
`key` und einem WLED-JSON-`state`. Beispiele: Warmweiss, Musik-Preset 1 und Aus.
Preset 1 muss am WLED-Gerät selbst eingerichtet werden. Die Bibliothek wird beim
Start gelesen. Effekte beziehen sich im Warmweiss-Beispiel auf Segment 0.

Jedes Bedienelement hat genau einen Zuständigkeitsbereich: der linke Drehknopf
das Licht, der rechte den Ton, das Tastenfeld die kuratierten Lieblingseffekte
und (Tasten A/B/C) Smart-Home-Kurzbefehle.

- **Links drehen – Licht wählen.** Blättert durch *alle* Effekte des WLED-Geräts
  und schaltet den Streifen sofort um (Live-Vorschau, kein Bestätigen nötig).
  Das LCD zeigt `12/187 Aurora`. Zwei Drehschritte innerhalb von
  `config.EFFECT_FAST_SECONDS` springen um `config.EFFECT_FAST_STEPS` Einträge,
  damit auch ~180 Effekte mit einem Rastencoder erreichbar bleiben: schnell
  drehen sucht grob, langsam drehen wählt genau.
- **Links drücken – Streifen an/aus.**
- **Tastenfeld:** Eintrag aus `effects.json` über seine `key` direkt aktivieren.
  Jeder Tastendruck gibt zusätzlich einen kurzen Klick aus (`chime.py`, per
  `aplay` unabhängig vom laufenden Alarm/Musik-Ton). Die Tasten `A`/`B`/`C`
  sind keine Lichteffekte mehr, sondern lösen über `config.SMART_HOME_ACTIONS`
  eine Home-Assistant-Aktion aus (Deckenlampe, zwei Alexa-Routinen) – die
  Effekte Aurora/Fireworks/Lightning bleiben über den linken Drehknopf
  erreichbar. Ohne gesetzte `config.HOME_ASSISTANT_URL` wird die Aktion nur
  geloggt; die eigentliche Anbindung (Home Assistant vs. Fauxmo) steht noch
  aus, siehe `smart_home.py`.
- **Rechts drehen – Lautstärke** in Schritten von `config.VOLUME_STEP` (Standard 5 %).
- **Rechts kurz drücken – Ton an/aus.** Läuft ein Alarm, stoppt er. Läuft Musik,
  stoppt sie. Sonst startet das Tageslied. Der kurze Druck meldet beim Loslassen,
  damit er vom langen unterscheidbar ist.
- **Rechts lang drücken (`config.BUTTON_HOLD_SECONDS`, Standard 2 s) – „Alles
  normal".** Musik aus, Licht an, Display zurück auf die automatische Steuerung
  über `config.GREETINGS`. Die Fluchttaste, wenn man sich verklickt hat.

Die Effektnamen für den linken Knopf holt `EffectBrowser.refresh()` beim Start
in einem Hintergrund-Thread vom Gerät (`/json` → `effects`); die Hauptschleife
blockiert dabei nie. Antwortet das Gerät nicht, dient die kuratierte Liste aus
`effects.json` als Ersatz – Einträge ohne `seg[0].fx` (z. B. „Licht aus") können
dann nicht vorgeschaut werden und fehlen in dieser Ersatzliste.

WLED-Anfragen laufen in einem eigenen Thread mit Timeout. Bei vielen Befehlen
bleibt nur der neueste noch nicht gesendete Zustand in der Warteschlange.
Verbindungsfehler werden protokolliert; sie unterbrechen den Alarm
nicht. Der angezeigte Effektname ist eine Auswahl, keine Empfangsbestätigung.

## I2C-Anbindung: Drehencoder und Tastenfeld

`controls_mcp.py` implementiert `INPUT_MODULE` für die tatsächlich verbaute
Hardware, per `i2cdetect -y 1` und `rotary_clock.py` vermessen:

- Tastenfeld (PCF8574) auf `0x20` (`config.KEYPAD_ADDRESS`): Zeilen P0–P3, Spalten P4–P7.
- MCP23017 auf `0x21` (`config.MCP23017_ADDRESS`): linker Encoder A/B auf PB6/PB7,
  Taster auf PB5; rechter Encoder A/B auf PA0/PA1, Taster auf PA2.
- LCD (PCF8574) auf `0x27` (`config.LCD_ADDRESS`), gemeinsamer Bus `config.INPUT_I2C_PORT`.

Weichen Adressen/Verkabelung ab, `config.MCP23017_ADDRESS`/`KEYPAD_ADDRESS`
anpassen oder mit `i2cdetect -y 1` neu bestimmen. Ein eigener Polling-Thread
scannt Encoder (Quadratur, Schwelle 2 Flanken je Schritt) und Tastenfeld
(zeilenweise, entprellt); `emit()` legt Ereignisse nur in die Warteschlange,
LCD und Bedienzustand ändert ausschließlich die Hauptschleife. Schlägt die
Initialisierung fehl (I2C-Fehler, falsche Adresse), läuft der Wecker ohne
Tastenfeld/Encoder weiter – analog zum alten GPIO-Taster.

Eigene Schnittstelle für einen anderen Treiber, weiterhin über `INPUT_MODULE`:

```python
# In einem eigenen, per INPUT_MODULE benannten Python-Modul:
def open_controls(emit):
    # Hardware initialisieren und Eingaben entprellen.
    # emit("left_rotate", +1) / emit("left_rotate", -1)
    # emit("left_press")
    # emit("key", "1")
    # emit("right_press") / emit("right_hold") / emit("right_rotate", +1)
    # Objekt zurückgeben, dessen close() Threads und Buszugriff beendet.
    ...
```

Ohne `INPUT_MODULE` (`= None`) bleibt der alte GPIO17-Taster aktiv, falls
`LEGACY_BUTTON_ENABLED = True`: Einfachklick schaltet Hintergrundlicht oder
stoppt einen aktiven Alarm, Doppelklick spielt das Tageslied, Dreifachklick
stoppt Audio.

## Debug-Ausgaben

`config.DEBUG` (Standard an, mit `ALARM_DEBUG=0` abschaltbar) gibt auf der
Konsole jede ausgelöste Aktion aus, um Eingabe- und WLED-Probleme live zu
verfolgen:

- `[Event] key '3'` – vom Eingabemodul in die Warteschlange gelegtes Ereignis.
- `[Eingabe] ...` – Rohereignisse aus `controls_mcp.py` (Tastendruck, Drehschritt).
- `[Controller] ...` – daraus abgeleitete Aktion (Effekt, Licht, Alarm gestoppt).
- `[WLED] Sende an <host>: {...}` – tatsächlich an WLED geschicktes JSON.

Bleibt bei Tastendruck z. B. nur `[Event]`/`[Eingabe]` sichtbar, aber kein
`[WLED]`, liegt es an der Effektauswahl (`effects.json`, `key`-Zuordnung);
bleibt auch `[Eingabe]` aus, liegt es an Verkabelung/I2C-Adresse.

## Musikreaktion

WLED-Lichtsteuerung erfolgt über HTTP/WLAN, nicht über den lokalen I2C-Bus.
Audio-Reaktivität braucht eine passende WLED-Firmware und eine Audioquelle.
Möglich sind unter anderem Mikrofon/Line-in am Controller oder Audio-Sync.
USB-Lautsprecher allein senden keine Audiodaten an WLED.
Das Musik-Preset aktiviert nur einen vorher eingerichteten Effekt; diese Software
implementiert noch keine Audioanalyse oder Audio-Sync-Übertragung vom Pi.
Benötigt werden Controller-Modell, Firmwareversion und die Entscheidung für
Mikrofon oder digitale Audioübertragung.

Offizielle Grundlagen:
[WLED JSON API](https://kno.wled.ge/interfaces/json-api/),
[WLED Audio Reactive](https://kno.wled.ge/advanced/audio-reactive/).

## Optionale Weboberfläche

Start: `.venv/bin/python webserver.py`, standardmäßig erreichbar im gesamten
lokalen Netzwerk unter `http://<Pi-IP>:8080` (z. B. `http://raspberrypi.local:8080`),
da der Server an `0.0.0.0` bindet (`WEB_HOST`/`WEB_PORT` in `config.py`, per
`ALARM_WEB_HOST`/`ALARM_WEB_PORT` überschreibbar).
**Die Oberfläche hat keine Anmeldung** und darf deshalb nur in einem
vertrauenswürdigen Heimnetz laufen – keine Portweiterleitung ins Internet ohne
zusätzlichen Schutz (z. B. Reverse-Proxy mit Login/HTTPS oder VPN).
Weckzeit **und Aktiv-Status** werden atomar in `settings.json` gespeichert und
vom laufenden Wecker übernommen. Datum, Datei und Spruch landen in
`mp3_mapping.json` und lassen sich in der Tabelle auch wieder löschen.
Priorität: konkretes Datum, jährliches Datum aus Webzuordnung, `DATE_SONGS`,
Rotation, Standardlied. MP3-Unterordner werden aufgelistet.
Uploads akzeptieren bereinigte MP3-Dateinamen, maximal 32 MiB, und überschreiben
keine vorhandenen Dateien. Eine Dateiendung ist keine Audioformatprüfung.
Neue Songs einfach über das Upload-Formular in den `mp3`-Ordner laden; sie
stehen danach sofort zum Abspielen und für Datumszuordnungen zur Verfügung.

Web-Vorhören läuft in einem eigenen Audioprozess: Web-Stopp stoppt nur das
Vorhören, der Hardwaretaster stoppt den Wecker. Gleichzeitiges Vorhören und
Wecken kann je nach ALSA-Gerät kollidieren. Eine gemeinsame Laufzeitsteuerung
für beide Prozesse ist noch nicht vorhanden.

## Dauerhafter Betrieb (systemd + nginx)

Für Dauerbetrieb (Start beim Booten, automatischer Neustart bei Absturz) laufen
Wecker und Weboberfläche als systemd-Services; nginx macht die Weboberfläche im
LAN auf Port 80 erreichbar, während die Flask-App selbst nur an `127.0.0.1`
bindet. Die fertigen Unit-/Config-Dateien liegen in `systemd/` und `nginx/`.

```sh
# Waitress ist bereits in requirements.txt enthalten:
.venv/bin/pip install -r requirements.txt

# Systemd-Services installieren und aktivieren:
sudo cp systemd/alarmclock.service systemd/alarmclock-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now alarmclock.service alarmclock-web.service

# nginx installieren und als Reverse-Proxy vor die Weboberfläche schalten:
sudo apt install nginx
sudo cp nginx/alarmclock.conf /etc/nginx/sites-available/alarmclock
sudo ln -s /etc/nginx/sites-available/alarmclock /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Danach ist die Oberfläche unter `http://<Pi-IP>/` (Port 80, ohne `:8080`) im
LAN erreichbar. `alarmclock-web.service` startet `waitress-serve` explizit mit
`--host=127.0.0.1`, damit die App selbst nur lokal erreichbar ist und
ausschließlich nginx nach außen zeigt.

Nützliche Befehle:

```sh
sudo systemctl status alarmclock.service alarmclock-web.service
journalctl -u alarmclock.service -f      # laufende Debug-Ausgaben (config.DEBUG) live verfolgen
journalctl -u alarmclock-web.service -f
sudo systemctl restart alarmclock.service alarmclock-web.service
```

Änderungen an `config.py`/den Unit-Dateien erfordern `sudo systemctl daemon-reload`
(nur bei Änderungen an der `.service`-Datei) und `sudo systemctl restart ...`.
Weiterhin gilt: keine Portweiterheitung dieses Ports ins Internet ohne
zusätzlichen Schutz (Anmeldung, TLS, VPN) – die Oberfläche ist bewusst nur
fürs Heimnetz gedacht.

## Prüfung

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q alarm_clock.py audio.py button.py config.py controller.py controls_mcp.py lcd.py lighting.py scheduler.py settings.py webserver.py
```

Tests prüfen Alarmdauer, Stoppen, Monatswechsel, Liedrotation, vorhandene
Musikdateien, Audio-Prozessende und die WLED-/Effektschnittstelle mit Mocks.
Die Hardware-Testskripte im Projektstamm werden dabei absichtlich nicht gestartet.

Die WLED-Tests mocken HTTP vollständig und prüfen zusätzlich DNS-/Verbindungsfehler,
Timeouts, ungültige API-Antworten, Deaktivierung, Presets, die begrenzte
Warteschlange, Live-Konfigurationswechsel und Speichern/Testen über die Web-API.

### GPIO-Taster: fehlender Treiber beim Start

Meldungen wie `No module named 'lgpio'` und anschließend
`/sys/class/gpio/gpio17/value` / `Invalid argument` betreffen den alten GPIO17-Taster.
Die Anwendung meldet dessen Initialisierungsfehler und läuft ohne diesen Taster
weiter. Damit stehen seine Klickaktionen, insbesondere manuelles Alarmstoppen,
nicht zur Verfügung; die konfigurierte Alarmdauer gilt weiterhin.

Wenn kein alter GPIO17-Taster angeschlossen ist, in `config.py`
`LEGACY_BUTTON_ENABLED = False` setzen. Für einen angeschlossenen Taster muss ein
passender GPIO-Treiber in der verwendeten Python-Umgebung verfügbar sein.
GPIOZero unterstützt `lgpio` auf allen Pi-Modellen:
[GPIOZero Pin-Factories](https://gpiozero.readthedocs.io/en/stable/api_pins.html).
In der aktivierten virtuellen Umgebung beispielsweise:

```sh
python3 -m pip install lgpio
GPIOZERO_PIN_FACTORY=lgpio python3 alarm_clock.py
```

Die Projekt-venv hat derzeit keinen Zugriff auf systemweit installierte
Python-Pakete (`include-system-site-packages = false`); eine reine Installation
über apt macht den Treiber daher nicht automatisch in dieser venv verfügbar.
