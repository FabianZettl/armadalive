#!/bin/sh
# Starts ArmadaLive with whichever Python has PySide6 right now: the system's, else the private copy in the app folder.
# A system update can drop PySide6 from the image (or bring it back); a fixed interpreter then fails on every start.
# The bottom screen is normally a Plasma session (socket armada-plasma-bottom). When that session cannot start, the bottom
# gamescope under it still runs and shows a client fullscreen: use its X11 side (DISPLAY from armada-bottom-env). Its Wayland
# socket shows the window too, but passes no touch to it; X11 does, and has no window frames.
run="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
windowed=""
# At boot this unit starts before the session it needs, in Game mode (the bottom session) as well as on the desktop (its display). Look until one is there
# (ARMADALIVE_WAIT seconds, 60 by default) and fail after that, so the unit tries again: a quiet exit counts as success for systemd, which never retried (0.4.6 to 0.5.1).
# The marker file means Game mode's bottom session has been started but is not up yet: the desktop is not looked for then.
n=0
while :; do
    if [ -S "$run/armada-plasma-bottom" ]; then
        break   # the normal case: the bottom Plasma session
    elif [ -r "$run/armada-bottom-env" ] && [ "$n" -ge "${ARMADALIVE_X11_AFTER:-30}" ]; then
        # the bottom gamescope is there but its Plasma session never came up: show the window on its X11 side. Not before the wait is over: at boot the
        # gamescope (and this file) come first, and an X11 window is invisible to Plasma's KWin: no activation through it, no on-screen keyboard.
        display=$(sed -n 's/^DISPLAY=//p' "$run/armada-bottom-env" | head -1)
        [ -n "$display" ] && export QT_QPA_PLATFORM=xcb DISPLAY="$display"
        break
    elif [ ! -r "$run/armada-bottom-env" ] && [ ! -e "$run/armada-bottom-screen-active" ]; then
        # Desktop mode: there is no bottom session, only the one Plasma session of the desktop. Show a normal window in it
        for sock in "$run"/wayland-[0-9]*; do
            [ -S "$sock" ] && { export QT_QPA_PLATFORM=wayland WAYLAND_DISPLAY="${sock##*/}"; windowed=--windowed; break; }
        done
        if [ -z "$windowed" ] && [ -n "${DISPLAY:-}" ]; then export QT_QPA_PLATFORM=xcb; windowed=--windowed; fi
        [ -n "$windowed" ] && break
    fi
    [ "$n" -ge "${ARMADALIVE_WAIT:-60}" ] && { echo "ArmadaLive: no bottom session and no desktop display found (yet); the unit tries again" >&2; exit 1; }
    sleep 1; n=$((n + 1))
done
[ -n "${ARMADALIVE_DRY_RUN:-}" ] && { echo "platform=${QT_QPA_PLATFORM:-} wayland=${WAYLAND_DISPLAY:-} display=${DISPLAY:-} windowed=$windowed"; exit 0; }
need="import PySide6.QtQuick, PySide6.QtWebSockets, PySide6.QtDBus, PySide6.QtTest"
for py in ${ARMADALIVE_PYTHON:-/usr/bin/python3 "$HOME/.local/share/armadalive/venv/bin/python"}; do
    "$py" -c "$need" 2>/dev/null || continue
    if [ "${QT_QPA_PLATFORM:-}" = xcb ] && [ -z "$windowed" ]; then
        # On the X11 side of the bottom gamescope only until the Plasma session is up: an X11 window is invisible to Plasma's KWin (no AYN tap, no keyboard).
        # When its socket shows up the app is ended with a failure, so the unit starts it again, and this time as a Plasma client.
        "$py" -m armadalive $windowed &
        app=$!
        ( while kill -0 "$app" 2>/dev/null; do [ -S "$run/armada-plasma-bottom" ] && { kill -TERM "$app"; break; }; sleep "${ARMADALIVE_WATCH:-2}"; done ) &
        wait "$app"
        exit $?
    fi
    exec "$py" -m armadalive $windowed
done
echo "ArmadaLive: no Python with PySide6 found; run install.sh again (it fetches a private copy)" >&2
exit 1
