#!/bin/bash
# Systemteil des Weckers einrichten bzw. aktualisieren (einmal mit sudo):
#   sudo tools/install_system.sh
#
# - systemd-Dienste (Wecker, Weboberflaeche) mit Restart=always
# - WLAN-Waechter (alarmclock-netwatch.timer, siehe tools/netwatch.sh)
# - Journal dauerhaft speichern (Logs ueberleben einen Neustart)
# - Hardware-Watchdog (haengt der Pi, startet er neu)
# - WLAN-Stromsparmodus aus, NetworkManager gibt Neuverbinden nie auf
# Am Ende werden Wecker und Weboberflaeche neu gestartet.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$(id -u)" != 0 ]; then
    echo "Bitte mit sudo starten: sudo $0" >&2
    exit 1
fi

echo "== Dienste"
install -m 644 systemd/alarmclock.service systemd/alarmclock-web.service \
    systemd/alarmclock-netwatch.service systemd/alarmclock-netwatch.timer /etc/systemd/system/
# Root-eigene Kopie: der Waechter laeuft als root, die Projektdateien gehoeren pi.
install -m 755 -o root -g root tools/netwatch.sh /usr/local/sbin/alarmclock-netwatch

echo "== Journal dauerhaft"
install -d /etc/systemd/journald.conf.d /var/log/journal
install -m 644 systemd/journald-persistent.conf /etc/systemd/journald.conf.d/90-alarmclock-persistent.conf
systemd-tmpfiles --create --prefix /var/log/journal
systemctl restart systemd-journald
journalctl --flush

echo "== Hardware-Watchdog"
install -d /etc/systemd/system.conf.d
install -m 644 systemd/watchdog.conf /etc/systemd/system.conf.d/90-alarmclock-watchdog.conf
systemctl daemon-reexec

echo "== WLAN"
install -d /etc/NetworkManager/conf.d
install -m 644 networkmanager/wifi-powersave-off.conf /etc/NetworkManager/conf.d/
# Standard sind 4 Versuche, danach verbindet NetworkManager nicht mehr von selbst.
nmcli -g UUID,TYPE connection show | while IFS=: read -r uuid type; do
    if [ "$type" = "802-11-wireless" ]; then
        nmcli connection modify "$uuid" connection.autoconnect-retries 0
        echo "  $(nmcli -g connection.id connection show "$uuid"): Neuverbinden ohne Limit"
    fi
done

echo "== Starten"
systemctl daemon-reload
systemctl enable alarmclock.service alarmclock-web.service >/dev/null
systemctl enable --now alarmclock-netwatch.timer
systemctl restart alarmclock.service alarmclock-web.service
systemctl --no-pager --lines=0 status alarmclock.service alarmclock-web.service alarmclock-netwatch.timer
echo "Fertig. Logs: journalctl -u alarmclock.service -u alarmclock-netwatch.service --since yesterday"
