#!/bin/sh
# Install ArmadaLive for the current user (no root needed). Use --uninstall to remove it.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
share="$HOME/.local/share/armadalive"
unit="$HOME/.config/systemd/user/armadalive.service"
desktop="$HOME/.local/share/applications/armadalive.desktop"
events="startup quit system-select game-select game-start game-end"
cache="$HOME/.cache/armadalive"
mkdir -p "$cache"
exec 9>"$cache/install.lock"
flock -n 9 || { echo "Another ArmadaLive installation is in progress." >&2; exit 1; }

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

# Each replacement is staged beside its destination so moving it into place is
# a rename even if parts of the user's home are on separate filesystems.
stage=$(mktemp -d "$share/.install.XXXXXX")
prepared=""
service_touched=0
restart_attempted=0
enable_attempted=0
was_enabled=0
had_app=0
[ ! -e "$share/armadalive" ] || had_app=1

destination() {
    case "$1" in
        app)     printf '%s\n' "$share/armadalive" ;;
        scripts) printf '%s\n' "$share/scripts" ;;
        event)   printf '%s\n' "$share/esde-event.py" ;;
        unit)    printf '%s\n' "$unit" ;;
        desktop) printf '%s\n' "$desktop" ;;
        *)       printf '%s\n' "$HOME/ES-DE/scripts/$1/armadalive" ;;
    esac
}

exists() { [ -e "$1" ] || [ -L "$1" ]; }

prepare() {
    target=$(destination "$1")
    mkdir -p "$(dirname "$target")"
    work=$(mktemp -d "$(dirname "$target")/.armadalive-install.XXXXXX")
    if ! printf '%s\n' "$work" > "$stage/$1"; then
        rm -rf -- "$work" || echo "Could not remove staging directory $work" >&2
        return 1
    fi
    prepared="$1 $prepared"
}

replace() {
    target=$(destination "$1")
    work=$(cat "$stage/$1")
    if exists "$target"; then
        mv -T -- "$target" "$work/old"
    fi
    : > "$work/switching"
    mv -T -- "$work/new" "$target"
}

rollback() {
    restored=1
    for item in $prepared; do
        target=$(destination "$item")
        if ! work=$(cat "$stage/$item"); then
            echo "Could not locate the backup for $target" >&2
            restored=0
            continue
        fi
        # Moving the failed replacement aside also works for read-only trees.
        if [ -f "$work/switching" ] && ! exists "$work/new" && exists "$target"; then
            if ! mv -T -- "$target" "$work/failed"; then
                echo "Could not move the replacement at $target; staging kept at $work" >&2
                restored=0
                continue
            fi
        fi
        if exists "$work/old" && ! mv -T -- "$work/old" "$target"; then
            echo "Could not restore $target; previous copy is at $work/old" >&2
            restored=0
        fi
    done
}

clean_staging() {
    for item in $prepared; do
        work=$(cat "$stage/$item") || continue
        if [ "$rc" -ne 0 ] && exists "$work/old"; then
            continue
        fi
        rm -rf -- "$work" || echo "Could not remove staging directory $work" >&2
    done
    rm -rf -- "$stage" || echo "Could not remove staging directory $stage" >&2
}

finish() {
    rc=$1
    trap - EXIT
    trap '' HUP INT TERM
    if [ "$rc" -ne 0 ]; then
        if [ "$restart_attempted" = 1 ]; then
            systemctl --user stop armadalive || echo "Could not stop the failed installation." >&2
        fi
        rollback
        if [ "$service_touched" = 1 ] && [ "$restored" = 1 ]; then
            if [ "$enable_attempted" = 1 ] && [ "$was_enabled" = 0 ]; then
                systemctl --user disable armadalive || echo "Could not restore service enablement." >&2
            fi
            systemctl --user daemon-reload || echo "Could not reload the restored service definition." >&2
            if [ "$restart_attempted" = 1 ] && [ "$had_app" = 1 ]; then
                systemctl --user restart armadalive || echo "Could not restart the previous installation." >&2
            fi
        fi
        echo "ArmadaLive installation failed." >&2
    fi
    clean_staging
    exit "$rc"
}

trap 'finish "$?"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

targets="app scripts event unit desktop $events"
for item in $targets; do prepare "$item"; done
app_stage=$(cat "$stage/app")/new
scripts_stage=$(cat "$stage/scripts")/new
cp -r "$here/armadalive" "$app_stage"
cp -r "$here/scripts" "$scripts_stage"
install -m 755 "$here/scripts/esde-event.py" "$(cat "$stage/event")/new"
cp "$here/data/armadalive.service" "$(cat "$stage/unit")/new"
cp "$here/data/armadalive.desktop" "$(cat "$stage/desktop")/new"
for e in $events; do
    ln -s "$share/esde-event.py" "$(cat "$stage/$e")/new"
done

test -f "$app_stage/__main__.py"
test -f "$app_stage/app.py"
test -f "$app_stage/qml/Main.qml"
test -x "$scripts_stage/run.sh"
sh -n "$scripts_stage/run.sh"
"$py" -m compileall -q -f "$app_stage" "$scripts_stage"
find "$app_stage" "$scripts_stage" -name __pycache__ -prune -exec rm -rf {} +

for item in $targets; do replace "$item"; done
service_touched=1
systemctl --user daemon-reload
systemctl --user is-enabled --quiet armadalive && was_enabled=1
restart_attempted=1
systemctl --user restart armadalive
systemctl --user is-active --quiet armadalive
enable_attempted=1
systemctl --user enable armadalive 2>/dev/null
echo "ArmadaLive installed. In ES-DE enable: Other Settings > Custom Event Scripts and Browsing Custom Event Scripts."
