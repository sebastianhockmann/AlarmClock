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
- Code identifiers are English; comments are mixed German/English — match the
  surrounding file.

## Commands

```sh
python -m unittest discover -s tests -v          # full test suite (no hardware needed)
python -m compileall -q *.py                      # syntax check
python alarm_clock.py                             # main loop (needs Pi hardware)
python webserver.py                               # web UI dev server, 0.0.0.0:8080
```

On the Pi, production runs via systemd (`systemd/*.service`) with waitress
bound to 127.0.0.1 behind nginx (`nginx/alarmclock.conf`). Logs:
`journalctl -u alarmclock.service -f`.

### Known test failures on Windows (not regressions)

- `test_controls_mcp` fails to import: `smbus2` is not installed locally
  (`pip install smbus2` fixes it; the module itself is pure Python).
- `test_wled.test_mapping_display_and_delete` fails because Windows path
  separators render as `mp3\xmas\maria.mp3`. Passes on the Pi (Linux).

## Architecture

Two independent processes share state only through JSON files:

| Process | Entry | Role |
|---|---|---|
| Clock | `alarm_clock.py` | 20 ms main loop: `controller.tick()`, drain input queue, update LCD |
| Web UI | `webserver.py` (Flask) | Edit alarm time / WLED settings / date→song mapping, upload & preview MP3s |

Shared files (gitignored, runtime-written): `settings.json` (alarm hour/minute/enabled,
`wled` section) and `mp3_mapping.json` (date → file/message). Written atomically
via `settings.write_json`; the clock re-reads them on every check, so no restart needed.

Modules:

- `config.py` — all defaults and hardware addresses. Env overrides:
  `ALARM_ALSA_DEVICE`, `ALARM_DEBUG`, `ALARM_WEB_HOST/PORT`, `WLED_HOST` (`WLED_URL` fallback).
  Precedence: `settings.json` > env > `config.py`.
- `controller.py` — `ClockController`: hardware-independent alarm lifetime and
  all input-event handling. Most logic changes land here; fully unit-testable with mocks.
- `scheduler.py` — `check_alarm()` (fires once per date, in-memory `_last_alarm_day`),
  song selection priority: exact date → yearly web mapping → `DATE_SONGS` → `WAKE_ITEMS` rotation → `DEFAULT_SONG`.
  Greetings/backlight schedule from `config.GREETINGS`.
- `audio.py` — `AudioPlayer` wraps `mpg123 -R` (remote mode); volume via stdin `VOLUME`,
  background thread parses `@P` status for `is_playing`.
- `lighting.py` — `WLEDManager` (background thread, bounded queue that keeps only
  the newest unsent state; no retries), `EffectSelector` (curated `effects.json`,
  keypad), `EffectBrowser` (all device effects fetched from `/json`, left knob,
  fast-spin acceleration). `WLEDClient` is a thin compat adapter only.
- `controls_mcp.py` — I2C input driver loaded via `config.INPUT_MODULE`
  (`open_controls(emit) -> obj with close()`). MCP23017 @0x21 for encoders,
  PCF8574 @0x20 for keypad; own polling thread, only calls `emit()`.
- `lcd.py` — RPLCD wrapper, writes only changed rows; imported lazily in `main()`.
- `button.py` — legacy GPIO17 button (disabled: `LEGACY_BUTTON_ENABLED = False`).

Input events (emitted into a `queue.Queue`, handled only on the main thread):
`left_rotate`, `left_press`, `key`, `right_rotate`, `right_press`, `right_hold`,
`play_today`, `legacy_press`, `error`.

Control model: left knob = light, right knob = sound, keypad = favourite effects,
long right press = "Alles normal" reset.

## Rules / gotchas

- **Importing a module must never touch hardware.** `alarm_clock.py` imports `lcd`
  inside `main()`; tests rely on this. Keep new hardware init lazy.
- Input drivers and WLED I/O run on background threads; only the main loop may
  change LCD/controller state. Never block the main loop on network or I2C.
- Hardware failures (I2C, GPIO, WLED unreachable) must degrade gracefully —
  log and keep the alarm running.
- Root-level `*_test.py`, `test_*.py`, `rotary_clock.py`, `wled_effect_list.py`,
  `watchdog.py` are manual hardware scripts, not part of the test suite. Real tests live in `tests/`.
- The web UI has **no authentication** — intended for the home LAN only.
