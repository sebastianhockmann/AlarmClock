#!/usr/bin/env python3
"""Schulferien Thueringen von openholidaysapi.org in config/school_holidays.json schreiben.

Das ist der versionierte Startbestand, der auch ohne Netz gilt. Der Wecker
holt sich zusaetzlich taeglich selbst einen Cache (school_calendar.HolidayUpdater).

    python tools/update_school_holidays.py [erstes_jahr] [letztes_jahr]
"""
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import school_calendar  # noqa: E402


def main():
    first = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year
    last = int(sys.argv[2]) if len(sys.argv) > 2 else first + 2
    periods = school_calendar.fetch(first, last)
    school_calendar.write_periods(school_calendar.SEED_FILE, periods)
    for period in periods:
        print(f'{period["start"]} - {period["end"]}  {period["name"]}')
    print(f'{len(periods)} Eintraege nach {school_calendar.SEED_FILE} geschrieben')


if __name__ == '__main__':
    main()
