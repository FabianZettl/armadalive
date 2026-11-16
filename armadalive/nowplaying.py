"""What is being played right now: follows ES-DE through the state file its event hook writes."""
import glob, json, os, random, re, time
import xml.etree.ElementTree as ET
from functools import lru_cache
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from .poller import Poller
from . import steamlib

ES = os.path.expanduser(os.environ.get("ARMADALIVE_ESDE_DIR", "~/ES-DE"))
MEDIA, GAMELISTS = ES + "/downloaded_media", ES + "/gamelists"
CHEAT_DIRS = [os.path.expanduser(p) for p in (
    "~/.var/app/org.libretro.RetroArch/config/retroarch/cheats", "~/.config/retroarch/cheats")]
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
STATE = os.path.join(RUNTIME, "armadalive", "state.json")

STEAM_LIBRARIES = [os.path.expanduser(p) for p in ("~/.local/share/Steam", "/run/media/armada/EXT")]
# emulators recognised by the name of their executable (RetroArch, AppImages, Flatpaks); a file manager is not one of them
EMULATORS = ("retroarch", "eden", "azahar", "cemu", "armsx2", "pcsx2", "dolphin-emu", "ppsspp", "rpcs3", "xemu", "duckstation",
             "vita3k", "mgba", "melonds", "flycast", "redream", "xenia", "shadps4", "citra", "yuzu", "ryujinx", "mednafen", "scummvm", "dosbox")
_cheats = {}
LUDO = os.path.expanduser("~/.config/ludo/library_snapshot.json")


def _first(pattern):
    hit = sorted(glob.glob(pattern))
    return hit[0] if hit else ""


def _url(path):
    return QUrl.fromLocalFile(path).toString() if path else ""


def _system_logo(system):
    return _first(glob.escape(ES) + f"/themes/*/_inc/systems/logos/{glob.escape(system)}.svg")


def _file_stamp(path):
    stat = os.stat(path)
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=64)
def _parse_gamelist(path, stamp):
    # Preserve the existing basename match, including its choice for duplicate names.
    return {os.path.basename(game.findtext("path") or ""): game for game in ET.parse(path).getroot().iter("game")}


def _gamelist_entries(system):
    path = f"{GAMELISTS}/{system}/gamelist.xml"
    try:
        return _parse_gamelist(path, _file_stamp(path))
    except (OSError, ET.ParseError):
        return {}


def _game_title(system, path):
    """The name ES-DE's gamelist gives a game (empty if it has no entry)."""
    game = _gamelist_entries(system).get(os.path.basename(path))
    return (game.findtext("name") or "") if game is not None else ""


def _cheat_file(path):
    global _cheats
    if not _cheats:  # shortcut: indexed once per run, restart ArmadaLive after adding .cht files
        found = {}
        for base in CHEAT_DIRS:
            for root, _, files in os.walk(base):
                for f in files:
                    if f.endswith(".cht"):
                        found.setdefault(f[:-4].lower(), os.path.join(root, f))
        _cheats = found
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
        value = re.search(r'name="ROMDirectory" value="([^"]*)"', open(ES + "/settings/es_settings.xml").read()).group(1)
    except (OSError, AttributeError):
        value = ""
    return (value or "/run/media/armada/EXT/Emulation/roms").rstrip("/")


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
            for marker in (rom_dir + "/", "/roms/"):   # Ludo mounts the card as /run/media/EXT, ES-DE as /run/media/armada/EXT
                at = text.find(marker)
                if at >= 0:
                    break
            parts = text[at + len(marker):].split("/") if at >= 0 else []
            if len(parts) >= 2 and (best is None or int(pid) > best[0]):  # system folder + game; the newest process wins
                best = (int(pid), parts[0], parts[1])
    if not best:
        return None
    _, system, game = best
    return dict(event="game-start", system=system, path=f"{rom_dir}/{system}/{game}", name=os.path.splitext(game)[0], pid=best[0])


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


def _shortcut_title(appid):
    found = steamlib.shortcut(appid)
    if found and not os.path.basename(found[1].strip('"')).lower().startswith("es-de"):
        return found[0] or str(appid)
    return None


def describe_shortcut(appid):
    """A running non-Steam shortcut that is not ES-DE (TotK, Moonlight, ...), or None."""
    if (title := _shortcut_title(appid)) is not None:
        return dict(_steam_selection(appid, title, playing=True), **_steam_art(appid, True))
    return None


def esde_running():
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                if os.path.basename(open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[0].decode(errors="replace")).lower().startswith("es-de"):
                    return True
            except OSError:
                pass
    return False


def _steam_selection(appid, name, playing=False):
    return dict(kind="game", title=name or str(appid), logo="", fanart="", manual="", hasCheats=False, playing=playing,
                key=f"steam/{appid}", system="steam")


def _steam_art(appid, allow_grid):
    steam = os.path.expanduser("~/.local/share/Steam")
    cache = glob.escape(f"{steam}/appcache/librarycache/{appid}")
    logo, hero = _first(cache + "/logo.png"), _first(cache + "/library_hero.jpg")
    if allow_grid:
        grid = glob.escape(f"{steam}/userdata") + f"/*/config/grid/{glob.escape(str(appid))}"
        logo, hero = logo or _first(grid + "_logo.*"), hero or _first(grid + "_hero.*")
    return dict(logo=_url(logo), fanart=_url(hero))


def describe_steam_ui(appid, name):
    """An app highlighted in Steam's interface, with library or shortcut artwork."""
    out = _steam_selection(appid, name)
    out.update(_steam_art(appid, True))
    return out


@lru_cache(maxsize=1)
def _parse_ludo_library(path, stamp):
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    return data.get("server_url", "").rstrip("/"), {g["rom_id"]: g for g in data.get("games", [])}


def _ludo_library():
    try:
        return _parse_ludo_library(LUDO, _file_stamp(LUDO))
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return "", {}


def _ludo_selection(appid, name):
    rom_id = int(appid.split(":")[1])
    return dict(kind="game", title=name or str(rom_id), logo="", fanart="", manual="", hasCheats=False,
                playing=False, key=f"ludo/{rom_id}", system="steam", path="")


def _ludo_art(appid, screenshot):
    """Prefer the local game's artwork, otherwise use the server's screenshot."""
    rom_id = int(appid.split(":")[1])
    server, games = _ludo_library()
    path = (games.get(rom_id) or {}).get("local_path", "")
    system = os.path.basename(os.path.dirname(path))
    art = _game_art(system, path) if _valid_system(system) else dict(logo="", fanart="", manual="")
    if not art["fanart"] and server and screenshot:
        art["fanart"] = server + screenshot
    return art


def describe_ludo(appid, name, screenshot):
    out = _ludo_selection(appid, name)
    out.update(_ludo_art(appid, screenshot))
    return out


def _steam_title(appid):
    for lib in STEAM_LIBRARIES:
        try:
            with open(f"{lib}/steamapps/appmanifest_{appid}.acf", encoding="utf-8", errors="replace") as manifest:
                match = re.search(r'"name"\s+"(.*?)"', manifest.read(128 * 1024))
                if match is not None:
                    return match.group(1)
        except OSError:
            continue
    return None


def describe_steam(appid):
    """A running Steam game: title from its manifest and local artwork, or None if unknown."""
    if (title := _steam_title(appid)) is not None:
        out = _steam_selection(appid, title, playing=True)
        out.update(_steam_art(appid, False))
        return out
    return None


def _focused_game(appid):
    if appid is None:
        return None
    title = _shortcut_title(appid) if int(appid) >= 2**31 else _steam_title(appid)
    return appid, title


def _valid_system(system):
    return isinstance(system, str) and system not in ("", ".", "..") and "/" not in system and "\0" not in system


def _esde_selection(event):
    """Describe the current identity and play state without looking up presentation fields."""
    ev, system, path = event.get("event", "idle"), event.get("system", ""), event.get("path", "")
    out = dict(kind="idle", title="ArmadaLive", logo="", fanart="", manual="", hasCheats=False, playing=False, key="", system="", path="")
    request = None
    if _valid_system(system):
        if ev == "system-select":
            out.update(kind="system", title=event.get("systemName") or system, system=system)
            request = ("system", system, event.get("t", 0))
        elif path and ev not in ("quit", "startup"):
            stem = os.path.splitext(os.path.basename(path))[0]
            out.update(kind="game", title=event.get("name") or stem, playing=ev == "game-start",
                       key=f"{system}/{stem}", system=system, path=path)
            request = ("game", system, path)
    return out, request


def _game_art(system, path):
    stem = os.path.splitext(os.path.basename(path))[0]

    def media(kind):
        return _first(glob.escape(f"{MEDIA}/{system}/{kind}/{stem}") + ".*")

    return dict(logo=_url(media("marquees")), fanart=_url(media("fanart") or media("screenshots")), manual=_url(media("manuals")))


def _read_metadata(request):
    if request is None:
        return None
    kind, *args = request
    if kind == "game":
        system, path = args
        fields = dict(_game_art(system, path), hasCheats=bool(_cheat_file(path)))
        if title := _game_title(system, path):
            fields["title"] = title
    elif kind == "ludo":
        fields = _ludo_art(*args)
    elif kind == "steam":
        fields = _steam_art(*args)
    else:
        system, seed = args
        fan = sorted(glob.glob(glob.escape(f"{MEDIA}/{system}/fanart") + "/*"))
        fields = dict(logo=_url(_system_logo(system)), fanart=_url(random.Random(seed).choice(fan) if fan else ""))
    return request, fields


def describe(event):
    """Synchronous snapshot for callers that explicitly need a complete description."""
    state, request = _esde_selection(event)
    if request is not None:
        state.update(_read_metadata(request)[1])
    return state


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
        self._base_state, self._metadata_fields = self._state, None
        metadata = self._metadata_request = [None]
        focus = self._focus_request = [None]
        self._focus_pending = False
        self._metadata = Poller(self, lambda: _read_metadata(metadata[0]), self._metadata_ready, 2000, now=False)
        self._focus_lookup = Poller(self, lambda: _focused_game(focus[0]), self._focus_ready, 2000, now=False)
        self._focus_lookup.failed.connect(self._focus_failed)
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
        if self._pinned:
            return
        was = self._ui_focus
        self._ui_focus = app == "769"  # 769 is Steam's own interface in the foreground
        appid = int(app) if app.isdigit() else 0
        self._shortcut = appid >= 2**31
        if was and not self._ui_focus:
            # A game just started from Steam's interface needs time to take focus.
            self._hold = time.monotonic() + 25
            QTimer.singleShot(26000, self, self._update)
        request = app if appid and not self._ui_focus else None
        if request != self._focus_request[0]:
            self._steam = self._sgame = None
            self._focus_request[0] = request
            self._focus_pending = request is not None
            self._focus_lookup.refresh()
        self._update()

    def _focus_ready(self, result):
        appid, title = result
        if self._pinned or appid != self._focus_request[0]:
            return
        self._focus_pending = False
        game = _steam_selection(appid, title, playing=True) if title is not None else None
        steam = game if not self._shortcut else None
        shortcut = game if self._shortcut else None
        if (steam, shortcut) != (self._steam, self._sgame):
            self._steam, self._sgame = steam, shortcut
            self._update()
        elif game is None:
            # The first lookup of an unknown window lets the normal fallback take focus.
            self._focus_request[0] = None
            self._update()

    def _focus_failed(self, _error):
        if self._focus_pending:
            self._focus_pending = False
            self._update()

    def pin(self, event=None, ui=None):
        """Hold one complete snapshot fixed, whatever the system does afterwards."""
        self._pinned = False
        self._proc, self._steam, self._sgame, self._esde = None, None, None, True
        self._focus_request[0] = None
        self._focus_pending = False
        self._focus_lookup.refresh()
        self._ui_focus, self._ui_app = bool(ui), tuple(ui) if ui else (0, "")
        self._event = event or {}
        self._update(synchronous=True)
        self._pinned = True

    def _selected_ui(self):
        appid, name = self._ui_app
        if not appid:
            return _esde_selection({})
        if isinstance(appid, str):
            return _ludo_selection(appid, name), ("ludo", appid, getattr(self._steamui, "screenshot", ""))
        return _steam_selection(appid, name), ("steam", str(appid), True)

    def _update(self, synchronous=False):
        """Follow the foreground selection without waiting for title or artwork."""
        # Keep the last foreground game until the new focus is classified.
        if self._pinned or self._focus_pending:
            return
        if self._ui_focus:  # Browsing Steam wins over anything running behind it.
            self._path, key = "", None
            state, request = self._selected_ui()
        elif self._steam:
            self._path, state, key = "", self._steam, self._steam["key"].partition("/")[2]
            request = ("steam", key, False)
        elif self._sgame and not self._proc:
            self._path, state, key = "", self._sgame, "sgame|" + self._sgame["key"]
            request = ("steam", self._sgame["key"].partition("/")[2], True)
        elif self._ui_app[0] and time.monotonic() < self._hold and not self._shortcut:
            self._path, key = "", None
            state, request = self._selected_ui()
        else:
            # An ES-DE browsing event wins over an emulator left running behind it.
            browsing = self._esde and self._event.get("event") in ("game-select", "system-select")
            shown = (self._event if browsing else None) or self._proc or (self._event if self._esde else {})
            self._path = shown.get("path", "")
            state, request = _esde_selection(shown)
            key = ("run|" + shown["path"]) if shown is self._proc else (shown.get("event", "") + "|" + (shown.get("path") or shown.get("system") or ""))
        self._base_state = state
        if synchronous or request != self._metadata_request[0]:
            self._metadata_request[0] = None if synchronous else request
            self._metadata_fields = _read_metadata(request)[1] if synchronous and request is not None else None
            self._metadata.refresh()
        self._publish_state()
        if key is not None and key != self._key:  # A Steam highlight must not switch pages.
            self._key = key
            self.selection.emit()

    def _publish_state(self):
        self._state = dict(self._base_state, **(self._metadata_fields or {}))
        self._state["metadataPending"] = self._metadata_request[0] is not None and self._metadata_fields is None
        self._state["playtime"] = self.history.total_for(self._state["key"]) if self.history else 0
        self.changed.emit()

    def _metadata_ready(self, result):
        request, fields = result
        if request == self._metadata_request[0] and not self._pinned and self._metadata_fields != fields:
            self._metadata_fields = fields
            self._publish_state()
