"""Steuerkanal Weboberflaeche -> Wecker-Prozess (UDP, nur 127.0.0.1).

Frueher spielte die Weboberflaeche Musik in einem eigenen mpg123-Prozess
ab und kollidierte dabei mit dem Wecker um das ALSA-Geraet. Jetzt schickt
sie Befehle an den Wecker; der legt sie in dieselbe Eingabe-Warteschlange
wie Tastendruecke. So gibt es genau einen Besitzer fuer Audio, LCD und WLED.

Protokoll: ein JSON-Datagramm {"event": ..., "value": ...} bzw.
{"query": "status"}; Antwort ein JSON-Datagramm.
"""
import json
import socket
import threading
import config

# Ereignisse, die von aussen kommen duerfen (Eingabegeraete nutzen emit direkt).
REMOTE_EVENTS = ('key', 'action', 'play_today', 'play_random', 'play_file', 'stop_audio',
                 'wake_test', 'wake_stop', 'volume', 'notice')
MAX_DATAGRAM = 8192


class CommandServer:
    def __init__(self, emit, status=None, host=None, port=None):
        self.emit = emit
        self.status = status or (lambda: {})
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((host or config.IPC_HOST, config.IPC_PORT if port is None else port))
        self.socket.settimeout(0.2)
        self.address = self.socket.getsockname()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _handle(self, message):
        if not isinstance(message, dict):
            return {'ok': False, 'error': 'Ungueltige Nachricht'}
        if message.get('query') == 'status':
            return {'ok': True, 'status': self.status()}
        event = message.get('event')
        if event not in REMOTE_EVENTS:
            return {'ok': False, 'error': f'Unbekannter Befehl: {event}'}
        self.emit(event, message.get('value'))
        return {'ok': True}

    def _run(self):
        while not self.stopping.is_set():
            try:
                data, sender = self.socket.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                reply = self._handle(json.loads(data))
            except ValueError:
                reply = {'ok': False, 'error': 'Ungueltiges JSON'}
            try:
                self.socket.sendto(json.dumps(reply, default=str).encode('utf-8'), sender)
            except OSError:
                pass

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=1)
        self.socket.close()


def _request(message, timeout, address=None):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(timeout)
        client.sendto(json.dumps(message).encode('utf-8'),
                      address or (config.IPC_HOST, config.IPC_PORT))
        data, _ = client.recvfrom(MAX_DATAGRAM * 8)
    return json.loads(data)


def send(event, value=None, timeout=1.0, address=None):
    """Befehl an den Wecker. OSError, wenn der Wecker-Prozess nicht antwortet."""
    try:
        reply = _request({'event': event, 'value': value}, timeout, address)
    except (socket.timeout, ConnectionError) as error:
        raise OSError('Wecker-Prozess nicht erreichbar') from error
    if not reply.get('ok'):
        raise ValueError(reply.get('error', 'Befehl abgelehnt'))
    return reply


def status(timeout=0.5, address=None):
    """Zustand des Weckers oder None, wenn er nicht laeuft."""
    try:
        return _request({'query': 'status'}, timeout, address).get('status')
    except (OSError, ValueError):
        return None
