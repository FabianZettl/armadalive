#!/bin/bash
# Armada OS / ArmadaLive health check for the Thor (run it on the device or over ssh after an OS update): services, the bottom session, the on-screen keyboard, the AYN button route, brightness, power, helper, Steam and ES-DE. Prints PASS / FAIL / INFO. Only brightness and the keyboard are touched briefly, and put back.
export XDG_RUNTIME_DIR=/run/user/$(id -u)
PY=~/.local/share/armadalive/venv/bin/python; [ -x $PY ] || PY=python3
SRC=~/.local/share/armadalive
res() { printf '%-5s %s\n' "$1" "$2"; }
check() { local name=$1; shift; local out; out=$("$@" 2>&1); local rc=$?; if [ $rc = 0 ]; then res PASS "$name${out:+  ($(echo "$out" | head -1 | cut -c1-100))}"; else res FAIL "$name  ($(echo "$out" | head -1 | cut -c1-110))"; fi; }
active() { systemctl --user is-active "$1" >/dev/null 2>&1 || systemctl is-active "$1" >/dev/null 2>&1; }

echo "== System"; . /etc/os-release; echo "OS $VERSION | kernel $(uname -r) | boot $(uptime -s)"
for u in armadalive armada-bottom-screen armada-bottom-gamescope armada-powerbuttond steamos-manager; do check "service $u" bash -c "systemctl --user is-active $u || systemctl is-active $u"; done
check "service inputplumber" systemctl is-active inputplumber
check "Decky PluginLoader" pgrep -f PluginLoader
check "bottom Plasma socket" test -S $XDG_RUNTIME_DIR/armada-plasma-bottom
check "ArmadaLive process" pgrep -f "python.* -m armadalive"
check "autostart at boot (journal)" bash -c "journalctl --user -u armadalive -b --no-pager | grep -q 'Started armadalive' && ! journalctl --user -u armadalive -b --no-pager | grep -q 'nothing to show it on'"

echo "== Bottom session / window / keyboard"
cat > /tmp/ac_kb.py <<'PY'
import sys, time
sys.path.insert(0, "/var/home/armada/.local/share/armadalive")
from armadalive import shell
print("bus", bool(shell._find_bus()))
ok = shell.activate_window(); print("activate", ok)
was = shell.keyboard_visible(); shell.keyboard_show(); time.sleep(1.2); shown = shell.keyboard_visible()
print("keyboard: forceActivate ->", "active" if shell._kb("get-property", *shell.KB, "active") == "b true" else "not active", "| visible", shown)
active = shell._kb("get-property", *shell.KB, "active") == "b true"
shell.keyboard_hide(); time.sleep(0.5)
sys.exit(0 if (shell._find_bus() and ok and active) else 1)
PY
check "KWin bus + window activate + on-screen keyboard show/hide" $PY /tmp/ac_kb.py
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
check "InputPlumber DBusDevice objects" bash -c "busctl --system tree org.shadowblip.InputPlumber 2>/dev/null | grep -q dbus"
cat > /tmp/ac_ayn.py <<'PY'
import sys
sys.path.insert(0, "/var/home/armada/.local/share/armadalive")
from PySide6.QtCore import QCoreApplication
a = QCoreApplication([])
from armadalive.ayn import AynButton
b = AynButton(); print("subscribed", b.connected); sys.exit(0 if b.connected else 1)
PY
check "ArmadaLive subscribes to the AYN event" $PY /tmp/ac_ayn.py
echo "INFO  AYN taps seen by ArmadaLive since boot: $(journalctl --user -u armadalive -b --no-pager | grep -c 'AYN:')  (press the button to see this grow)"

echo "== Screens"
B=/sys/class/backlight
for d in $B/*; do echo "INFO  $(basename $d) $(cat $d/brightness)/$(cat $d/max_brightness)"; done
SESS=$(loginctl list-sessions --no-legend | awk '$4 ~ /seat/ {print $1; exit}')
cat > /tmp/ac_br.sh <<SH
dev=ae94000.dsi.0; f=$B/\$dev/brightness; orig=\$(cat \$f); t=\$(( \$(cat $B/\$dev/max_brightness) * 6 / 10 )); [ "\$t" = "\$orig" ] && t=\$(( t - 20 ))
busctl --system call org.freedesktop.login1 /org/freedesktop/login1/session/$SESS org.freedesktop.login1.Session SetBrightness ssu backlight \$dev \$t >/dev/null || exit 2
sleep 3; got=\$(cat \$f)
busctl --system call org.freedesktop.login1 /org/freedesktop/login1/session/$SESS org.freedesktop.login1.Session SetBrightness ssu backlight \$dev \$orig >/dev/null
[ "\$got" = "\$t" ] && echo "set \$t, held \$got, restored \$orig" || { echo "set \$t but read \$got"; exit 1; }
SH
check "bottom brightness set and held for 3 s" bash /tmp/ac_br.sh

echo "== Power, helper, radios, audio"
check "armada-power status" bash -c "armada-power status | head -1"
check "root helper present" test -x /etc/armadalive/armadalive-helper
check "sudo rule for the helper (no password)" sudo -n -l /etc/armadalive/armadalive-helper
check "charge limit write accepted" bash -c "sudo -n /etc/armadalive/armadalive-helper charge-limit 100"
echo "INFO  charge_control_end_threshold reads: $(cat /sys/class/power_supply/battery/charge_control_end_threshold 2>&1)"
check "Wi-Fi radio state" bash -c "cat /sys/class/rfkill/rfkill*/soft | head -1; nmcli -t -f WIFI radio | head -1"
check "Bluetooth controller" bash -c "bluetoothctl show 2>/dev/null | grep -q 'Powered'"
check "volume readable (wpctl)" bash -c "wpctl get-volume @DEFAULT_AUDIO_SINK@"
check "gamepad device present" bash -c "grep -q 'Handlers=.*js' /proc/bus/input/devices"
check "/dev/uinput writable (trackpad, back buttons)" test -w /dev/uinput

echo "== Steam / gamescope / ES-DE"
check "Steam debug port 8080 (SharedJSContext)" bash -c "curl -s -m 4 localhost:8080/json | grep -q SharedJSContext"
check "gamescope stats pipe" test -p $XDG_RUNTIME_DIR/gamescope-stats/stats.pipe
check "main gamescope socket" test -S $XDG_RUNTIME_DIR/gamescope-0
check "ES-DE event hooks installed" bash -c "ls ~/ES-DE/scripts/*/armadalive >/dev/null"

echo "== ArmadaLive code"
check "unit tests on the installed copy" bash -c "cd ~/armadalive-src/armadalive && ~/.local/share/armadalive/venv/bin/python -W ignore -m unittest discover -s tests -t . 2>&1 | tail -3 | tr '\n' ' '"
echo "== errors in this boot's ArmadaLive journal"; journalctl --user -u armadalive -b --no-pager | grep -i -E "traceback|TypeError|ReferenceError|Error " | grep -v atspi | head -5 | cut -c1-150
