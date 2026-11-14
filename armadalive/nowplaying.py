"""What is being played right now: follows ES-DE through the state file its event hook writes."""
import glob, json, os, random, re, time
import xml.etree.ElementTree as ET
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from .poller import Poller
from . import steamlib

ES = os.path.expanduser(os.environ.get("ARMADALIVE_ESDE_DIR", "~/ES-DE"))
MEDIA, GAMELISTS = ES + "/downloaded_media", ES + "/gamelists"
CHEAT_DIRS = [os.path.expanduser(p) for p in (
    "~/.var/app/org.libretro.RetroArch/config/retroarch/cheats", "~/.config/retroarch/cheats")]
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
STATE = os.path.join(RUNTIME, "armadalive", "state.json")

# emulators recognised by the name of their executable (RetroArch, AppImages, Flatpaks); a file manager is not one of them
EMULATORS = ("retroarch", "eden", "azahar", "cemu", "armsx2", "pcsx2", "dolphin-emu", "ppsspp", "rpcs3", "xemu", "duckstation",
             "vita3k", "mgba", "melonds", "flycast", "redream", "xenia", "shadps4", "citra", "yuzu", "ryujinx", "mednafen", "scummvm", "dosbox")
_gamelists, _cheats = {}, {}
LUDO = os.path.expanduser("~/.config/ludo/library_snapshot.json")
_ludo = (0, "", {})   # snapshot mtime, server URL, games by RomM id


def _first(pattern):
    hit = sorted(glob.glob(pattern))
    return hit[0] if hit else ""


def _url(path):
    return QUrl.fromLocalFile(path).toString() if path else ""


def _system_logo(system):
    return _first(glob.escape(ES) + f"/themes/*/_inc/systems/logos/{glob.escape(system)}.svg")


def rom_relative(system, path):
    """Match an absolute launcher path and an ES-DE relative gamelist path."""
    path = os.path.normpath(path)
    if os.path.isabs(path):
        parts = path.split("/")
        for index, part in enumerate(parts[:-2]):
            if part == "roms" and parts[index + 1] == system:
                return "/".join(parts[index + 2:])
        for index, part in enumerate(parts[:-1]):
            if part == system:
                return "/".join(parts[index + 1:])
        return os.path.basename(path)
    return path if path != ".." and not path.startswith("../") else os.path.basename(path)


def _game_title(system, path):
    """The name ES-DE's gamelist gives a game (empty if it has no entry)."""
    f = f"{GAMELISTS}/{system}/gamelist.xml"
    try:
        mtime = os.stat(f).st_mtime_ns
        if _gamelists.get(f, (None,))[0] != mtime:
            _gamelists[f] = (mtime, {rom_relative(system, g.findtext("path") or ""): g.findtext("name") or ""
                                    for g in ET.parse(f).getroot().iter("game")})
        return _gamelists[f][1].get(rom_relative(system, path), "")
    except (OSError, ET.ParseError):
        return ""


def _cheat_file(path):
    if not _cheats:  # shortcut: indexed once per run, restart ArmadaLive after adding .cht files
        for base in CHEAT_DIRS:
            for root, _, files in os.walk(base):
                for f in files:
                    if f.endswith(".cht"):
                        _cheats.setdefault(f[:-4].lower(), os.path.join(root, f))
    return _cheats.get(os.path.splitext(os.path.basename(path))[0].lower(), "")


def read_cheats(path):
    f = _cheat_file(path)
    if not f:
        return []
    kv = dict(re.findall(r'^(cheat\d+_(?:desc|code))\s*=\s*"(.*)"\s*$', open(f, errors="replace").read(), re.M))
    return [{"desc": kv[k], "code": kv.get(k.replace("desc", "code"), "")}
            for k in sorted(kv, key=lambda k: int(re.search(r"\d+", k).group())) if k.endswith("_desc")]


def _rom_dir():
    try:
        with open(ES + "/settings/es_settings.xml", encoding="utf-8") as settings:
            value = re.search(r'name="ROMDirectory" value="([^"]*)"', settings.read()).group(1)
    except (OSError, AttributeError):
        value = ""
    return os.path.expanduser(value or "/run/media/armada/EXT/Emulation/roms").rstrip("/")


def _rom_path(path, root):
    """Find the system and its relative game path under either ROM mount."""
    for marker in (root + "/", "/roms/"):
        _, found, relative = path.partition(marker)
        if found:
            system, sep, game = relative.partition("/")
            if sep and system and game:
                return system, game
    return "", ""


def running_game():
    """The ES-DE style event of an emulator that is running right now, found by the ROM it was started with."""
    rom_dir, best = _rom_dir(), None
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            args = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        if not os.path.basename(args[0].decode(errors="replace")).lower().startswith(EMULATORS):
            continue
        for arg in args[1:]:
            text = arg.decode(errors="replace")
            system, game = _rom_path(text, rom_dir)
            if game and (best is None or int(pid) > best[0]):  # the newest process wins
                best = (int(pid), system, game)
    if not best:
        return None
    _, system, game = best
    return dict(event="game-start", system=system, path=f"{rom_dir}/{system}/{game}", name=os.path.splitext(os.path.basename(game))[0], pid=best[0])


def steam_running():
    """True while Steam runs some game of its own (`reaper SteamLaunch AppId=...`): a Steam game or a shortcut, but not ES-DE
    itself, whose emulators are found by their ROM."""
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                args = open(f"/proc/{pid}/cmdline", "rb").read().decode(errors="replace").split("\0")
            except OSError:
                continue
            if "SteamLaunch" in args and any(a.startswith("AppId=") for a in args) and "es-de" not in " ".join(args).lower():
                return True
    return False


def describe_shortcut(appid):
    """A running non-Steam shortcut that is not ES-DE (TotK, Moonlight, ...) as a game; None for anything else."""
    found = steamlib.shortcut(appid)
    if not found or os.path.basename(found[1].strip('"')).lower().startswith("es-de"):
        return None
    return dict(describe_steam_ui(appid, found[0]), playing=True)


def esde_running():
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                if os.path.basename(open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[0].decode(errors="replace")).lower().startswith("es-de"):
                    return True
            except OSError:
                pass
    return False


def describe_steam_ui(appid, name):
    """An app highlighted in Steam's UI: Steam games have art in the library cache, shortcuts (ES-DE, ...) in the grid folder."""
    steam = steamlib.STEAM or os.path.expanduser("~/.local/share/Steam")
    cache, grid = f"{steam}/appcache/librarycache/{appid}", glob.escape(f"{steam}/userdata") + f"/*/config/grid/{appid}"
    logo = _first(cache + "/logo.png") or _first(grid + "_logo.*")
    hero = _first(cache + "/library_hero.jpg") or _first(grid + "_hero.*")
    return dict(kind="game", title=name or str(appid), logo=_url(logo), fanart=_url(hero), manual="", hasCheats=False, playing=False,
                key=f"steam/{appid}", system="steam")


def _ludo_library():
    global _ludo
    try:
        mtime = os.stat(LUDO).st_mtime_ns
        if mtime != _ludo[0]:
            data = json.load(open(LUDO))
            _ludo = (mtime, data.get("server_url", "").rstrip("/"), {g["rom_id"]: g for g in data.get("games", [])})
    except (OSError, ValueError, KeyError, AttributeError):
        _ludo = (0, "", {})
    return _ludo[1:]


def describe_ludo(appid, name, screenshot):
    """A game highlighted in the Ludo plugin: a downloaded one has the ES-DE art of its ROM, any other the server's screenshot."""
    rom_id = int(appid.split(":")[1])
    server, games = _ludo_library()
    path = (games.get(rom_id) or {}).get("local_path", "")
    out = {}
    if path:
        system, relative = _rom_path(path, _rom_dir())
        if system:
            out = describe(dict(event="game-select", system=system, path=relative))
        else:
            out = describe(dict(event="game-select", system=os.path.basename(os.path.dirname(path)), path=path))
    if out.get("kind") != "game":
        out = dict(kind="game", logo="", fanart="", manual="")
    if not out["fanart"] and server and screenshot:
        out["fanart"] = server + screenshot
    out.update(title=name or str(rom_id), hasCheats=False, playing=False, key=f"ludo/{rom_id}", system="steam", path="")
    return out


def describe_steam(appid):
    """A running Steam game: title from its manifest, art from Steam's library cache. None if unknown."""
    for lib in sorted(steamlib._libraries() - {""}):
        try:
            with open(f"{lib}/steamapps/appmanifest_{appid}.acf", encoding="utf-8", errors="replace") as manifest:
                title = re.search(r'"name"\s+"(.*?)"', manifest.read()).group(1)
        except (OSError, AttributeError):
            continue
        return dict(describe_steam_ui(appid, title), playing=True)
    return None


def describe(event):
    """Reduce an ES-DE event to what the UI shows."""
    ev, system, path = event.get("event", "idle"), event.get("system", ""), event.get("path", "")
    out = dict(kind="idle", title="ArmadaLive", logo="", fanart="", manual="", hasCheats=False, playing=False, key="", system="", path="")
    if ev == "system-select" and re.fullmatch(r"[\w.-]+", system):
        fan = sorted(glob.glob(glob.escape(f"{MEDIA}/{system}/fanart") + "/*"))
        out.update(kind="system", system=system, title=event.get("systemName") or system, logo=_url(_system_logo(system)),
                   fanart=_url(random.Random(event.get("t", 0)).choice(fan) if fan else ""))
    elif path and re.fullmatch(r"[\w.-]+", system) and system not in (".", "..") and ev not in ("quit", "startup"):
        relative = os.path.splitext(rom_relative(system, path))[0]

        def media(kind):
            folder = glob.escape(f"{MEDIA}/{system}/{kind}/")
            return _first(folder + glob.escape(relative) + ".*") or _first(folder + glob.escape(os.path.basename(relative)) + ".*")

        out.update(kind="game", title=_game_title(system, path) or event.get("name", ""), logo=_url(media("marquees")),
                   fanart=_url(media("fanart") or media("screenshots")), manual=_url(media("manuals")),
                   hasCheats=bool(_cheat_file(path)), playing=ev == "game-start",
                   key=f"{system}/{os.path.splitext(os.path.basename(path))[0]}", system=system, path=path)
    return out


class NowPlaying(QObject):
    changed = Signal()
    selection = Signal()

    def __init__(self, gamescope, steamui):
        super().__init__()
        self._event, self._steam, self._proc = {}, None, None
        self._ui_focus, self._ui_app, self._hold, self._esde = False, (0, ""), 0.0, False
        self._pinned = False
        self.running = False     # a game is really running (a process), even while Steam's UI is in front
        self._sgame = None       # the non-Steam shortcut in front, if it is a game of its own
        self._shortcut = False   # a non-Steam shortcut (ES-DE itself, or an emulator it started) is in front
        self._steamui = steamui
        steamui.selected.connect(self._ui_selected)
        self._state, self._mtime, self._key, self._path = describe({}), 0, "", ""
        self.history = None      # set by the app: the one playtime record (history.py)
        gamescope.focusChanged.connect(self._focus)
        self._focus(gamescope.state["focus"])  # the first reading happened before we were listening
        timer = QTimer(self)
        timer.timeout.connect(self._poll)
        timer.start(400)
        self._procs = Poller(self, lambda: (running_game(), esde_running(), steam_running()), self._scan, 2000)   # /proc walk: a worker thread
        self._poll()

    @Property("QVariant", notify=changed)
    def state(self):
        return self._state

    @Slot(result="QVariant")
    def cheats(self):
        return read_cheats(self._path)

    def _poll(self):
        try:
            mtime = os.stat(STATE).st_mtime_ns
            if mtime == self._mtime:
                return
            self._mtime = mtime
            event = json.load(open(STATE))
        except (OSError, ValueError):
            return
        self._event = event
        self._update()

    def _scan(self, found):
        game, esde, steam = found
        moved = game != self._proc or esde != self._esde
        self._proc, self._esde = game, esde
        running = bool(game or steam)
        moved = moved or running != self.running
        self.running = running
        if moved:
            self._update()

    def _ui_selected(self, appid, name):
        self._ui_app = (appid, name)
        self._update()

    def _focus(self, app):
        was = self._ui_focus
        self._ui_focus = app == "769"  # 769 is Steam's own UI in the foreground
        self._shortcut = app.isdigit() and int(app) >= 2**31
        if was and not self._ui_focus:
            # a game that was just started from Steam's UI needs a while before its own id takes the focus
            self._hold = time.monotonic() + 25
            QTimer.singleShot(26000, self._update)
        # AppIds of non-Steam shortcuts (ES-DE itself) are >= 2**31 and have no manifest, so they fall through to ES-DE
        self._steam = describe_steam(app) if app.isdigit() and 0 < int(app) < 2**31 else None
        self._sgame = describe_shortcut(app) if self._shortcut else None
        self._update()

    def pin(self, event=None, ui=None):
        """Hold one state fixed, whatever the system does afterwards (for screenshots and tests)."""
        self._pinned = False
        self._proc, self._steam, self._esde = None, None, True
        self._ui_focus, self._ui_app = bool(ui), tuple(ui) if ui else (0, "")
        self._event = event or {}
        self._update()
        self._pinned = True

    def _update(self):
        """What the bottom screen shows follows what is in front: Steam's UI, a Steam game, or ES-DE and its emulators."""
        if self._pinned:
            return
        ludo = isinstance(self._ui_app[0], str)
        ui = (describe_ludo(*self._ui_app, getattr(self._steamui, "screenshot", "")) if ludo else describe_steam_ui(*self._ui_app)) if self._ui_app[0] else None
        if self._ui_focus:                  # browsing Steam: the highlighted app, whatever runs in the background
            self._path, state, key = "", ui or describe({}), None
        elif self._steam:                   # a Steam game is in front
            self._path, state, key = "", dict(self._steam), self._steam["key"].partition("/")[2]
        elif self._sgame and not self._proc:   # a shortcut that is a game itself, and no emulator of ES-DE's behind it
            self._path, state, key = "", dict(self._sgame), "sgame|" + self._sgame["key"]
        elif ui and time.monotonic() < self._hold and not self._shortcut:  # that game is still starting
            self._path, state, key = "", ui, None
        else:                               # ES-DE's own world
            # while ES-DE is browsing, what it announces wins over an emulator that may still be running behind it
            browsing = self._esde and self._event.get("event") in ("game-select", "system-select")
            shown = (self._event if browsing else None) or self._proc or (self._event if self._esde else {})
            self._path = shown.get("path", "")
            state = describe(shown)
            key = ("run|" + shown["path"]) if shown is self._proc else (shown.get("event", "") + "|" + (shown.get("path") or shown.get("system") or ""))
        self._state = state
        # the playtime of this game, for the Now page; History does the counting
        self._state["playtime"] = self.history.total_for(state.get("key")) if self.history else 0
        self.changed.emit()
        if key is not None and key != self._key:  # browsing Steam's library must not throw the user back to the first page
            self._key = key
            self.selection.emit()
