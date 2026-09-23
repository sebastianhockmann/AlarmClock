"""Home-Assistant-Anbindung fuer die Smart-Home-Tasten des Tastenfelds
(Deckenlampe, Alexa-Routinen ueber HA, siehe config.SMART_HOME_ACTIONS).

Der Anbindungsweg (Home Assistant vs. Fauxmo o.ae.) stand beim Schreiben
noch nicht fest. Bis config.HOME_ASSISTANT_URL gesetzt ist, bleibt trigger()
ein reiner Platzhalter: die Taste wird geloggt, es passiert aber nichts -
so laesst sich das Tastenfeld schon jetzt umbelegen, ohne auf die konkrete
Integration zu warten.
"""
import json
import logging
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError
import config

logger = logging.getLogger(__name__)


def trigger(action):
    """Loest eine Smart-Home-Aktion aus; gibt sofort das Label fuers LCD zurueck."""
    label = action.get('label', action.get('entity_id', '?'))
    if not config.HOME_ASSISTANT_URL:
        logger.info('Smart-Home-Aktion "%s" ausgeloest, aber HOME_ASSISTANT_URL ist '
                    'nicht konfiguriert - Integration noch nicht angebunden.', label)
        return label
    threading.Thread(target=_call, args=(action,), daemon=True).start()
    return label


def _call(action):
    domain, _, service = action['service'].partition('.')
    url = f"{config.HOME_ASSISTANT_URL}/api/services/{domain}/{service}"
    headers = {'Content-Type': 'application/json'}
    if config.HOME_ASSISTANT_TOKEN:
        headers['Authorization'] = f'Bearer {config.HOME_ASSISTANT_TOKEN}'
    request = Request(url, data=json.dumps({'entity_id': action['entity_id']}).encode('utf-8'),
                      headers=headers, method='POST')
    try:
        with urlopen(request, timeout=3):
            pass
    except (URLError, OSError) as error:
        logger.warning('Home-Assistant-Aufruf fuer "%s" fehlgeschlagen: %s',
                       action.get('label', action.get('entity_id')), error)
