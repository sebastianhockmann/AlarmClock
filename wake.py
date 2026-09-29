"""Weckprogramm: Licht wird langsam heller, Musik startet leise und wird lauter.

Eine WakeSession ist ein laufender Weckvorgang. Sie kennt drei Phasen:
'light' (Licht-Vorlauf vor der Weckzeit), 'music' (Lied laeuft) und
'snooze' (Schlummern, Licht bleibt an). Die Session macht nur Ausgaben an
Player und WLED; wann sie beginnt und endet, entscheidet ClockController.

Die Lichtrampe schickt alle LIGHT_STEP_SECONDS einen neuen Helligkeitswert
mit WLED-Uebergang ("tt"), damit es trotz grober Schritte weich aussieht.
Jeder Schritt enthaelt den vollen Effektzustand: faellt ein Befehl in der
WLEDManager-Warteschlange weg, stimmt der naechste trotzdem.

Musik ueber Alexa (item['alexa'] = Sprachbefehl): Die Lautstaerke-Rampe
laeuft in Alexa-Stufen 1-10 ("Lautstärke N"), jede Stufe nur einmal.
Das Ende eines Liedes meldet Alexa nicht - Schluss ist nach max_minutes.
"""
import copy

LIGHT_STEP_SECONDS = 2.0
LIGHT_OFF_TRANSITION = 50  # 5 s Ausblenden (WLED-Einheit: 100 ms)
ALEXA_STOP = 'Stopp'


def alexa_level(percent):
    """Prozent (0-100) -> Alexa-Lautstaerke 1-10."""
    return max(1, min(10, round(percent / 10)))


def alexa_volume_command(level):
    return f'Lautstärke {level}'


def percent_to_bri(percent):
    return max(1, min(255, round(percent * 255 / 100)))


def ramp(start, end, elapsed, duration):
    if duration <= 0 or elapsed >= duration:
        return end
    if elapsed <= 0:
        return start
    return start + (end - start) * elapsed / duration


class WakeSession:
    def __init__(self, program, player, send_light, effect=None, alarm=None, day=None,
                 alexa=None):
        self.program = program
        self.player = player
        # alexa(text) -> bool: Sprachbefehl ans Echo einreihen (integrations.AlexaSpeaker).
        self.alexa = alexa
        self.alexa_level = None
        self.send_light = send_light
        self.effect_state = copy.deepcopy(effect['state']) if effect else None
        self.alarm = alarm
        self.day = day
        self.item = None
        self.light_start = None
        self.music_start = None
        self.snoozed_until = None
        self.audio_error = None
        self.volume_manual = False
        self._last_light_send = None
        self._last_bri = None
        self._last_volume = None

    @property
    def phase(self):
        if self.snoozed_until is not None:
            return 'snooze'
        return 'light' if self.music_start is None else 'music'

    def start_light(self, now):
        if self.effect_state is None or self.light_start is not None:
            return
        self.light_start = now
        self._update_light(now, force=True)

    @property
    def uses_alexa(self):
        return bool(self.item and self.item.get('alexa'))

    def start_music(self, item, now):
        """Musikphase beginnen. Gibt eine Fehlermeldung zurueck oder None."""
        self.start_light(now)
        self.item = item
        self.snoozed_until = None
        self.music_start = now
        self.audio_error = None
        if self.program['music'] == 'none' or item is None:
            return None
        volume = (self.program['volume_start'] if self.program['volume_ramp_seconds']
                  else self.program['volume_end'])
        if self.uses_alexa:
            level = alexa_level(volume)
            if self.alexa is None or not self.alexa(alexa_volume_command(level)):
                self.audio_error = 'Alexa nicht bereit'
                return self.audio_error
            self.alexa(item['alexa'])
            self.alexa_level = level
            return None
        self._last_volume = self.player.set_volume(volume)
        try:
            self.player.play(item['file'])
        except (OSError, ValueError) as error:
            self.audio_error = str(error)
            return self.audio_error
        return None

    def tick(self, now):
        """True solange der Weckvorgang laeuft, False wenn er zu Ende ist."""
        if self.light_start is not None:
            self._update_light(now)
        if self.snoozed_until is not None:
            if now >= self.snoozed_until:
                self.start_music(self.item, now)
            return True
        if self.music_start is None:
            return True
        elapsed = now - self.music_start
        if elapsed >= self.program['max_minutes'] * 60:
            return False
        if self.program['music'] == 'none' or self.audio_error:
            # Nur Licht (oder Audio kaputt): bis zur Maximaldauer.
            return True
        if self.uses_alexa:
            if not self.volume_manual:
                level = alexa_level(ramp(self.program['volume_start'], self.program['volume_end'],
                                         elapsed, self.program['volume_ramp_seconds']))
                if level != self.alexa_level:
                    self.alexa(alexa_volume_command(level))
                    self.alexa_level = level
            return True
        if not self.volume_manual:
            volume = round(ramp(self.program['volume_start'], self.program['volume_end'],
                                elapsed, self.program['volume_ramp_seconds']))
            if volume != self._last_volume:
                self._last_volume = self.player.set_volume(volume)
        if self.player.finished:
            if self.program['stop_after_song']:
                return False
            try:
                self.player.play(self.item['file'])
            except (OSError, ValueError) as error:
                self.audio_error = str(error)
        return True

    def snooze(self, now):
        self.player.stop()
        if self.uses_alexa and self.snoozed_until is None:
            self.alexa(ALEXA_STOP)
        self.snoozed_until = now + self.program['snooze_minutes'] * 60
        return self.snoozed_until

    def finish(self):
        """Musik aus; Licht je nach Einstellung ausblenden oder anlassen."""
        self.player.stop()
        if self.uses_alexa and self.music_start is not None and self.snoozed_until is None:
            self.alexa(ALEXA_STOP)
        if self.light_start is not None and self.program['light_end'] == 'off':
            self.send_light({'on': False, 'tt': LIGHT_OFF_TRANSITION})
            return True
        return False

    def _update_light(self, now, force=False):
        if not force and now - self._last_light_send < LIGHT_STEP_SECONDS:
            return
        duration = self.program['light_ramp_minutes'] * 60
        percent = ramp(self.program['brightness_start'], self.program['brightness_end'],
                       now - self.light_start, duration)
        bri = percent_to_bri(percent)
        if not force and bri == self._last_bri:
            return
        state = copy.deepcopy(self.effect_state)
        state.update(on=True, bri=bri, tt=0 if force else int(LIGHT_STEP_SECONDS * 10))
        self.send_light(state)
        self._last_light_send, self._last_bri = now, bri
