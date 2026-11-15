#!/bin/bash
# Armada OS / ArmadaLive health check for the Thor (run it on the device or over ssh after an OS update): services, the bottom session, the on-screen keyboard, the AYN button route, brightness, power, helper, Steam and ES-DE. Prints PASS / FAIL / INFO. Only brightness and the keyboard are touched briefly, and put back.
export XDG_RUNTIME_DIR=/run/user/$(id -u)
SRC="$HOME/.local/share/armadalive"
PY=${ARMADALIVE_PYTHON:-/usr/bin/python3}
if [ -z "${ARMADALIVE_PYTHON:-}" ]; then
    need="import PySide6.QtQuick, PySide6.QtWebSockets, PySide6.QtDBus, PySide6.QtTest"
    for candidate in /usr/bin/python3 "$SRC/venv/bin/python"; do
        if "$candidate" -c "$need" 2>/dev/null; then
            PY=$candidate
            break
        fi
    done
fi

failures=0
res() { printf '%-5s %s\n' "$1" "$2"; }
check() {
    local name=$1 out rc
    shift
    out=$("$@" 2>&1)
    rc=$?
    if [ "$rc" = 0 ]; then
        res PASS "$name${out:+  ($(printf '%s\n' "$out" | head -1 | cut -c1-100))}"
    else
        failures=$((failures + 1))
        res FAIL "$name${out:+  ($(printf '%s\n' "$out" | head -1 | cut -c1-110))}"
    fi
}

source_tests() (
    local checkout=${ARMADALIVE_TEST_CHECKOUT:-$HOME/armadalive-src/armadalive}
    local test_home site out rc
    if [ ! -d "$checkout/tests" ]; then
        printf 'No test checkout at %s (set ARMADALIVE_TEST_CHECKOUT).\n' "$checkout"
        return 1
    fi
    cd "$checkout" || return
    test_home=$(mktemp -d) || return
    trap 'rm -rf -- "$test_home"' EXIT
    if site=$("$PY" -m site --user-site 2>/dev/null); then
        export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$site"
    fi
    out=$(HOME="$test_home" QT_QPA_PLATFORM=offscreen "$PY" -W ignore -m unittest discover -s tests -t . 2>&1)
    rc=$?
    printf '%s\n' "$out" | tail -3 | tr '\n' ' '
    return "$rc"
)

echo "== System"; . /etc/os-release; echo "OS $VERSION | kernel $(uname -r) | boot $(uptime -s)"
for u in armadalive armada-bottom-screen armada-bottom-gamescope armada-powerbuttond steamos-manager; do check "service $u" bash -c "systemctl --user is-active $u || systemctl is-active $u"; done
check "service inputplumber" systemctl is-active inputplumber
check "Decky PluginLoader" pgrep -f PluginLoader
check "bottom Plasma socket" test -S $XDG_RUNTIME_DIR/armada-plasma-bottom
check "ArmadaLive process" pgrep -f "python.* -m armadalive"
check "autostart at boot (journal)" bash -o pipefail -c 'journalctl --user -u armadalive -b --no-pager | awk "/Started armadalive/{started=1} /nothing to show it on/{missing=1} END{exit !(started && !missing)}"'

echo "== Bottom session / window / keyboard"
cat > /tmp/ac_kb.py <<'PY'
import sys, time
from armadalive import shell
if not shell._find_bus():
    sys.exit("Could not find the KWin bus")

def visible():
    return shell._kb("get-property", *shell.KB, "visible")

initial = visible()
if initial not in ("b true", "b false"):
    sys.exit("Could not read initial keyboard visibility")

try:
    activated = shell.activate_window()
    shell.keyboard_show()
    time.sleep(1.2)
    shown = visible() == "b true"
    active = shell._kb("get-property", *shell.KB, "active") == "b true"
finally:
    if visible() != initial:
        if initial == "b true":
            shell.keyboard_show()
        else:
            shell.keyboard_hide()
        time.sleep(0.5)
    restored = visible() == initial

if not restored:
    sys.exit("Could not restore initial keyboard visibility")
if not activated:
    sys.exit("Could not activate the ArmadaLive window")
if not active:
    sys.exit("Keyboard did not become active")
print("window activated, keyboard active, visible:", shown, "| initial visibility restored")
PY
check "KWin bus + window activate + on-screen keyboard show/hide" env "PYTHONPATH=$SRC${PYTHONPATH:+:$PYTHONPATH}" "$PY" /tmp/ac_kb.py
cat > /tmp/ac_wl.sh <<'SH'
pid=$(pgrep -f "python.* -m armadalive" | head -1); [ -n "$pid" ] || exit 1
tr '\0' '\n' < /proc/$pid/environ | grep -E '^(QT_QPA_PLATFORM|DISPLAY|WAYLAND_DISPLAY)=' | tr '\n' ' '
tr '\0' '\n' < /proc/$pid/environ | grep -q '^QT_QPA_PLATFORM=wayland'
SH
check "ArmadaLive is a Wayland client of the bottom Plasma (not X11)" bash /tmp/ac_wl.sh
echo "INFO  ES-DE state dir exists: $(test -d $XDG_RUNTIME_DIR/armadalive && echo yes || echo 'no, the first ES-DE event creates it')"
check "plasma-keyboard process" pgrep -f "plasma-keyboard|maliit"

echo "== AYN button"
check "InputPlumber override installed" test -f /etc/inputplumber/capability_maps.d/ayn_type2.yaml
check "override sends the AYN key to ui_quick2" grep -q "dbus: ui_quick2" /etc/inputplumber/capability_maps.d/ayn_type2.yaml
cat > /tmp/ac_map.sh <<'SH'
src=/usr/share/inputplumber/capability_maps/ayn_type2.yaml; dst=/etc/inputplumber/capability_maps.d/ayn_type2.yaml
grep -q 'button: QuickAccess2' "$src" || { echo "system map has no QuickAccess2 (changed upstream)"; exit 1; }
sed '/name: AYN Key/,/button: QuickAccess2/{s/^      gamepad:$/      dbus: ui_quick2/;/button: QuickAccess2/d}' "$src" > /tmp/ac_expected.yaml
diff <(grep -v '^#' /tmp/ac_expected.yaml) <(grep -v '^#' "$dst") >/dev/null && echo "override matches the current system map" || { echo "override differs from the current system map: run ayn-button.sh again"; exit 1; }
SH
check "override is current with the system's map" bash /tmp/ac_map.sh
check "InputPlumber D-Bus service" busctl --system status org.shadowblip.InputPlumber
check "InputPlumber DBusDevice objects" bash -o pipefail -c "busctl --system tree org.shadowblip.InputPlumber 2>/dev/null | grep dbus >/dev/null"
cat > /tmp/ac_ayn.py <<'PY'
import sys
from PySide6.QtCore import QCoreApplication
a = QCoreApplication([])
from armadalive.ayn import AynButton
b = AynButton(); print("subscribed", b.connected); sys.exit(0 if b.connected else 1)
PY
check "ArmadaLive subscribes to the AYN event" env "PYTHONPATH=$SRC${PYTHONPATH:+:$PYTHONPATH}" "$PY" /tmp/ac_ayn.py
echo "INFO  AYN taps seen by ArmadaLive since boot: $(journalctl --user -u armadalive -b --no-pager | grep -c 'AYN:')  (press the button to see this grow)"

echo "== Screens"
B=/sys/class/backlight
for d in $B/*; do echo "INFO  $(basename $d) $(cat $d/brightness)/$(cat $d/max_brightness)"; done
SESS=$(loginctl list-sessions --no-legend | awk '$4 ~ /seat/ {print $1; exit}')
cat > /tmp/ac_br.sh <<SH
dev=ae94000.dsi.0
file="$B/\$dev/brightness"
original=\$(cat "\$file") || exit 1
maximum=\$(cat "$B/\$dev/max_brightness") || exit 1
case "\$original" in ''|*[!0-9]*) echo "Invalid initial brightness"; exit 1 ;; esac
case "\$maximum" in ''|*[!0-9]*) echo "Invalid maximum brightness"; exit 1 ;; esac
[ "\$maximum" -gt 0 ] && [ "\$original" -le "\$maximum" ] || { echo "Invalid brightness range"; exit 1; }
target=\$(( maximum * 6 / 10 ))
if [ "\$target" -eq "\$original" ]; then
    target=\$(( target >= 20 ? target - 20 : target + 1 ))
fi

set_brightness() {
    busctl --system call org.freedesktop.login1 /org/freedesktop/login1/session/$SESS org.freedesktop.login1.Session SetBrightness ssu backlight "\$dev" "\$1" >/dev/null
}

restore_brightness() {
    rc=\$?
    trap - EXIT
    if ! set_brightness "\$original"; then
        echo "Could not restore brightness to \$original" >&2
        exit 1
    fi
    if ! restored=\$(cat "\$file") || [ "\$restored" != "\$original" ]; then
        echo "Could not confirm restored brightness \$original (read \$restored)" >&2
        exit 1
    fi
    if [ "\$rc" = 0 ]; then
        echo "set \$target, held \$held, restored \$restored"
    fi
    exit "\$rc"
}

trap restore_brightness EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
set_brightness "\$target" || { echo "Could not set test brightness"; exit 1; }
sleep 3 || exit 1
held=\$(cat "\$file") || exit 1
[ "\$held" = "\$target" ] || { echo "set \$target but read \$held"; exit 1; }
SH
check "bottom brightness set and held for 3 s" bash /tmp/ac_br.sh

echo "== Power, helper, radios, audio"
check "armada-power status" armada-power status
check "root helper present" test -x /etc/armadalive/armadalive-helper
check "sudo rule for the helper (no password)" sudo -n -l /etc/armadalive/armadalive-helper
check "charge limit readable" cat /sys/class/power_supply/battery/charge_control_end_threshold
check "Wi-Fi radio state" nmcli -t -f WIFI radio
check "Bluetooth controller" bash -o pipefail -c "bluetoothctl show 2>/dev/null | grep 'Powered' >/dev/null"
check "volume readable (wpctl)" bash -c "wpctl get-volume @DEFAULT_AUDIO_SINK@"
check "gamepad device present" bash -c "grep -q 'Handlers=.*js' /proc/bus/input/devices"
check "/dev/uinput writable (trackpad, back buttons)" test -w /dev/uinput

echo "== Steam / gamescope / ES-DE"
check "Steam debug port 8080 (SharedJSContext)" bash -o pipefail -c "curl -fsS -m 4 localhost:8080/json | grep SharedJSContext >/dev/null"
check "gamescope stats pipe" test -p $XDG_RUNTIME_DIR/gamescope-stats/stats.pipe
check "main gamescope socket" test -S $XDG_RUNTIME_DIR/gamescope-0
check "ES-DE event hooks installed" bash -c "ls ~/ES-DE/scripts/*/armadalive >/dev/null"

echo "== ArmadaLive code"
check "unit tests from source checkout" source_tests
echo "== errors in this boot's ArmadaLive journal"; journalctl --user -u armadalive -b --no-pager | grep -i -E "traceback|TypeError|ReferenceError|Error " | grep -v atspi | head -5 | cut -c1-150
exit "$((failures > 0))"
