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

mkdir -p "$share"
stage=$(mktemp -d "$share/.install.XXXXXX")
prepared=""
reload_attempted=0
restart_attempted=0
enable_attempted=0

destination() {
    case "$1" in
        app)     printf '%s\n' "$share/armadalive" ;;
        scripts) printf '%s\n' "$share/scripts" ;;
        event)   printf '%s\n' "$share/esde-event.py" ;;
        unit)    printf '%s\n' "$unit" ;;
        desktop) printf '%s\n' "$desktop" ;;
        venv)    printf '%s\n' "$share/venv" ;;
        *)       printf '%s\n' "$HOME/ES-DE/scripts/$1/armadalive" ;;
    esac
}

exists() { [ -e "$1" ] || [ -L "$1" ]; }

# Keep staged files and backups on the same filesystem as their destinations.
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

begin_replacement() {
    target=$(destination "$1")
    work=$(cat "$stage/$1")
    if exists "$target"; then
        mv -T -- "$target" "$work/old"
    fi
    : > "$work/switching"
}

replace() {
    begin_replacement "$1"
    mv -T -- "$work/new" "$target"
}

restore_files() {
    files_restored=1
    for item in $prepared; do
        target=$(destination "$item")
        if ! work=$(cat "$stage/$item"); then
            echo "Could not locate the staging directory for $target" >&2
            files_restored=0
            continue
        fi
        if [ -f "$work/switching" ] && ! exists "$work/new" && exists "$target"; then
            if ! mv -T -- "$target" "$work/failed"; then
                echo "Could not move the replacement at $target; staging kept at $work" >&2
                files_restored=0
                continue
            fi
        fi
        if exists "$work/old" && ! mv -T -- "$work/old" "$target"; then
            echo "Could not restore $target; previous copy is at $work/old" >&2
            files_restored=0
        fi
    done
}

clean_staging() {
    for item in $prepared; do
        work=$(cat "$stage/$item") || continue
        rm -rf -- "$work" || echo "Could not remove staging directory $work" >&2
    done
    rm -rf -- "$stage" || echo "Could not remove staging directory $stage" >&2
}

restore_service() {
    if [ "$enable_attempted" = 1 ] && [ "$was_enabled" = enabled-runtime ]; then
        systemctl --user enable --runtime --no-reload armadalive ||
            service_error "Could not restore runtime service enablement."
    fi
    systemctl --user daemon-reload ||
        { service_error "Could not reload the restored service definition."; return; }
    if [ "$restart_attempted" = 1 ] && [ "$was_active" = 1 ]; then
        systemctl --user restart armadalive ||
            service_error "Could not restart the previous installation."
    fi
}

service_error() {
    echo "$1" >&2
    service_restored=0
}

finish() {
    rc=$1
    trap - EXIT
    trap '' HUP INT TERM
    if [ "$rc" -ne 0 ]; then
        service_restored=1
        if [ "$restart_attempted" = 1 ]; then
            systemctl --user stop armadalive ||
                service_error "Could not stop the failed installation."
        fi
        # Undo a partial enable while the replacement unit is still present.
        if [ "$enable_attempted" = 1 ]; then
            systemctl --user disable --no-reload armadalive ||
                service_error "Could not remove the replacement service enablement."
        fi
        restore_files
        if [ "$reload_attempted" = 1 ] && [ "$files_restored" = 1 ]; then
            restore_service
        fi
        echo "ArmadaLive installation failed." >&2
        if [ "$files_restored" = 0 ] || [ "$service_restored" = 0 ]; then
            echo "Rollback incomplete. Staging paths are listed in $stage" >&2
            exit "$rc"
        fi
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
event_stage=$(cat "$stage/event")/new
unit_stage=$(cat "$stage/unit")/new
desktop_stage=$(cat "$stage/desktop")/new
cp -r "$here/armadalive" "$app_stage"
cp -r "$here/scripts" "$scripts_stage"
install -m 755 "$here/scripts/esde-event.py" "$event_stage"
cp "$here/data/armadalive.service" "$unit_stage"
cp "$here/data/armadalive.desktop" "$desktop_stage"
for e in $events; do
    ln -s "$share/esde-event.py" "$(cat "$stage/$e")/new"
done

# Prefer the system PySide6. Use the private environment when the OS lacks it.
need="import PySide6.QtQuick, PySide6.QtWebSockets, PySide6.QtDBus, PySide6.QtTest"
py=/usr/bin/python3
provision_private=0
if ! "$py" -c "$need" 2>/dev/null; then
    if "$share/venv/bin/python" -c "$need" 2>/dev/null; then
        py="$share/venv/bin/python"
    else
        provision_private=1
    fi
fi

for file in "$app_stage/__main__.py" "$app_stage/app.py" "$app_stage/qml/Main.qml" \
            "$scripts_stage/run.sh" "$event_stage" "$unit_stage" "$desktop_stage"; do
    if ! [ -f "$file" ] || ! [ -s "$file" ]; then
        echo "ArmadaLive staged package has a missing or empty file: $file" >&2
        exit 1
    fi
done
test -x "$scripts_stage/run.sh"
sh -n "$scripts_stage/run.sh"
"$py" -m compileall -q -f "$app_stage" "$scripts_stage"
find "$app_stage" "$scripts_stage" -name __pycache__ -prune -exec rm -rf {} +

# Read the previous service state while its definition is still installed.
was_enabled=$(systemctl --user is-enabled armadalive 2>/dev/null) || true
case "$was_enabled" in
    enabled|enabled-runtime|disabled|not-found) ;;
    "") if exists "$unit"; then echo "Could not determine ArmadaLive service enablement." >&2; exit 1; fi ;;
    *) echo "Cannot replace ArmadaLive service with enablement state: $was_enabled" >&2; exit 1 ;;
esac
if systemctl --user is-active --quiet armadalive; then
    was_active=1
else
    case "$?" in
        3|4) was_active=0 ;;
        *) exit 1 ;;
    esac
fi

if [ "$provision_private" = 1 ]; then
    echo "PySide6 is not installed on this system: fetching a private copy (several hundred MB, needs internet)..."
    # A virtual environment embeds its path in entry points. Back up the old
    # environment, then build the replacement at its final path.
    prepare venv
    begin_replacement venv
    /usr/bin/python3 -m venv "$target"
    "$target/bin/pip" install --quiet PySide6-Essentials PySide6-Addons pymupdf
    "$target/bin/python" -c "$need" || { echo "PySide6 could not be installed" >&2; exit 1; }
fi

for item in $targets; do replace "$item"; done
reload_attempted=1
systemctl --user daemon-reload
restart_attempted=1
systemctl --user restart armadalive
systemctl --user is-active --quiet armadalive
if [ "$was_enabled" != enabled ]; then
    enable_attempted=1
    systemctl --user enable armadalive
fi
echo "ArmadaLive installed. In ES-DE enable: Other Settings > Custom Event Scripts and Browsing Custom Event Scripts."
