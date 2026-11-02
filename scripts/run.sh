#!/bin/sh
# Starts ArmadaLive with whichever Python has PySide6 right now: the system's, else the private copy in the app folder.
# A system update can drop PySide6 from the image (or bring it back); a fixed interpreter then fails on every start.
# The bottom screen is normally a Plasma session (socket armada-plasma-bottom). When that session cannot start, the bottom
# gamescope under it still runs and shows a client fullscreen: use its X11 side (DISPLAY from armada-bottom-env). Its Wayland
# socket shows the window too, but passes no touch to it; X11 does, and has no window frames.
run="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ ! -S "$run/armada-plasma-bottom" ] && [ -r "$run/armada-bottom-env" ]; then
    display=$(sed -n 's/^DISPLAY=//p' "$run/armada-bottom-env" | head -1)
    [ -n "$display" ] && export QT_QPA_PLATFORM=xcb DISPLAY="$display"
fi
need="import PySide6.QtQuick, PySide6.QtWebSockets, PySide6.QtDBus, PySide6.QtTest"
for py in /usr/bin/python3 "$HOME/.local/share/armadalive/venv/bin/python"; do
    "$py" -c "$need" 2>/dev/null && exec "$py" -m armadalive
done
echo "ArmadaLive: no Python with PySide6 found; run install.sh again (it fetches a private copy)" >&2
exit 1
