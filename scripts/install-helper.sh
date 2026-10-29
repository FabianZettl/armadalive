#!/bin/sh
# Install (or --remove) the root helper that lets ArmadaLive change power profiles, fan curves and RGB.
# Run once with sudo. The helper validates every value; sudoers allows exactly this one program, without a password.
set -eu
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
user=${SUDO_USER:?run this through sudo, not as a root login}
here=$(cd "$(dirname "$0")" && pwd)
helper=/etc/armadalive/armadalive-helper
rule=/etc/sudoers.d/armadalive

if [ "${1:-}" = "--remove" ]; then
    rm -rf /etc/armadalive "$rule"
    echo "helper removed"
    exit 0
fi

install -D -m 755 -o root -g root "$here/armadalive-helper" "$helper"
printf '%s ALL=(root) NOPASSWD: %s\n' "$user" "$helper" >"$rule.new"
chmod 440 "$rule.new"
visudo -cf "$rule.new" >/dev/null || { rm -f "$rule.new"; echo "sudoers check failed, nothing installed" >&2; exit 1; }
mv "$rule.new" "$rule"
echo "helper installed for $user"
