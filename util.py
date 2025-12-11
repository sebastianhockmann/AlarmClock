# util.py
#
# Gemeinsame Hilfsfunktionen für Zeitbereiche und Formatierungen.

from datetime import time as dtime


def parse_hhmm(s: str) -> dtime:
    """
    Wandelt einen String 'HH:MM' in ein datetime.time Objekt um.
    Beispiel: parse_hhmm("22:30") -> datetime.time(22, 30)
    """
    h, m = s.split(":")
    return dtime(int(h), int(m))


def time_in_range(t: dtime, start: dtime, end: dtime) -> bool:
    """
    Prüft, ob die Uhrzeit t im Bereich [start, end) liegt.
    
    Unterstützt auch Zeitbereiche über Mitternacht:
        start=22:00, end=06:00 bedeutet:
        t >= 22:00 ODER t < 06:00
    """
    if start <= end:
        return start <= t < end
    else:
        # über Mitternacht (Einschluss: 22:00–06:00)
        return t >= start or t < end


def center_text(text: str, width: int) -> str:
    """
    Zentriert einen Text auf eine bestimmte Breite, falls nötig abgeschnitten.
    """
    txt = text[:width]  # sicherstellen, dass der Text nicht zu lang ist
    return txt.center(width)


def scrolling_text(text: str, width: int, offset: int) -> str:
    """
    Für animiertes Scrollen langer Texte über das Display.
    offset gibt an, welcher 'Ausschnitt' gerade angezeigt werden soll.

    Beispiel:
        text="Guten Morgen Tiago!"
        width=16
        offset=3
    """
    if len(text) <= width:
        return text.center(width)

    repeat_text = text + "   "  # kleine Pause beim Scrollen
    start = offset % len(repeat_text)
    window = (repeat_text + repeat_text)[start:start+width]
    return window
