"""Netzwerk-Live-Check.

Das WLAN des Pi faellt ab und zu kurz weg (meist der WLAN-Stromsparmodus,
siehe README). Ein Aufruf in dieser Zeit endet mit errno 113 "No route to
host". Darum:

- not_connected(error) erkennt Fehler, bei denen die Verbindung gar nicht
  zustande kam. Dann ist sicher nichts angekommen und ein zweiter Versuch
  kann nichts doppelt schalten (anders als nach einem Timeout).
- wait_reachable(host, port, timeout) prueft per TCP-Verbindungsaufbau, bis
  das Ziel wieder erreichbar ist (integrations.http_call wartet damit).
- NetworkMonitor prueft im Wecker-Prozess regelmaessig Home Assistant und
  WLED, protokolliert Ausfaelle mit Dauer und haelt das WLAN wach.
"""
import errno
import socket
import threading
import time
from urllib.error import URLError
from urllib.parse import urlsplit

# Verbindung kam nicht zustande: Netz/Host weg, abgelehnt, Name nicht aufloesbar.
NOT_CONNECTED = {errno.EHOSTUNREACH, errno.ENETUNREACH, errno.ENETDOWN, errno.ECONNREFUSED,
                 errno.EHOSTDOWN, errno.EADDRNOTAVAIL}
PROBE_TIMEOUT = 2.0
PROBE_INTERVAL = 2.0
# So lange warten integrations-Aufrufe hoechstens, bis das Netz wieder da ist.
WAIT_SECONDS = 20
MONITOR_SECONDS = 30
MONITOR_OFFLINE_SECONDS = 5


def not_connected(error):
    """True, wenn der Fehler bedeutet: Verbindung nie aufgebaut, nichts gesendet."""
    if isinstance(error, URLError) and not isinstance(error.reason, str):
        error = error.reason
    if isinstance(error, socket.gaierror):
        return True
    return isinstance(error, OSError) and error.errno in NOT_CONNECTED


def endpoint(url):
    """(host, port) einer http(s)-URL oder None."""
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == 'https' else 80)
    except ValueError:
        return None
    return (parts.hostname, port) if parts.hostname else None


def probe(host, port, timeout=PROBE_TIMEOUT):
    """TCP-Verbindung aufbauen und sofort schliessen. True = erreichbar."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_reachable(host, port, timeout=WAIT_SECONDS, probe=probe, sleep=time.sleep):
    """Bis zu timeout Sekunden warten, bis host:port erreichbar ist. Blockiert!"""
    deadline = time.monotonic() + timeout
    while True:
        if probe(host, port):
            return True
        if time.monotonic() + PROBE_INTERVAL > deadline:
            return False
        sleep(PROBE_INTERVAL)


class NetworkMonitor:
    """Hintergrund-Thread: prueft regelmaessig, ob das Heimnetz erreichbar ist.

    targets() liefert [(host, port)] - erreichbar heisst: eines davon antwortet.
    Wechsel online/offline gehen an report(text); online ist None bis zur
    ersten Pruefung.
    """

    def __init__(self, targets, report=None, probe=probe, interval=MONITOR_SECONDS):
        self.targets = targets
        self.report = report or (lambda message: None)
        self.probe = probe
        self.interval = interval
        self.online = None
        self.offline_since = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def check(self):
        targets = [target for target in self.targets() if target and target[0]]
        if not targets:
            return self.online
        online = any(self.probe(host, port) for host, port in targets)
        if online != self.online:
            if not online:
                self.offline_since = time.monotonic()
                self.report('Netzwerk weg: ' + ', '.join(f'{h}:{p}' for h, p in targets)
                            + ' nicht erreichbar')
            elif self.online is False:
                seconds = int(time.monotonic() - self.offline_since)
                self.report(f'Netzwerk wieder da (nach {seconds} s)')
            self.online = online
        return online

    def _run(self):
        while not self._stop.is_set():
            online = self.check()
            self._stop.wait(MONITOR_OFFLINE_SECONDS if online is False else self.interval)

    def close(self):
        self._stop.set()
