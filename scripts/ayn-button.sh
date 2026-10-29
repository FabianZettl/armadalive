#!/bin/sh
# Routes the Thor's AYN button to ArmadaLive. Run once with sudo.
#
# InputPlumber maps the button (KEY_F24) to a gamepad button the emulated controller does not have, so by default it
# does nothing. This installs a copy of InputPlumber's AYN capability map that sends it to InputPlumber's D-Bus device
# as ui_quick2 instead; ArmadaLive listens for that event and brings its window to the front.
#
# Adapted from ThorHUD's ayn-button.sh (MIT, Copyright (c) 2026 Mike Klein, https://github.com/mtklein/thorhud): the same
# override serves both apps, so running either script once is enough. See CREDITS.md for the license text.
#
#   sudo ./ayn-button.sh           install the override
#   sudo ./ayn-button.sh --remove  go back to InputPlumber's own map
#
# The override lives in /etc, which belongs to the current OS deployment: after a rollback, run it again.
set -eu
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
src=/usr/share/inputplumber/capability_maps/ayn_type2.yaml
dst=/etc/inputplumber/capability_maps.d/ayn_type2.yaml

if [ "${1:-}" = --remove ]; then
    rm -f "$dst"
else
    grep -q 'button: QuickAccess2' "$src" || { echo "unexpected $src; not changing anything" >&2; exit 1; }
    mkdir -p "$(dirname "$dst")"
    {
        echo "# Installed by ArmadaLive's ayn-button.sh: the AYN key goes to InputPlumber's D-Bus device (ui_quick2)."
        sed '/name: AYN Key/,/button: QuickAccess2/{s/^      gamepad:$/      dbus: ui_quick2/;/button: QuickAccess2/d}' "$src"
    } >"$dst.new"
    mv "$dst.new" "$dst"
fi
systemctl restart inputplumber
echo "done"
