"""The app grid on the idle screen: installed apps from their .desktop files (launched on the bottom screen) and Steam games and
shortcuts (launched through Steam on the main screen) and ES-DE games (through a Steam shortcut they get on the first tap), as many as you add; the grid scrolls sideways."""
import configparser, json, os, re, subprocess
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from . import esdelib, steamlib, steamshortcuts, steamui

CONFIG = os.path.expanduser("~/.config/armadalive/apps.json")
APP_DIRS = [os.path.expanduser(p) for p in (
    "~/.local/share/applications", "/usr/share/applications",
    "~/.local/share/flatpak/exports/share/applications", "/var/lib/flatpak/exports/share/applications")]
ICON_ROOTS = [os.path.expanduser(p) for p in (
    "~/.local/share/icons", "~/.local/share/flatpak/exports/share/icons", "/var/lib/flatpak/exports/share/icons",
    "/usr/share/icons/hicolor", "/usr/share/icons/breeze", "/usr/share/icons/Adwaita", "/usr/share/pixmaps")]
DEFAULTS = ["org.mozilla.firefox", "org.kde.dolphin", "org.kde.konsole", "systemsettings", "com.moonlight_stream.Moonlight",
            "org.localsend.localsend_app", "it.mijorus.gearlever", "com.ranfdev.DistroShelf"]
_icons = {}


def _icon_index():
    if _icons:
        return _icons
    best = {}
    for root in ICON_ROOTS:
        for path, _, files in os.walk(root):
            if "apps" not in path.split(os.sep) and not root.endswith("pixmaps"):
                continue
            for f in files:
                name, ext = os.path.splitext(f)
                if ext not in (".svg", ".png"):
                    continue
                size = 1000 if ext == ".svg" or "scalable" in path else int((re.findall(r"(\d+)", path) or ["0"])[-1])
                if size >= best.get(name, (-1,))[0]:
                    best[name] = (size, os.path.join(path, f))
    _icons.update({k: v[1] for k, v in best.items()})
    return _icons


def _icon(name):
    if name and os.path.isabs(name) and os.path.exists(name):
        return QUrl.fromLocalFile(name).toString()
    path = _icon_index().get(name or "", "")
    return QUrl.fromLocalFile(path).toString() if path else ""


def _catalog():
    apps = {}
    for d in APP_DIRS:
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not f.endswith(".desktop") or f[:-8] in apps:
                continue
            p = configparser.ConfigParser(interpolation=None, strict=False)
            p.optionxform = str
            try:
                p.read(os.path.join(d, f), encoding="utf-8")
                e = p["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("Type") != "Application" or e.get("NoDisplay") == "true" or e.get("Hidden") == "true" or e.get("Terminal") == "true":
                continue
            apps[f[:-8]] = dict(id=f[:-8], name=e.get("Name", f[:-8]), iconName=e.get("Icon", ""))
    return apps


class Apps(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._apps = _catalog()
        self._scan()
        self._slots = self._load()
        self._icon_cache = {}

    def _scan(self):
        self._steam = {g["id"]: g for g in steamlib.games()}
        self._systems = esdelib.systems()
        self._esde = {}   # id -> game, with its system
        for system, found in esdelib.games().items():
            for g in found:
                self._esde[g["id"]] = dict(g, system=system)

    def _known(self, app_id):
        return app_id in self._apps or app_id in self._steam or app_id in self._esde

    def _load(self):
        try:
            slots = json.load(open(CONFIG))["slots"]
        except (OSError, ValueError, KeyError):
            slots = [a for a in DEFAULTS if a in self._apps]
        return [s for s in slots if self._known(s)]   # a removed app or game just leaves the grid

    def _save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump({"slots": self._slots}, f)

    def _entry(self, app_id, thumb=False):
        if app_id in self._esde:
            g = self._esde[app_id]   # the picker lists plain files; only a tile gets the cut, rounded cover
            return dict(id=app_id, name=g["name"], icon=(QUrl.fromLocalFile(g["cover"]).toString() if thumb else steamlib._url(g["cover"])) if g["cover"] else "",
                        cover=True, group="esde:" + g["system"])
        if app_id in self._steam:
            return dict(self._steam[app_id], cover=True, group="steam")
        a = self._apps[app_id]
        if app_id not in self._icon_cache:
            self._icon_cache[app_id] = _icon(a["iconName"])
        return dict(id=app_id, name=a["name"], icon=self._icon_cache[app_id], cover=False, group="apps")

    @Property("QVariant", notify=changed)
    def slots(self):
        return [self._entry(s) for s in self._slots] + [{}]   # the last, empty tile adds one

    @Slot(result="QVariant")
    def catalog(self):
        self._scan()   # new installs and new ROMs show up without a restart
        ids = list(self._apps) + list(self._steam) + list(self._esde)
        return [self._entry(a, thumb=True) for a in sorted(ids, key=lambda a: self._entry(a, thumb=True)["name"].lower())]

    @Slot(result="QVariant")
    def groups(self):
        """The picker's tabs: desktop apps, Steam, then every ES-DE system that has games."""
        out = [dict(id="apps", label=""), dict(id="steam", label="")]
        names = {g["system"] for g in self._esde.values()}
        return out + [dict(id="esde:" + n, label=self._systems[n]["fullname"]) for n in sorted(names, key=lambda n: self._systems[n]["fullname"].lower())]

    @Slot(int, str)
    def assign(self, slot, app_id):
        if app_id == "":
            if 0 <= slot < len(self._slots):
                del self._slots[slot]
        elif self._known(app_id) and 0 <= slot <= len(self._slots):
            if slot == len(self._slots):
                self._slots.append(app_id)
            else:
                self._slots[slot] = app_id
        else:
            return
        self._save()
        self.changed.emit()

    @Slot(int)
    def launch(self, slot):
        app_id = self._slots[slot] if 0 <= slot < len(self._slots) else ""
        if app_id in self._steam:
            steamui.eval_js(f'SteamClient.Apps.RunGame("{app_id[6:]}", "", -1, 100)', lambda _: None)
            return
        if app_id in self._esde:
            g = self._esde[app_id]
            words = esdelib.command(g["system"], g["rom"])
            if words:
                steamshortcuts.run_rom(g["name"], g["system"], g["rom"], words)
            return
        if app_id not in self._apps:  # only ids from the catalog ever reach gtk-launch
            return
        # run as a plain app on the bottom Plasma session; our own Qt settings must not leak into it
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "QT_QUICK_CONTROLS_STYLE")}
        subprocess.Popen(["gtk-launch", app_id], env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
