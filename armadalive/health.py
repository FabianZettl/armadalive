"""A checklist of what ArmadaLive needs to see what is going on, with a hint for each thing that is missing."""
import glob, os, re
from PySide6.QtCore import Property, QObject, QTimer, Signal

from . import nowplaying, privileged

EVENTS = ("startup", "quit", "system-select", "game-select", "game-start", "game-end")
CEF_FLAG = os.path.expanduser("~/.steam/steam/.cef-enable-remote-debugging")


def _esde_setting(name):
    try:
        return re.search(rf'name="{name}" value="(\w+)"', open(nowplaying.ES + "/settings/es_settings.xml").read()).group(1) == "true"
    except (OSError, AttributeError):
        return False


class Health(QObject):
    changed = Signal()

    def __init__(self, steamui):
        super().__init__()
        self._steamui, self._s = steamui, []
        timer = QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(5000)
        self.refresh()

    @Property("QVariant", notify=changed)
    def checks(self):
        return self._s

    def refresh(self):
        hooks = all(os.path.islink(f"{nowplaying.ES}/scripts/{e}/armadalive") for e in EVENTS)
        self._s = [
            dict(id="hooks", ok=hooks, hint="Run install.sh again: the ES-DE hooks are missing"),
            dict(id="events", ok=_esde_setting("CustomEventScripts") and _esde_setting("CustomEventScriptsBrowsing"),
                 hint="ES-DE: START > Other Settings > Custom Event Scripts and Browsing Custom Event Scripts"),
            dict(id="media", ok=bool(glob.glob(nowplaying.MEDIA + "/*/marquees/*")), hint="Scrape media in ES-DE (logos and backgrounds)"),
            dict(id="steam", ok=os.path.exists(CEF_FLAG) and self._steamui.connected,
                 hint="Steam Big Picture selection needs ~/.steam/steam/.cef-enable-remote-debugging (Decky Loader) and a Steam restart"),
            dict(id="gamescope", ok=os.path.exists(f"/run/user/{os.getuid()}/gamescope-stats/stats.pipe"), hint="gamescope's stats pipe is missing: FPS cannot be read"),
        ]
        self.changed.emit()
