#!/bin/sh
# Install ArmadaLive for the current user (no root needed). Use --uninstall to remove it.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
share="$HOME/.local/share/armadalive"
unit="$HOME/.config/systemd/user/armadalive.service"
desktop="$HOME/.local/share/applications/armadalive.desktop"
events="startup quit system-select game-select game-start game-end"

if [ "${1:-}" = "--uninstall" ]; then
    systemctl --user disable --now armadalive 2>/dev/null || true
    for e in $events; do rm -f "$HOME/ES-DE/scripts/$e/armadalive"; done
    rm -rf "$share" "$unit" "$desktop"
    systemctl --user daemon-reload
    echo "ArmadaLive removed."
    exit 0
fi

mkdir -p "$share" "$(dirname "$unit")" "$(dirname "$desktop")"

# PySide6 normally comes with the OS image, but a system update once dropped it. Then ArmadaLive uses a private copy in its own folder.
need="import PySide6.QtQuick, PySide6.QtWebSockets, PySide6.QtDBus, PySide6.QtTest"
py=/usr/bin/python3
if ! "$py" -c "$need" 2>/dev/null; then
    py="$share/venv/bin/python"
    if ! "$py" -c "$need" 2>/dev/null; then
        echo "PySide6 is not installed on this system: fetching a private copy (several hundred MB, needs internet)..."
        rm -rf "$share/venv"
        /usr/bin/python3 -m venv "$share/venv"
        "$share/venv/bin/pip" install --quiet PySide6-Essentials PySide6-Addons pymupdf
        "$py" -c "$need" || { echo "PySide6 could not be installed" >&2; exit 1; }
    fi
fi
rm -rf "$share/armadalive"
cp -r "$here/armadalive" "$share/"
find "$share" -name __pycache__ -prune -exec rm -rf {} +
rm -rf "$share/scripts"
cp -r "$here/scripts" "$share/scripts"
install -m 755 "$here/scripts/esde-event.py" "$share/esde-event.py"
sed "s#^ExecStart=/usr/bin/python3#ExecStart=$py#" "$here/data/armadalive.service" >"$unit"
cp "$here/data/armadalive.desktop" "$desktop"
for e in $events; do
    mkdir -p "$HOME/ES-DE/scripts/$e"
    ln -sfn "$share/esde-event.py" "$HOME/ES-DE/scripts/$e/armadalive"
done
systemctl --user daemon-reload
systemctl --user enable armadalive 2>/dev/null
systemctl --user restart armadalive
echo "ArmadaLive installed. In ES-DE enable: Other Settings > Custom Event Scripts and Browsing Custom Event Scripts."
