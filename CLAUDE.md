# CLAUDE.md

Raspberry Pi alarm clock: I2C LCD, mpg123 audio over ALSA, WLED LED strip over
HTTP, two rotary encoders + 4x4 keypad over I2C, and a Flask web UI.
Developed on Windows, **deployed and run on a Pi** (`/home/pi/AlarmClock`, user `pi`).
`README.md` (German) is the detailed user/operator documentation — keep it in
sync when behavior or config changes.

## Language conventions

- README, LCD texts, log/debug output, web UI and error messages are **German**.
  LCD strings avoid umlauts (`Lautstaerke`, `Weckzeit`) because the HD44780
  charset can't render them; keep that convention for anything shown on the LCD.
  Validation messages from `settings.py` are shown in the web UI (umlaut-free ASCII is fine).
- Code identifiers are English; comments are mixed German/English — match the
  surrounding file.

## Commands

```sh
python -m unittest discover -s tests -v          # full test suite (no hardware needed)
python -m compileall -q *.py config tools         # syntax check
python alarm_clock.py                             # main loop (needs Pi hardware)
python webserver.py                               # web UI dev server, 0.0.0.0:8080
```

On the Pi, production runs via systemd (`systemd/*.service`) with waitress
bound to 127.0.0.1 behind nginx (`nginx/alarmclock.conf`). Logs:
`journalctl -u alarmclock.service -f`. Restarting needs sudo with a password,
so ask the user to run `sudo systemctl restart alarmclock.service alarmclock-web.service`.

## Configuration (`config/`)

| File | Content | Tracked | Written by |
|---|---|---|---|
| `config/hardware.json` | I2C addresses, LCD, input module, ALSA device, web/IPC ports, alexa script path, debug | yes | hand, restart needed |
| `config/defaults.json` | defaults for every web-editable section | yes | hand |
| `config/effects.json` | default effect library (numeric WLED `fx` IDs) | yes | hand |
| `config/settings.json` | web UI overrides | no | web UI / `settings.save()` |
| `config/school_holidays.json` | Thüringen school holidays seed (works offline) | yes | `tools/update_school_holidays.py` |
| `config/school_holidays_cache.json` | same, refreshed daily from openholidaysapi.org | no | `school_calendar.HolidayUpdater` |

- `config/__init__.py` loads `hardware.json` into module constants (`config.LCD_ADDRESS`, …),
  plus paths. Env overrides: `ALARM_ALSA_DEVICE`, `ALARM_DEBUG`, `ALARM_WEB_HOST/PORT`,
  `WLED_HOST` (`WLED_URL` fallback). Web-editable values are **not** constants.
- `settings.py` is the store: `settings.load()/get(section)/save(section, value)/reset(section)`.
  Sections and validators live in `settings.VALIDATORS`. Dicts deep-merge onto defaults,
  lists replace. `save` validates strictly (German `ValueError`); `load` falls back per field
  and skips invalid list entries. Cached by file mtime, so both processes read live.
  To add a setting: add it to `defaults.json`, add a field/spec in `settings.py`, expose in the UI.
- `settings.migrate_legacy()` (called from `alarm_clock.main()`) moves old root
  `settings.json`/`mp3_mapping.json` into `config/settings.json`.

## Architecture

Two processes. They share settings through `config/settings.json`, and the web UI
sends runtime commands to the clock over UDP on localhost (`ipc.py`, port from `hardware.json`):

| Process | Entry | Role |
|---|---|---|
| Clock | `alarm_clock.py` | 20 ms main loop: `controller.tick()`, drain event queue, update LCD; runs `ipc.CommandServer` |
| Web UI | `webserver.py` (Flask) + `templates/index.html` (vanilla JS SPA) | JSON API for all settings, MP3 upload/preview, tests; never plays audio itself |

Modules:

- `controller.py` — `ClockController`: alarm lifecycle (via `WakeSession`), snooze, and
  **all** event handling incl. keypad actions (`run_action`). Most logic changes land here;
  fully unit-testable with mocks.
- `wake.py` — `WakeSession`: light ramp (full effect state + `bri` + `tt` every 2 s),
  volume ramp, end after song (`AudioPlayer.finished`) or `max_minutes`, snooze, light off.
- `programs.py` — light programs (`programs` section: morning/evening light): `active(now)`
  window + calendar of the start day, `ProgramRunner` ramps `bri` from wall-clock time
  (restart resumes), fades off at `end`; `override()` on manual light input; paused while
  a `WakeSession` has its own light.
- `school_calendar.py` — Thüringen school days: computed public holidays, school holidays
  from seed + cache file, `calendar.free_days`; `matches(rule, day)` for rules
  `all|school|free|before_school` (alarms: `alarm['calendar']`, programs: `program['calendar']`).
  Missing data = school day (better wake once too often).
- `network.py` — live check: `not_connected(error)` (errno 113 etc., never timeouts),
  `wait_reachable()`; `integrations._open()` waits and resends; `NetworkMonitor` thread
  logs outages, status `network` in ipc status.
- `scheduler.py` — `AlarmScheduler.due(now)` → `[('light'|'alarm', alarm)]`, one per alarm
  per date (in-memory), light lead handled across midnight; `next_alarm`, song selection
  (exact date → yearly date → rotation → default; or random from `mp3/`), greetings.
- `integrations.py` — remote actions (`http`, `home_assistant`, `alexa` via
  `alexa_remote_control.sh`, arg list, no shell); `run()` is async and reports failures via callback.
- `weather.py` — Open-Meteo fetch + LCD summary, background thread, cached.
- `ipc.py` — `CommandServer` (whitelisted `REMOTE_EVENTS`, status query) and `send()/status()`.
- `lighting.py` — `WLEDManager` (background thread, bounded queue keeps only newest unsent
  state; no retries; `fetch()` for sync GETs in web requests), `EffectBrowser` (left knob).
- `audio.py` — `AudioPlayer` wraps `mpg123 -R`; volume via stdin, `is_playing`/`finished` from `@P`.
- `controls_mcp.py` — I2C input driver (`open_controls(emit)`), MCP23017 + PCF8574, own thread.
- `lcd.py` (imported lazily in `main()`), `chime.py`, `button.py` (legacy GPIO, disabled).

Events (queue, main thread only): input `left_rotate`, `left_press`, `key`, `right_rotate`,
`right_press`, `right_hold`, `right_press_rotate`, `legacy_press`, `error`; remote (ipc) `key`, `action`,
`play_today`, `play_random`, `play_file`, `stop_audio`, `wake_test`, `wake_stop`, `volume`,
`notice`; internal `weather_result`, `alexa_error` (wake command failed → fall back to MP3).

Keypad action types (`settings.ACTION_SPECS`): `none`, `effect`, `light`, `music`, `display`,
`songs` (browse MP3s or `music.alexa_songs` with the right knob), `snooze`, `wake_test`,
`alarm_toggle`, `weather`, `http`, `home_assistant`, `ha_color`
(cycles `light.turn_on` through a color list, starting from the lamp's current color),
`ha_alexa` (`alexa_devices.send_text_command` by HA device_id), `alexa`.

Control model: left knob = light, right knob = sound, keypad = configurable actions
(during an alarm any key = snooze by default), long right press = "Alles normal" reset,
right knob pressed+turned = Alexa volume, left knob within 10 s after a HA lamp key
(`home_assistant`/`ha_color` on `light.*`) = dim that lamp (`integrations.LampDimmer`, steps 1/10..100 %, newest value wins). Alexa (wake music `alexa`, song list, knob volume)
goes through `integrations.AlexaSpeaker` (serial queue, echo = `alexa.ha_device_id`).

WLED keeps `seg.pal` across effect changes: every library effect sets `pal`, and the
left-knob browser sends `fxdef` + the effect's default palette from `/json/fxdata`.

## Rules / gotchas

- **Importing a module must never touch hardware.** `alarm_clock.py` imports `lcd`
  inside `main()`; tests rely on this. Keep new hardware init lazy.
- Input drivers, WLED, weather and integrations run on background threads; only the main
  loop may change LCD/controller state — background threads report via `emit('notice', …)`.
  Never block the main loop on network or I2C.
- Hardware/network failures (I2C, GPIO, WLED/HA/Alexa unreachable) must degrade
  gracefully — log and keep the alarm running.
- Effect library uses numeric WLED `fx` IDs; loading must not depend on WLED being reachable.
- `tools/` holds manual hardware scripts (not part of the test suite); they add the project
  root to `sys.path`. Real tests live in `tests/`; `tests/helpers.TempSettingsTestCase`
  redirects `config.SETTINGS_FILE` to a temp dir — use it for anything touching settings.
- The web UI has **no authentication** — intended for the home LAN only. Never return
  the Home Assistant token to the browser; never add shell-command actions editable from the web.
