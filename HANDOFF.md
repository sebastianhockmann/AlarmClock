# Handoff — AlarmClock

_Status as of 2026-09-23, commit `9a177e7` ("New functions") on `main`._

## Where things stand

The clock is functionally complete for the current hardware:

- Alarm triggers at the configured time, plays the day's song once, shows the
  message, and stays active until stopped or `ALARM_DURATION_SECONDS` (300 s) elapse.
- Left encoder browses all WLED effects live (with fast-spin acceleration),
  press toggles the strip. Keypad selects curated effects from `effects.json`.
- Right encoder sets volume, short press stops alarm / toggles music, long press
  (2 s) resets everything to "Alles normal".
- Web UI: alarm time + enabled, WLED host/timeout + connection test, date→song
  mapping, MP3 upload and preview.
- systemd units + nginx reverse proxy for permanent operation on the Pi.

Latest commit added: right-knob volume control, long-press reset, `EffectBrowser`
(all device effects on the left knob), and LCD backlight reset.

## Tests

`python -m unittest discover -s tests -v` → 41 tests. On the Windows dev box,
2 fail for environment reasons only (see CLAUDE.md): missing `smbus2`, and
backslash path separators in the web mapping test. Expected all-green on the Pi —
**not yet re-verified on the Pi after the latest commit.**

## Open items / known limitations

1. **Verify on hardware** after `9a177e7`: volume knob, long-press reset,
   effect browsing across ~180 effects, backlight reset.
2. Web preview and alarm use separate mpg123 processes; simultaneous playback may
   collide on the ALSA device. No shared runtime control between the two processes.
3. Alarm "already fired today" lock is in memory only — a restart within the
   alarm minute can re-trigger; missed alarms are not caught up.
4. No acoustic fallback if the audio device/decoder fails after start.
5. WLED audio reactivity not implemented (only activates a pre-configured preset);
   needs a decision on mic vs. audio sync and controller/firmware details.
6. Web UI has no authentication — LAN-only by design.
7. Tests could normalize path separators to pass on Windows.
8. `WAKE_ITEMS` / `DATE_SONGS` are still the Christmas starter library.

## Deploying changes to the Pi

```sh
cd /home/pi/AlarmClock && git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart alarmclock.service alarmclock-web.service
journalctl -u alarmclock.service -f
```

## Useful pointers

- Architecture and conventions: `CLAUDE.md`
- Full operator docs (German): `README.md`
- Logic entry point for most changes: `controller.py` (`ClockController.handle`)
- Hardware wiring/addresses: `config.py` section "Drehencoder" and `rotary_clock.py`
