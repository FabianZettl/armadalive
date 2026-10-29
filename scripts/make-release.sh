#!/bin/sh
# Build and publish a release: tests, archive, checksum, GitHub release. Needs the gh CLI, logged in.
#   scripts/make-release.sh 0.2.0 notes.md
# The in-app updater only installs a release that has both armadalive.tar.gz and armadalive.tar.gz.sha256.
set -eu
version=${1:?version, e.g. 0.2.0}
notes=${2:?file with the release notes}
cd "$(dirname "$0")/.."
grep -q "__version__ = \"$version\"" armadalive/__init__.py || { echo "armadalive/__init__.py does not say $version" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "commit your changes first" >&2; exit 1; }
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -t . || { echo "tests failed, nothing published" >&2; exit 1; }
tmp=$(mktemp -d)
git archive --format=tar.gz --prefix=armadalive/ -o "$tmp/armadalive.tar.gz" HEAD
(cd "$tmp" && sha256sum armadalive.tar.gz > armadalive.tar.gz.sha256)
git push origin HEAD
gh release create "v$version" "$tmp/armadalive.tar.gz" "$tmp/armadalive.tar.gz.sha256" \
    --title "ArmadaLive $version" --notes-file "$notes" --target "$(git rev-parse HEAD)"
