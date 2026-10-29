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
rm -rf "$share/armadalive"
cp -r "$here/armadalive" "$share/"
find "$share" -name __pycache__ -prune -exec rm -rf {} +
rm -rf "$share/scripts"
cp -r "$here/scripts" "$share/scripts"
install -m 755 "$here/scripts/esde-event.py" "$share/esde-event.py"
cp "$here/data/armadalive.service" "$unit"
cp "$here/data/armadalive.desktop" "$desktop"
for e in $events; do
    mkdir -p "$HOME/ES-DE/scripts/$e"
    ln -sfn "$share/esde-event.py" "$HOME/ES-DE/scripts/$e/armadalive"
done
systemctl --user daemon-reload
systemctl --user enable armadalive 2>/dev/null
systemctl --user restart armadalive
echo "ArmadaLive installed. In ES-DE enable: Other Settings > Custom Event Scripts and Browsing Custom Event Scripts."
