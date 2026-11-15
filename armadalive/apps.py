"""The app grid on the idle screen: installed apps from their .desktop files (launched on the bottom screen) and Steam games and
shortcuts (launched through Steam on the main screen) and ES-DE games (through a Steam shortcut they get on the first tap), as many as you add; the grid scrolls sideways."""
import configparser, json, logging, os, random, re, subprocess, threading, time
from PySide6.QtCore import Property, QCoreApplication, QObject, Qt, QUrl, Signal, Slot

from . import esdelib, steamlib, steamshortcuts
from .nowplaying import ES
from .persistence import write_json as _write_layout

CONFIG = os.path.expanduser("~/.config/armadalive/apps.json")
APP_DIRS = [os.path.expanduser(p) for p in (
    "~/.local/share/applications", "/usr/share/applications",
    "~/.local/share/flatpak/exports/share/applications", "/var/lib/flatpak/exports/share/applications")]
ICON_ROOTS = [os.path.expanduser(p) for p in (
    "~/.local/share/icons", "~/.local/share/flatpak/exports/share/icons", "/var/lib/flatpak/exports/share/icons",
    "/usr/share/icons/hicolor", "/usr/share/icons/breeze", "/usr/share/icons/Adwaita", "/usr/share/pixmaps")]
DEFAULTS = ["org.mozilla.firefox", "org.kde.dolphin", "org.kde.konsole", "systemsettings", "com.moonlight_stream.Moonlight",
            "org.localsend.localsend_app", "it.mijorus.gearlever", "com.ranfdev.DistroShelf"]
log = logging.getLogger(__name__)


def _icon_index():
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
    return {name: path for name, (_, path) in best.items()}


def _system_art_index(es):
    try:
        with open(os.path.join(es, "settings", "es_settings.xml")) as settings:
            theme = re.search(r'name="Theme" value="([^"]+)"', settings.read()).group(1)
        directory = os.path.join(es, "themes", theme, "_inc", "systems", "artwork")
        files = os.listdir(directory)
    except (OSError, AttributeError):
        return {}
    preferred = {".webp": 0, ".png": 1, ".jpg": 2}
    artwork = {}
    for filename in files:
        system, ext = os.path.splitext(filename)
        if ext in preferred and (system not in artwork or preferred[ext] < artwork[system][0]):
            artwork[system] = (preferred[ext], QUrl.fromLocalFile(os.path.join(directory, filename)).toString())
    return {system: url for system, (_, url) in artwork.items()}


def system_art(system, es=None):
    """The picture of one system from the ES-DE theme in use, or an empty string."""
    return _system_art_index(es or ES).get(system, "")


def _icon(name, index):
    if name and os.path.isabs(name) and os.path.exists(name):
        return QUrl.fromLocalFile(name).toString()
    path = index.get(name, "")
    return QUrl.fromLocalFile(path).toString() if path else ""


def _catalog():
    apps, seen = {}, set()
    for d in APP_DIRS:
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            continue
        for f in entries:
            app_id = f[:-8]
            if not f.endswith(".desktop") or app_id in seen:
                continue
            p = configparser.ConfigParser(interpolation=None, strict=False)
            p.optionxform = str
            try:
                p.read(os.path.join(d, f), encoding="utf-8")
                e = p["Desktop Entry"]
            except (OSError, configparser.Error, KeyError, UnicodeDecodeError):
                continue
            seen.add(app_id)  # A higher-priority hidden entry masks the lower ones.
            if e.get("Type") != "Application" or e.get("NoDisplay") == "true" or e.get("Hidden") == "true" or e.get("Terminal") == "true":
                continue
            apps[app_id] = dict(id=app_id, name=e.get("Name", app_id), iconName=e.get("Icon", ""))
    return apps


SMART = ("smart:recent", "smart:favorites", "smart:steam")          # smart folders without a parameter; "smart:esde:<system>" is every game of one ES-DE system
RANDOM = "random:game"                           # a tile that starts a random game
PREVIEW = 4                                      # covers shown on a folder tile


def _scan_catalog():
    desktop, icons = _catalog(), _icon_index()
    definitions = esdelib.systems()
    games = esdelib.games(definitions=definitions)
    steam = steamlib.games()
    systems = sorted(games, key=lambda name: definitions[name]["fullname"].lower())
    rows = {
        app_id: dict(id=app_id, name=app["name"], icon=_icon(app["iconName"], icons), cover=False, group="apps")
        for app_id, app in desktop.items()
    }
    rows.update({game["id"]: dict(game, cover=True, group="steam") for game in steam})
    roms, paths = {}, {}
    for system, found in games.items():
        for game in found:
            app_id = game["id"]
            roms[app_id] = dict(game, system=system)
            paths[game["rom"]] = app_id
            icon = QUrl.fromLocalFile(game["cover"]).toString() if game["cover"] else ""
            rows[app_id] = dict(id=app_id, name=game["name"], icon=icon, cover=True, group="esde:" + system)
    ordered = tuple(sorted(rows.values(), key=lambda row: row["name"].lower()))
    steam_ids = tuple(row["id"] for row in ordered if row["group"] == "steam")
    return (rows, ordered, steam_ids, {game["id"]: game for game in steam}, roms, paths,
            {system: tuple(game["id"] for game in games[system]) for system in systems},
            {system: definitions[system]["fullname"] for system in systems}, _system_art_index(ES) if systems else {})


class Apps(QObject):
    changed = Signal()
    catalogChanged = Signal()
    catalogLoadingChanged = Signal()
    saveFailed = Signal(str)
    _scanned = Signal(int, object)
    _artReady = Signal(int, object)
    _saveFailed = Signal(object)

    def __init__(self, history=None, shortcuts=None):
        super().__init__()
        self._history = history
        self._shortcuts = shortcuts if shortcuts is not None else steamshortcuts.SteamShortcuts(parent=self)
        self._rows, self._steam, self._esde, self._by_path = {}, {}, {}, {}
        self._systems, self._system_items, self._system_art = {}, {}, {}
        self._catalog_rows = self._steam_items = ()
        self._folders, self._next = {}, 1
        saved = self._load()
        self._use_defaults = saved is None
        self._slots = saved if saved is not None else []
        self._requested_scan = 0
        self._scan_running = False
        self._art_running = False
        self._art_generation = 0
        self._tile_art = {}
        self._art_attempted = set()
        self._save_lock = threading.Lock()
        self._pending_save = None
        self._writer = None
        self._writes_paused = self._deferred_save = False
        self._save_error = None
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)
        self._saveFailed.connect(self._report_save_error, Qt.QueuedConnection)
        self._scanned.connect(self._accept_scan, Qt.QueuedConnection)
        self._artReady.connect(self._accept_art, Qt.QueuedConnection)
        if getattr(history, "changed", None) is not None:
            history.changed.connect(self._history_changed)
        self.refreshCatalog()

    @Property(bool, notify=catalogLoadingChanged)
    def catalogLoading(self):
        return self._scan_running

    @Slot()
    def refreshCatalog(self):
        self._requested_scan += 1
        if not self._scan_running:
            self._scan_running = True
            self.catalogLoadingChanged.emit()
            self._start_scan()

    def _start_scan(self):
        generation = self._requested_scan

        def scan():
            try:
                snapshot = _scan_catalog()
            except Exception:
                log.exception("Failed to refresh application catalog")
                snapshot = None
            self._scanned.emit(generation, snapshot)

        threading.Thread(target=scan, daemon=True).start()

    @Slot(int, object)
    def _accept_scan(self, generation, snapshot):
        if generation != self._requested_scan:
            self._start_scan()
            return
        self._scan_running = False
        if snapshot is not None:
            (self._rows, self._catalog_rows, self._steam_items, self._steam, self._esde, self._by_path,
             self._system_items, self._systems, self._system_art) = snapshot
            if self._use_defaults:
                self._slots = [app_id for app_id in DEFAULTS if app_id in self._rows]
                self._use_defaults = False
            self._art_generation += 1
            self._art_attempted.clear()
            self._queue_art()
            self.catalogChanged.emit()
            self.changed.emit()
        self.catalogLoadingChanged.emit()

    @Slot()
    def _history_changed(self):
        self._queue_art()
        self.changed.emit()

    @Slot()
    def _queue_art(self):
        wanted = []
        for app_id in self._slots:
            if app_id.startswith(("folder:", "smart:")):
                wanted.extend(self._items_of(app_id)[:PREVIEW])
            else:
                wanted.append(app_id)
        paths = {self._esde[app_id]["cover"] for app_id in wanted if app_id in self._esde}
        paths.discard("")
        self._tile_art = {path: url for path, url in self._tile_art.items() if path in paths}
        if self._art_running:
            return
        self._art_attempted.intersection_update(paths)
        paths.difference_update(self._art_attempted)
        if not paths:
            return
        generation = self._art_generation
        self._art_running = True
        self._art_attempted.update(paths)

        def render():
            rendered = {}
            for path in paths:
                try:
                    rendered[path] = steamlib._url(path)
                except Exception:
                    log.exception("Failed to render cover for %s", path)
                    rendered[path] = ""
            self._artReady.emit(generation, rendered)

        threading.Thread(target=render, daemon=True).start()

    @Slot(int, object)
    def _accept_art(self, generation, rendered):
        self._art_running = False
        if generation == self._art_generation:
            updates = {path: url for path, url in rendered.items() if url and self._tile_art.get(path) != url}
            self._tile_art.update(updates)
        else:
            updates = {}
        self._queue_art()
        if updates:
            self.changed.emit()

    def _plain(self, app_id):
        return app_id in self._rows

    def _smart(self, app_id):
        return app_id in SMART or (app_id.startswith("smart:esde:") and app_id[11:] in self._systems)

    def _known(self, app_id):
        return self._plain(app_id) or (app_id.startswith("folder:") and app_id[7:] in self._folders) or self._smart(app_id) or app_id == RANDOM

    def _load(self):
        try:
            with open(CONFIG, encoding="utf-8") as stream:
                saved = json.load(stream)
            slots = [app_id for app_id in saved["slots"] if isinstance(app_id, str)]
            folders = {
                str(key): dict(name=str(folder.get("name", "")),
                               items=[item for item in folder.get("items", []) if isinstance(item, str)])
                for key, folder in saved.get("folders", {}).items()
            }
            next_folder = int(saved.get("next", len(folders) + 1))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None
        self._folders, self._next = folders, next_folder
        return slots

    def _save(self):
        if self._writes_paused:
            self._deferred_save = True
            return
        snapshot = {
            "slots": tuple(self._slots),
            "folders": {key: dict(name=folder["name"], items=tuple(folder["items"]))
                        for key, folder in self._folders.items()},
            "next": self._next,
        }
        with self._save_lock:
            self._pending_save = (CONFIG, snapshot)
            if self._writer is None:
                self._start_writer()

    def _start_writer(self, retry=True):
        self._writer = threading.Thread(target=self._write_pending, args=(retry,), daemon=True)
        self._writer.start()
        return self._writer

    def _write_pending(self, retry):
        failed = None
        while True:
            with self._save_lock:
                pending = self._pending_save
                if pending is None:
                    self._writer = None
                    return
            path, snapshot = pending
            try:
                _write_layout(path, snapshot)
            except OSError as error:
                log.exception("Failed to save app layout to %s", path)
                with self._save_lock:
                    self._save_error = error
                    if self._pending_save is not pending:
                        continue   # A newer snapshot already includes this edit.
                    if not retry or failed is pending:
                        self._writer = None
                        self._saveFailed.emit(pending)
                        return
                failed = pending
                time.sleep(0.1)
            else:
                with self._save_lock:
                    self._save_error = None
                    if self._pending_save is pending:
                        self._pending_save = None

    @Slot(object)
    def _report_save_error(self, pending):
        with self._save_lock:
            error = self._save_error if pending is self._pending_save and self._writer is None else None
        if error is not None:
            self.saveFailed.emit(str(error))

    def pauseWrites(self):
        self._writes_paused = True

    def writesPending(self):
        with self._save_lock:
            if self._writer is not None:
                return True
            if self._save_error is not None:
                raise self._save_error
        return False

    def resumeWrites(self):
        self._writes_paused = False
        if self._deferred_save:
            self._deferred_save = False
            self._save()

    @Slot()
    def flush(self, timeout=3.0):
        """Drain accepted edits, or raise if the latest snapshot remains unsaved."""
        with self._save_lock:
            writer = self._writer
            if writer is None and self._pending_save is not None and not self._writes_paused:
                writer = self._start_writer(retry=False)
        if writer is not None:
            writer.join(timeout)
            if writer.is_alive():
                raise TimeoutError("Timed out saving app layout")
        self.writesPending()

    @Slot()
    def _shutdown(self):
        try:
            self.flush()
        except OSError as error:
            log.error("App layout remains unsaved at shutdown: %s", error)

    # --- what a tile or a list row shows ---
    def _resolve(self, key, rec):
        """The catalog id of a game from the play history, None when it cannot be started from here any more."""
        if key in self._esde:
            return key
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
            return self._folders.get(app_id[7:], {}).get("items", [])
        if app_id == "smart:recent":
            found = [self._resolve(k, r) for k, r in (self._history.recent(40) if self._history else [])]
            return list(dict.fromkeys(i for i in found if i))[:24]
        if app_id == "smart:favorites":
            found = [self._resolve(k, r) for k, r in (self._history.favorites() if self._history else [])]
            return sorted(set(i for i in found if i), key=lambda i: (self._esde.get(i) or self._steam.get(i))["name"].lower())
        if app_id == "smart:steam":
            return self._steam_items
        if app_id.startswith("smart:esde:"):
            return self._system_items.get(app_id[11:], ())
        return []

    def _entry(self, app_id, preview=True):
        if app_id == RANDOM:
            return dict(id=app_id, name="Random game", icon="", cover=False, glyph="🎲", group="folders")
        if app_id.startswith(("folder:", "smart:esde:")) or app_id in SMART:
            names = {"smart:recent": "Recently played", "smart:favorites": "Favorites", "smart:steam": "Steam"}
            if app_id.startswith("folder:"):
                name = self._folders.get(app_id[7:], {}).get("name") or "Folder " + app_id[7:]
            elif app_id.startswith("smart:esde:"):
                name = self._systems.get(app_id[11:], app_id[11:])
            else:
                name = names[app_id]
            if not preview:
                return dict(id=app_id, name=name, folder=True, group="folders")
            items = self._items_of(app_id)
            art = self._system_art.get(app_id[11:], "") if app_id.startswith("smart:esde:") else ""
            return dict(id=app_id, name=name, icon="", art=art, cover=False, folder=True, manual=app_id.startswith("folder:"), count=len(items), group="folders",
                        preview=[self._game_entry(i)["icon"] for i in items[:PREVIEW]])
        return self._game_entry(app_id)

    def _game_entry(self, app_id, thumb=False):
        row = self._rows.get(app_id)
        if row is None:
            return dict(id=app_id, name=app_id, icon="", cover=False, unavailable=True)
        if not thumb and app_id in self._esde:
            cover = self._esde[app_id]["cover"]
            return dict(row, icon=self._tile_art.get(cover, ""))
        return dict(row)

    @Property("QVariant", notify=changed)
    def slots(self):
        return [self._entry(s) for s in self._slots] + [{}]   # the last, empty tile adds one

    @Slot(result="QVariant")
    def catalog(self):
        return [dict(row) for row in self._catalog_rows]

    @Slot(result="QVariant")
    def groups(self):
        """The picker's tabs: desktop apps, Steam, then every ES-DE system that has games."""
        out = [dict(id="apps", label=""), dict(id="steam", label=""), dict(id="folders", label="")]
        return out + [dict(id="esde:" + system, label=label) for system, label in self._systems.items()]

    @Slot(result="QVariant")
    def folderChoices(self):
        """What the picker's Folders tab offers: a new folder, the folders there are, the smart ones and the random tile."""
        ids = ["folder:new"] + ["folder:" + f for f in self._folders] + list(SMART) + ["smart:esde:" + system for system in self._systems] + [RANDOM]
        out = []
        for i in ids:
            e = dict(id=i, name="New folder", icon="", cover=False, glyph="+", group="folders") if i == "folder:new" else self._entry(i, preview=False)
            out.append(e)
        return out

    @Slot(str, result="QVariant")
    def folderItems(self, folder_id):
        """The entries inside a folder, for its view."""
        return [self._game_entry(i, thumb=True) for i in self._items_of(folder_id)[:600]]

    # --- changing the grid ---
    @Slot(int, str)
    def assign(self, slot, app_id):
        if not 0 <= slot <= len(self._slots):
            return
        if app_id == "folder:new":
            app_id = self._create_folder()
        if app_id == "":
            if slot == len(self._slots):
                return
            gone = self._slots.pop(slot)
            if gone.startswith("folder:") and gone not in self._slots:
                self._folders.pop(gone[7:], None)     # a folder that is nowhere any more is forgotten
        elif self._known(app_id):
            if slot == len(self._slots):
                self._slots.append(app_id)
            else:
                self._slots[slot] = app_id
        else:
            return
        self._use_defaults = False
        self._save()
        self._queue_art()
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
            self._queue_art()
            self.changed.emit()

    @Slot(str, str)
    def removeFromFolder(self, folder_id, app_id):
        f = self._folders.get(folder_id[7:]) if folder_id.startswith("folder:") else None
        if f is not None and app_id in f["items"]:
            f["items"].remove(app_id)
            self._save()
            self._queue_art()
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
        """Starts a random launchable item in the folder."""
        items = [app_id for app_id in self._items_of(folder_id) if self._plain(app_id)]
        if items:
            self.launchId(random.choice(items))

    @Slot(str)
    def launchId(self, app_id):
        if app_id == RANDOM:
            if self._shortcuts.state["busy"]:
                return
            pool = list(self._esde) + [i for i in self._steam]
            if pool:
                self.launchId(random.choice(pool))
            return
        if app_id in self._steam:
            self._shortcuts.launch_steam(app_id[6:], self._steam[app_id]["name"], lambda: app_id in self._steam)
            return
        if app_id in self._esde:
            game = self._esde[app_id]

            def current():
                entry = self._esde.get(app_id)
                return entry is not None and (entry["system"], entry["rom"]) == (game["system"], game["rom"])

            self._shortcuts.launch(game["name"], game["system"], game["rom"], esdelib.command, current)
            return
        if not self._plain(app_id):  # only ids from the catalog ever reach gtk-launch
            return
        # run as a plain app on the bottom Plasma session; our own Qt settings must not leak into it
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "QT_QUICK_CONTROLS_STYLE")}
        subprocess.Popen(["gtk-launch", app_id], env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
