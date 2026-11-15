"""A checklist of what ArmadaLive needs to see what is going on, with a hint for each thing that is missing."""
import os, re
from PySide6.QtCore import Property, QObject, Signal

from . import nowplaying
from .poller import Poller

EVENTS = ("startup", "quit", "system-select", "game-select", "game-start", "game-end")


def _checks():
    hooks = all(os.path.islink(f"{nowplaying.ES}/scripts/{e}/armadalive") for e in EVENTS)
    try:
        with open(nowplaying.ES + "/settings/es_settings.xml") as f:
            config = f.read()
    except OSError:
        config = ""
    events = all(re.search(rf'name="{name}" value="true"', config)
                 for name in ("CustomEventScripts", "CustomEventScriptsBrowsing"))
    return hooks, events, _has_marquee(), os.path.exists(f"/run/user/{os.getuid()}/gamescope-stats/stats.pipe")


def _has_marquee():
    try:
        with os.scandir(nowplaying.MEDIA) as systems:
            for system in systems:
                try:
                    with os.scandir(os.path.join(system.path, "marquees")) as images:
                        if any(not entry.name.startswith(".") for entry in images):
                            return True
                except OSError:
                    continue
    except OSError:
        pass
    return False


class Health(QObject):
    changed = Signal()

    def __init__(self, steamui):
        super().__init__()
        self._steamui, self._s = steamui, []
        self._poller = Poller(self, _checks, self._apply, 5000, idle_ms=30000)

    def set_active(self, active):
        self._poller.set_active(active)

    @Property("QVariant", notify=changed)
    def checks(self):
        return self._s

    def refresh(self):
        self._poller.refresh()

    def _apply(self, checks):
        hooks, events, media, gamescope = checks
        state = [
            dict(id="hooks", ok=hooks, hint="Run install.sh again: the ES-DE hooks are missing"),
            dict(id="events", ok=events,
                 hint="ES-DE: START > Other Settings > Custom Event Scripts and Browsing Custom Event Scripts"),
            dict(id="media", ok=media, hint="Scrape media in ES-DE (logos and backgrounds)"),
            dict(id="steam", ok=self._steamui.connected,   # the connection is the test: the marker file is only one way to switch debugging on
                 hint="Steam Big Picture selection needs Steam's remote debugging: turn on CEF Remote Debugging in Steam's developer settings, or install Decky Loader (it creates ~/.steam/steam/.cef-enable-remote-debugging), then restart Steam"),
            dict(id="gamescope", ok=gamescope, hint="gamescope's stats pipe is missing: FPS cannot be read"),
        ]
        if state != self._s:
            self._s = state
            self.changed.emit()
