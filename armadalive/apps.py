"""The nine-app grid on the idle screen: installed apps from their .desktop files, launched on the bottom screen."""
import configparser, json, os, re, subprocess
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

CONFIG = os.path.expanduser("~/.config/armadalive/apps.json")
APP_DIRS = [os.path.expanduser(p) for p in (
    "~/.local/share/applications", "/usr/share/applications",
    "~/.local/share/flatpak/exports/share/applications", "/var/lib/flatpak/exports/share/applications")]
ICON_ROOTS = [os.path.expanduser(p) for p in (
    "~/.local/share/icons", "~/.local/share/flatpak/exports/share/icons", "/var/lib/flatpak/exports/share/icons",
    "/usr/share/icons/hicolor", "/usr/share/icons/breeze", "/usr/share/icons/Adwaita", "/usr/share/pixmaps")]
DEFAULTS = ["org.mozilla.firefox", "org.kde.dolphin", "org.kde.konsole", "systemsettings", "com.moonlight_stream.Moonlight",
            "org.localsend.localsend_app", "it.mijorus.gearlever", "com.ranfdev.DistroShelf"]
SLOTS = 9
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
        self._slots = self._load()
        self._icon_cache = {}

    def _load(self):
        try:
            slots = json.load(open(CONFIG))["slots"]
        except (OSError, ValueError, KeyError):
            slots = [a for a in DEFAULTS if a in self._apps]
        return ([s if s in self._apps else "" for s in slots] + [""] * SLOTS)[:SLOTS]

    def _save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump({"slots": self._slots}, f)

    def _entry(self, app_id):
        if not app_id:
            return {}
        a = self._apps[app_id]
        if app_id not in self._icon_cache:
            self._icon_cache[app_id] = _icon(a["iconName"])
        return dict(id=app_id, name=a["name"], icon=self._icon_cache[app_id])

    @Property("QVariant", notify=changed)
    def slots(self):
        return [self._entry(s) for s in self._slots]

    @Slot(result="QVariant")
    def catalog(self):
        return [dict(self._entry(a), id=a) for a in sorted(self._apps, key=lambda a: self._apps[a]["name"].lower())]

    @Slot(int, str)
    def assign(self, slot, app_id):
        if 0 <= slot < SLOTS and (app_id in self._apps or app_id == ""):
            self._slots[slot] = app_id
            self._save()
            self.changed.emit()

    @Slot(int)
    def launch(self, slot):
        app_id = self._slots[slot] if 0 <= slot < SLOTS else ""
        if app_id not in self._apps:  # only ids from the catalog ever reach gtk-launch
            return
        # run as a plain app on the bottom Plasma session; our own Qt settings must not leak into it
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "QT_QUICK_CONTROLS_STYLE")}
        subprocess.Popen(["gtk-launch", app_id], env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
