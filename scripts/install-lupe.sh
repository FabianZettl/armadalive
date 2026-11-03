#!/bin/sh
# The Lupe needs GStreamer's PipeWire plugin, which Armada's image does not ship (package pipewire-gstreamer). This takes
# libgstpipewire.so out of that package into the app's gst-plugins folder: no layered package, no reboot, nothing outside it.
set -eu
dir="$(cd "$(dirname "$0")/.." && pwd)/gst-plugins"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$dir"
echo "Downloading pipewire-gstreamer (the version of this system's pipewire if the repository has it) ..."
version=$(rpm -q --qf '%{VERSION}-%{RELEASE}' pipewire 2>/dev/null || true)
dnf5 download --destdir "$tmp" "pipewire-gstreamer-$version" >/dev/null 2>&1 || dnf5 download --destdir "$tmp" pipewire-gstreamer >/dev/null
rpm=$(ls "$tmp"/pipewire-gstreamer-*.rpm | head -1)
(cd "$tmp" && rpm2cpio "$rpm" | cpio -idm --quiet ./usr/lib64/gstreamer-1.0/libgstpipewire.so)
cp "$tmp/usr/lib64/gstreamer-1.0/libgstpipewire.so" "$dir/"
if GST_PLUGIN_PATH="$dir" gst-inspect-1.0 pipewiresrc >/dev/null 2>&1; then echo "Lupe plugin installed: $dir/libgstpipewire.so"; else echo "The plugin was copied but GStreamer does not load it; the Lupe will say what is missing." >&2; exit 1; fi
