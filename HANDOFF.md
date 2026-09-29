# Handoff — AlarmClock

_Status as of 2026-09-26, uncommitted restructuring on top of `571eca3` on `main`._

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

## Tests

`python -m unittest discover -s tests -v` → 82 tests, all green on the Pi.
Integration-checked on the Pi: new web UI against the real WLED (16.0.1, 264 LEDs,
AudioReactive with I2S mic active), Open-Meteo search, and the clock main loop with a
stub LCD driven over `ipc`. Rendered pages checked via headless Firefox (desktop + phone width).

## Open items

1. **Services still run the old code** — needs
   `sudo systemctl restart alarmclock.service alarmclock-web.service` (sudo needs a password).
   Then check `journalctl -u alarmclock.service` for the migration message and verify on
   hardware: wake test from the web UI (light ramp, volume ramp, end after song), snooze via
   keypad, key actions, LCD messages.
2. Alexa: `alexa_remote_control.sh` not installed yet; key B is preconfigured for it.
   Alternative without login: URL Routine Trigger / Voice Monkey URL as `http` action.
3. Home Assistant URL/token not set; key A (Deckenlampe) does nothing until then.
4. Weather location not set.
5. Alarm "already fired today" lock is in memory only (restart within the alarm minute can
   re-trigger; missed alarms are not caught up).
6. Web UI has no authentication — LAN-only by design.
7. Music library is still the Christmas starter set.
