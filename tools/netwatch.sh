#!/bin/bash
# WLAN-Waechter fuer den Wecker-Pi (laeuft als root, jede Minute per
# alarmclock-netwatch.timer; installiert nach /usr/local/sbin/alarmclock-netwatch).
#
# Hintergrund: Faellt das WLAN aus und NetworkManager verbindet nicht von
# selbst neu (schwaches Signal, DFS-Kanalwechsel am Router, haengender
# brcmfmac-Treiber), bleibt der Pi bis zum naechsten Neustart offline -
# Alexa, WLED und Home Assistant gehen dann nicht, nur das Display laeuft.
#
# Ist das Gateway nicht per ping erreichbar, wird stufenweise repariert:
#   ab  2 min  WLAN neu verbinden (nmcli device connect)
#   ab  5 min  NetworkManager neu starten
#   ab 10 min  WLAN-Treiber neu laden (brcmfmac)
#   ab 20 min  Neustart - hoechstens alle 6 h und nie, solange der Wecker klingelt
# Alles landet im Journal: journalctl -u alarmclock-netwatch.service
set -u

IFACE=${NETWATCH_IFACE:-wlan0}
IPC_PORT=${NETWATCH_IPC_PORT:-8099}
RECONNECT_AFTER=120
RESTART_AFTER=300
DRIVER_AFTER=600
REBOOT_AFTER=1200
REBOOT_GAP=21600
RUN_DIR=${NETWATCH_RUN_DIR:-/run/alarmclock-netwatch}       # tmpfs: seit wann offline, welche Stufe
LIB_DIR=${NETWATCH_LIB_DIR:-/var/lib/alarmclock-netwatch}   # bleibt: Zeitpunkt des letzten Neustarts

mkdir -p "$RUN_DIR" "$LIB_DIR"
now=$(date +%s)

online() {
    local gateway
    gateway=$(ip -4 route show default dev "$IFACE" 2>/dev/null | awk '{print $3; exit}')
    [ -n "$gateway" ] || return 1
    ping -c 3 -W 2 -I "$IFACE" "$gateway" >/dev/null 2>&1
}

# Klingelt der Wecker gerade (oder Licht-Vorlauf/Schlummern)? Dann kein Neustart.
# Eigene kleine Abfrage mit System-Python, ohne Projektcode als root auszufuehren.
alarm_running() {
    python3 -I -c '
import json, socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(1)
try:
    s.sendto(b"{\"query\": \"status\"}", ("127.0.0.1", int(sys.argv[1])))
    status = json.loads(s.recvfrom(65536)[0]).get("status") or {}
except (OSError, ValueError):
    sys.exit(1)
sys.exit(0 if status.get("phase") else 1)
' "$IPC_PORT"
}

if online; then
    if [ -f "$RUN_DIR/since" ]; then
        echo "WLAN wieder da nach $(( now - $(cat "$RUN_DIR/since") )) s (Stufe $(cat "$RUN_DIR/step" 2>/dev/null || echo 0))"
        rm -f "$RUN_DIR/since" "$RUN_DIR/step"
    fi
    exit 0
fi

if [ ! -f "$RUN_DIR/since" ]; then
    echo "$now" > "$RUN_DIR/since"
    echo 0 > "$RUN_DIR/step"
    echo "WLAN weg: Gateway auf $IFACE nicht erreichbar"
    nmcli -t -f DEVICE,STATE,CONNECTION device status 2>&1 | sed 's/^/  /'
    exit 0
fi

since=$(cat "$RUN_DIR/since")
step=$(cat "$RUN_DIR/step" 2>/dev/null || echo 0)
offline=$(( now - since ))

if [ "$step" -lt 1 ] && [ "$offline" -ge "$RECONNECT_AFTER" ]; then
    echo "Offline seit ${offline} s: verbinde WLAN neu"
    nmcli device connect "$IFACE" 2>&1 | sed 's/^/  /'
    echo 1 > "$RUN_DIR/step"
elif [ "$step" -lt 2 ] && [ "$offline" -ge "$RESTART_AFTER" ]; then
    echo "Offline seit ${offline} s: starte NetworkManager neu"
    systemctl restart NetworkManager
    echo 2 > "$RUN_DIR/step"
elif [ "$step" -lt 3 ] && [ "$offline" -ge "$DRIVER_AFTER" ]; then
    echo "Offline seit ${offline} s: lade WLAN-Treiber neu"
    modprobe -r brcmfmac_wcc 2>/dev/null
    modprobe -r brcmfmac 2>&1 | sed 's/^/  /'
    sleep 3
    modprobe brcmfmac 2>&1 | sed 's/^/  /'
    echo 3 > "$RUN_DIR/step"
elif [ "$step" -lt 4 ] && [ "$offline" -ge "$REBOOT_AFTER" ]; then
    last=$(cat "$LIB_DIR/last_reboot" 2>/dev/null || echo 0)
    if [ $(( now - last )) -lt "$REBOOT_GAP" ]; then
        echo "Offline seit ${offline} s: Neustart erst $(( (last + REBOOT_GAP - now) / 60 )) min spaeter erlaubt"
        echo 4 > "$RUN_DIR/step"
    elif alarm_running; then
        echo "Offline seit ${offline} s: Wecker laeuft, Neustart verschoben"
    else
        echo "Offline seit ${offline} s: Neustart"
        echo "$now" > "$LIB_DIR/last_reboot"
        sync
        systemctl reboot
    fi
fi
exit 0
