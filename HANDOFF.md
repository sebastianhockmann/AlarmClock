# Handoff — AlarmClock

_Status as of 2026-11-25._

## Where things stand

Restructured for maintainability:

- All configuration moved to `config/` as JSON (`hardware.json`, `defaults.json`,
  `effects.json`; runtime overrides in gitignored `config/settings.json`). `settings.py`
  validates and merges; old root `settings.json`/`mp3_mapping.json` are migrated on
  first clock start.
- New modules: `wake.py` (wake program: light sunrise ramp, volume ramp, end after song,
  snooze), `integrations.py` (HTTP / Home Assistant / Alexa via alexa-remote-control),
  `weather.py` (Open-Meteo), `ipc.py` (web UI → clock commands over localhost UDP).
  `smart_home.py`, `EffectSelector`, `WLEDClient` removed.
- Multiple alarms with weekdays, master on/off switch, light lead before alarm.
- Keypad fully configurable per key (effect, music, weather, display, snooze, Alexa, HTTP, HA …).
- Web UI rewritten as tabbed single page (vanilla JS) over a JSON API; audio preview now
  plays on the clock (single ALSA owner) or in the browser.
- Manual hardware scripts moved to `tools/`.

## 2026-09-29: Farben, Knöpfe, Alexa-Wecken

- Green tint root cause: WLED segment palette stuck on 50 "Aurora"; commands never set `pal`.
  Library effects now set `pal`, left-knob browser sends `fxdef` + default palette from
  `/json/fxdata`. Live WLED segment was reset to pal 0 during diagnosis.
- Right knob direction reversed via `inputs.right_reverse` (hardware.json, restart needed).
- Right knob pressed+turned = Alexa volume (`right_press_rotate`), debounced 0.8 s.
- Wake music `alexa`: daily rotation of `music.alexa_songs`, volume ramp in Alexa steps,
  "Stopp" on end/snooze, fallback to MP3 on missing echo or failed command.
- Key action `songs`: browse MP3s / Alexa songs with the right knob.
- Keypad was wired rotated: `controls_mcp.KEYS` now `("DCBA", "#963", "0852", "*741")`,
  verified on hardware (all 16 keys, 2026-09-29). Push+turn and knob direction verified too.
- Alexa volume command is "Lautstärke N" (1-10); HA Alexa calls get a 15 s timeout.
- Needs on the Pi: restart both services, pick "Echo über Home Assistant" under Smart Home,
  verify knob direction and push-turn on hardware.

## 2026-11-03: Netzwerk-Live-Check, Schulkalender, Morgen-/Abendlicht

- errno 113: `network.py` + `integrations._open()` warten bei nicht aufgebauter Verbindung
  bis 20 s aufs Netz und senden erneut (nie nach Timeout). `NetworkMonitor` loggt Ausfaelle.
  Ursache vermutlich WLAN-Power-Save (`Power Management:on`) -> `networkmanager/wifi-powersave-off.conf`
  muss noch mit sudo installiert werden (README "Netzwerk-Live-Check").
- `school_calendar.py`: Thueringer Feiertage berechnet, Ferien von openholidaysapi.org
  (Seed `config/school_holidays.json` bis 01/2029 + taeglicher Cache), eigene freie Tage.
- `programs.py`: Morgenlicht 06:00-06:40 (Schultage, Sonnenaufgang 1->80 % in 15 min),
  Abendlicht 20:30-21:00 (vor Schultagen, Abendglut 35->4 % in 30 min). Wecker "Schule"
  06:15 Mo-Fr nur Schultage; Weckprogramm-Licht jetzt "kein Licht". `alarms_enabled` auf true gesetzt.
- Dienste laufen seit 2026-11-03 17:25 mit dem neuen Code.
- WLAN-Power-Save aus (Konfig installiert). Offen: Morgen-/Abendlicht am echten Streifen ansehen.

## 2026-11-25: Ausfall-Analyse, Robustheit, Weboberflaeche

- Ausfall 24.11. abends bis Neustart 25.11. 08:48: Pi im Netz weg, Display lief, morgens
  kein Licht/keine Musik (erster Tag der Weihnachts-Playlist = Alexa). Ursache nicht mehr
  belegbar: Journal war volatile (RPi-OS-Default). nginx-Log endet 24.11. 22:05:18.
  Bekannt: WLAN -73 dBm auf DFS-Kanal 100 (5,5 GHz), NM autoconnect-retries Standard 4.
- Neu: `tools/install_system.sh` (sudo) installiert persistentes Journal, WLAN-Waechter
  (`tools/netwatch.sh` -> /usr/local/sbin, Timer 1 min), Hardware-Watchdog,
  NM autoconnect-retries 0, Dienste mit Restart=always. **Noch nicht ausgefuehrt.**
- Wecker: Alexa-Wecken ohne Netz -> sofort MP3; WLED-Befehle werden bis 15 min nachgesendet
  (Log nur bei Wechsel); Weck-Sperre in `config/alarm_state.json`, verpasste Weckzeiten
  bis 10 min nachgeholt; LCD "Netz?"; ALSA per Kartenname `plughw:CARD=Device,DEV=0`.
- Weboberflaeche: Uebersicht mit Plan fuers naechste Wecken, Wecker-Schaltern,
  Wecker-Check (`/api/health`), Licht an/aus/Helligkeit (ipc `brightness`); Markierung
  ungespeicherter Aenderungen, Offline-Balken, groessere Touch-Flaechen.

## Tests

`.venv/bin/python -m unittest discover -s tests -v` → 140 tests, all green on the Pi
(system Python lacks Flask, so use the venv).
Integration-checked on the Pi: new web UI against the real WLED (16.0.1, 264 LEDs,
AudioReactive with I2S mic active), Open-Meteo search, and the clock main loop with a
stub LCD driven over `ipc`. Rendered pages checked via headless Firefox (desktop + phone width).

## Open items

1. Run `sudo tools/install_system.sh` (restarts the services with the new code). Afterwards
   outages are in `journalctl -u alarmclock.service -u alarmclock-netwatch.service -b -1`.
   Router: consider a non-DFS 5 GHz channel (36-48) or 2.4 GHz for the Pi.
2. Verify on hardware: morning/evening light, alarm "Schule", snooze via keypad, wake test,
   key A (HA Deckenlampe).
3. Alexa: `alexa_remote_control.sh` not installed; key B needs it (or use
   "Echo ueber Home Assistant").
4. Home Assistant and weather location are configured (done).
5. Alexa can accept a command and still stay silent (e.g. song not found); that is not
   detectable - the MP3 fallback only covers failed commands / no network.
6. Web UI has no authentication — LAN-only by design.
7. Music library is still the Christmas starter set.
