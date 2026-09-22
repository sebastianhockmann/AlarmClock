"""WLED-Effektnamen und ihre numerische fx-ID nachschlagen.

effects.json referenziert WLED-Effekte ueber die numerische ID
(state.seg[].fx), nicht ueber den Namen aus der WLED-Oberflaeche
("Effect mode"-Liste). Dieses Skript fragt genau diese Liste live beim
konfigurierten WLED-Geraet ab (Host/Timeout aus settings.json bzw.
config.py, wie der Rest des Programms) und zeigt Name -> ID an, damit man
die passende Zahl von Hand in effects.json eintragen kann.

Start: .venv/bin/python wled_effect_list.py
Suche einschraenken: .venv/bin/python wled_effect_list.py --search aurora
"""

import argparse
import sys

from lighting import WLEDManager


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--search", default="",
                        help="Nur Effekte anzeigen, deren Name diesen Text enthaelt (ohne Gross-/Kleinschreibung)")
    args = parser.parse_args()

    manager = WLEDManager(report=print)
    status = manager.get_status()
    if status is None:
        print(f"WLED nicht erreichbar: {manager.last_error}", file=sys.stderr)
        return 1
    effects = status.get("effects")
    if not isinstance(effects, list):
        print("WLED-Antwort enthaelt keine Effektliste (Firmware zu alt?).", file=sys.stderr)
        return 1

    current_fx = None
    segments = status.get("state", {}).get("seg")
    if isinstance(segments, list) and segments and isinstance(segments[0], dict):
        current_fx = segments[0].get("fx")

    needle = args.search.lower()
    shown = 0
    for fx_id, name in enumerate(effects):
        if needle and needle not in str(name).lower():
            continue
        marker = " <- aktuell" if fx_id == current_fx else ""
        print(f'{fx_id:>3}  {name}{marker}')
        shown += 1
    if shown == 0:
        print("Keine passenden Effekte gefunden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
