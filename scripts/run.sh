#!/bin/sh
# Starts ArmadaLive with whichever Python has PySide6 right now: the system's, else the private copy in the app folder.
# A system update can drop PySide6 from the image (or bring it back); a fixed interpreter then fails on every start.
# The bottom screen is normally a Plasma session (socket armada-plasma-bottom). When that session cannot start, the bottom
# gamescope under it still runs and shows a client fullscreen: use its X11 side (DISPLAY from armada-bottom-env). Its Wayland
# socket shows the window too, but passes no touch to it; X11 does, and has no window frames.
run="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
windowed=""
if [ -S "$run/armada-plasma-bottom" ]; then
    :   # the normal case: the bottom Plasma session
elif [ -r "$run/armada-bottom-env" ]; then
    display=$(sed -n 's/^DISPLAY=//p' "$run/armada-bottom-env" | head -1)
    [ -n "$display" ] && export QT_QPA_PLATFORM=xcb DISPLAY="$display"
else
    # Desktop mode: there is no bottom session, only the one Plasma session of the desktop. Show a normal window in it
    # instead of letting Qt abort on the missing socket (the service then restarted every few seconds).
    for sock in "$run"/wayland-[0-9]*; do
        [ -S "$sock" ] && { export QT_QPA_PLATFORM=wayland WAYLAND_DISPLAY="${sock##*/}"; windowed=--windowed; break; }
    done
    if [ -z "$windowed" ] && [ -n "${DISPLAY:-}" ]; then export QT_QPA_PLATFORM=xcb; windowed=--windowed; fi
    if [ -z "$windowed" ]; then echo "ArmadaLive: no bottom session and no desktop display found; nothing to show it on" >&2; exit 0; fi
fi
[ -n "${ARMADALIVE_DRY_RUN:-}" ] && { echo "platform=${QT_QPA_PLATFORM:-} wayland=${WAYLAND_DISPLAY:-} display=${DISPLAY:-} windowed=$windowed"; exit 0; }
need="import PySide6.QtQuick, PySide6.QtWebSockets, PySide6.QtDBus, PySide6.QtTest"
for py in /usr/bin/python3 "$HOME/.local/share/armadalive/venv/bin/python"; do
    "$py" -c "$need" 2>/dev/null && exec "$py" -m armadalive $windowed
done
echo "ArmadaLive: no Python with PySide6 found; run install.sh again (it fetches a private copy)" >&2
exit 1
