"""The app grid on the idle screen: installed apps from their .desktop files (launched on the bottom screen) and Steam games and
shortcuts (launched through Steam on the main screen) and ES-DE games (through a Steam shortcut they get on the first tap), as many as you add; the grid scrolls sideways."""
import configparser, json, os, random, re, subprocess
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from . import esdelib, steamlib, steamshortcuts, steamui
from .nowplaying import ES

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


def system_art(system, es=None):
    """The picture of one system from the ES-DE theme in use (the theme's _inc/systems/artwork), or "" if the theme has none."""
    es = es or ES
    try:
        theme = re.search(r'name="Theme" value="([^"]+)"', open(es + "/settings/es_settings.xml").read()).group(1)
    except (OSError, AttributeError):
        return ""
    for ext in ("webp", "png", "jpg"):
        path = f"{es}/themes/{theme}/_inc/systems/artwork/{system}.{ext}"
        if os.path.exists(path):
            return QUrl.fromLocalFile(path).toString()
    return ""


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


SMART = ("smart:recent", "smart:favorites", "smart:steam")          # smart folders without a parameter; "smart:esde:<system>" is every game of one ES-DE system
RANDOM = "random:game"                           # a tile that starts a random game
PREVIEW = 4                                      # covers shown on a folder tile


class Apps(QObject):
    changed = Signal()

    def __init__(self, history=None):
        super().__init__()
        self._history = history
        self._apps = _catalog()
        self._folders, self._next = {}, 1
        self._scan()
        self._slots = self._load()
        self._icon_cache = {}

    def _scan(self):
        self._steam = {g["id"]: g for g in steamlib.games()}
        self._systems = esdelib.systems()
        self._esde, self._by_path = {}, {}   # id -> game, with its system; ROM path -> id
        for system, found in esdelib.games().items():
            for g in found:
                self._esde[g["id"]] = dict(g, system=system)
                self._by_path[g["rom"]] = g["id"]

    def _plain(self, app_id):
        return app_id in self._apps or app_id in self._steam or app_id in self._esde

    def _smart(self, app_id):
        return app_id in SMART or (app_id.startswith("smart:esde:") and any(g["system"] == app_id[11:] for g in self._esde.values()))

    def _known(self, app_id):
        return self._plain(app_id) or app_id in {"folder:" + f for f in self._folders} or self._smart(app_id) or app_id == RANDOM

    def _load(self):
        try:
            saved = json.load(open(CONFIG))
            slots = saved["slots"]
            self._folders = {str(k): dict(name=str(v.get("name", "")), items=[i for i in v.get("items", []) if isinstance(i, str)]) for k, v in saved.get("folders", {}).items()}
            self._next = int(saved.get("next", len(self._folders) + 1))
        except (OSError, ValueError, KeyError, AttributeError):
            slots = [a for a in DEFAULTS if a in self._apps]
        return [s for s in slots if isinstance(s, str) and self._known(s)]   # a removed app or game just leaves the grid

    def _save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump({"slots": self._slots, "folders": self._folders, "next": self._next}, f)

    # --- what a tile or a list row shows ---
    def _resolve(self, key, rec):
        """The catalog id of a game from the play history, None when it cannot be started from here any more."""
        if rec.get("path") in self._by_path:
            return self._by_path[rec["path"]]
        if key.startswith("steam/") and key[6:].isdigit():
            n = int(key[6:])
            for cand in (f"steam:{n}", f"steam:{(n << 32) | 0x02000000}"):
                if cand in self._steam:
                    return cand
        return None

    def _items_of(self, app_id):
        """The catalog ids inside a folder (manual or smart)."""
        if app_id.startswith("folder:"):
            return [i for i in self._folders.get(app_id[7:], {}).get("items", []) if self._plain(i)]
        if app_id == "smart:recent":
            found = [self._resolve(k, r) for k, r in (self._history.recent(40) if self._history else [])]
            return list(dict.fromkeys(i for i in found if i))[:24]
        if app_id == "smart:favorites":
            found = [self._resolve(k, r) for k, r in (self._history.favorites() if self._history else [])]
            return sorted(set(i for i in found if i), key=lambda i: (self._esde.get(i) or self._steam.get(i))["name"].lower())
        if app_id == "smart:steam":
            return sorted(self._steam, key=lambda i: self._steam[i]["name"].lower())
        if app_id.startswith("smart:esde:"):
            return sorted((i for i, g in self._esde.items() if g["system"] == app_id[11:]), key=lambda i: self._esde[i]["name"].lower())
        return []

    def _entry(self, app_id, thumb=False):
        if app_id == RANDOM:
            return dict(id=app_id, name="Random game", icon="", cover=False, glyph="🎲", group="folders")
        if app_id.startswith(("folder:", "smart:")):
            names = {"smart:recent": "Recently played", "smart:favorites": "Favorites", "smart:steam": "Steam"}
            if app_id.startswith("folder:"):
                name = self._folders.get(app_id[7:], {}).get("name") or "Folder " + app_id[7:]
            elif app_id.startswith("smart:esde:"):
                name = (self._systems.get(app_id[11:]) or {}).get("fullname", app_id[11:])
            else:
                name = names[app_id]
            items = self._items_of(app_id)
            art = system_art(app_id[11:]) if app_id.startswith("smart:esde:") else ""
            return dict(id=app_id, name=name, icon="", art=art, cover=False, folder=True, manual=app_id.startswith("folder:"), count=len(items), group="folders",
                        preview=[self._entry(i)["icon"] for i in items[:PREVIEW]])
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
        out = [dict(id="apps", label=""), dict(id="steam", label=""), dict(id="folders", label="")]
        names = {g["system"] for g in self._esde.values()}
        return out + [dict(id="esde:" + n, label=self._systems[n]["fullname"]) for n in sorted(names, key=lambda n: self._systems[n]["fullname"].lower())]

    @Slot(result="QVariant")
    def folderChoices(self):
        """What the picker's Folders tab offers: a new folder, the folders there are, the smart ones and the random tile."""
        names = {g["system"] for g in self._esde.values()}
        ids = ["folder:new"] + ["folder:" + f for f in self._folders] + list(SMART) + ["smart:esde:" + n for n in sorted(names, key=lambda n: self._systems[n]["fullname"].lower())] + [RANDOM]
        out = []
        for i in ids:
            e = dict(id=i, name="New folder", icon="", cover=False, glyph="+", group="folders") if i == "folder:new" else self._entry(i)
            out.append(e)
        return out

    @Slot(str, result="QVariant")
    def folderItems(self, folder_id):
        """The entries inside a folder, for its view."""
        return [self._entry(i, thumb=True) for i in self._items_of(folder_id)[:600]]

    # --- changing the grid ---
    @Slot(int, str)
    def assign(self, slot, app_id):
        if app_id == "folder:new":
            app_id = self._create_folder()
        if app_id == "":
            if 0 <= slot < len(self._slots):
                gone = self._slots.pop(slot)
                if gone.startswith("folder:") and gone not in self._slots:
                    self._folders.pop(gone[7:], None)     # a folder that is nowhere any more is forgotten
        elif self._known(app_id) and 0 <= slot <= len(self._slots):
            if slot == len(self._slots):
                self._slots.append(app_id)
            else:
                self._slots[slot] = app_id
        else:
            return
        self._save()
        self.changed.emit()

    def _create_folder(self):
        fid = str(self._next)
        self._next += 1
        self._folders[fid] = dict(name="", items=[])
        return "folder:" + fid

    @Slot(str, str)
    def addToFolder(self, folder_id, app_id):
        f = self._folders.get(folder_id[7:]) if folder_id.startswith("folder:") else None
        if f is not None and self._plain(app_id) and app_id not in f["items"]:
            f["items"].append(app_id)
            self._save()
            self.changed.emit()

    @Slot(str, str)
    def removeFromFolder(self, folder_id, app_id):
        f = self._folders.get(folder_id[7:]) if folder_id.startswith("folder:") else None
        if f is not None and app_id in f["items"]:
            f["items"].remove(app_id)
            self._save()
            self.changed.emit()

    @Slot(str, str)
    def renameFolder(self, folder_id, name):
        f = self._folders.get(folder_id[7:]) if folder_id.startswith("folder:") else None
        if f is not None:
            f["name"] = name.strip()[:40]
            self._save()
            self.changed.emit()

    # --- starting things ---
    @Slot(int)
    def launch(self, slot):
        app_id = self._slots[slot] if 0 <= slot < len(self._slots) else ""
        self.launchId(app_id)

    @Slot(str)
    def randomIn(self, folder_id):
        """Starts a random game out of one folder (a system, the favorites, ...)."""
        items = self._items_of(folder_id)
        if items:
            self.launchId(random.choice(items))

    @Slot(str)
    def launchId(self, app_id):
        if app_id == RANDOM:
            pool = list(self._esde) + [i for i in self._steam]
            if pool:
                self.launchId(random.choice(pool))
            return
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
