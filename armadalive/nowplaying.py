"""What is being played right now: follows ES-DE through the state file its event hook writes."""
import glob, json, os, random, re, time
import xml.etree.ElementTree as ET
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

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
_gamelists, _cheats = {}, {}


def _first(pattern):
    hit = sorted(glob.glob(pattern))
    return hit[0] if hit else ""


def _url(path):
    return QUrl.fromLocalFile(path).toString() if path else ""


def _system_logo(system):
    return _first(glob.escape(ES) + f"/themes/*/_inc/systems/logos/{glob.escape(system)}.svg")


def _game_title(system, path):
    f = f"{GAMELISTS}/{system}/gamelist.xml"
    try:
        mtime = os.stat(f).st_mtime
        if _gamelists.get(system, (0,))[0] != mtime:
            # shortcut: matched by file basename, so same-named ROMs in subfolders collide
            _gamelists[system] = (mtime, {os.path.basename(g.findtext("path") or ""): g.findtext("name") or ""
                                          for g in ET.parse(f).getroot().iter("game")})
        return _gamelists[system][1].get(os.path.basename(path), "")
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
            at = text.find(rom_dir + "/")
            parts = text[at + len(rom_dir) + 1:].split("/") if at >= 0 else []
            if len(parts) >= 2 and (best is None or int(pid) > best[0]):  # system folder + game; the newest process wins
                best = (int(pid), parts[0], parts[1])
    if not best:
        return None
    _, system, game = best
    return dict(event="game-start", system=system, path=f"{rom_dir}/{system}/{game}", name=os.path.splitext(game)[0])


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
    steam = os.path.expanduser("~/.local/share/Steam")
    cache, grid = f"{steam}/appcache/librarycache/{appid}", glob.escape(f"{steam}/userdata") + f"/*/config/grid/{appid}"
    logo = _first(cache + "/logo.png") or _first(grid + "_logo.*")
    hero = _first(cache + "/library_hero.jpg") or _first(grid + "_hero.*")
    return dict(kind="game", title=name or str(appid), logo=_url(logo), fanart=_url(hero), manual="", hasCheats=False, playing=False)


def describe_steam(appid):
    """A running Steam game: title from its manifest, art from Steam's library cache. None if unknown."""
    cache = os.path.expanduser(f"~/.local/share/Steam/appcache/librarycache/{appid}")
    for lib in STEAM_LIBRARIES:
        try:
            title = re.search(r'"name"\s+"(.*?)"', open(f"{lib}/steamapps/appmanifest_{appid}.acf").read()).group(1)
        except (OSError, AttributeError):
            continue
        return dict(kind="game", title=title, logo=_url(_first(cache + "/logo.png")),
                    fanart=_url(_first(cache + "/library_hero.jpg")), manual="", hasCheats=False, playing=True)
    return None


def describe(event):
    """Reduce an ES-DE event to what the UI shows."""
    ev, system, path = event.get("event", "idle"), event.get("system", ""), event.get("path", "")
    out = dict(kind="idle", title="ArmadaLive", logo="", fanart="", manual="", hasCheats=False, playing=False)
    if ev == "system-select" and re.fullmatch(r"[\w.-]+", system):
        fan = sorted(glob.glob(glob.escape(f"{MEDIA}/{system}/fanart") + "/*"))
        out.update(kind="system", title=event.get("systemName") or system, logo=_url(_system_logo(system)),
                   fanart=_url(random.Random(event.get("t", 0)).choice(fan) if fan else ""))
    elif path and system and ev not in ("quit", "startup"):
        base = glob.escape(f"{MEDIA}/{system}/%s/" + os.path.splitext(os.path.basename(path))[0])
        media = lambda t: _first((base % t) + ".*")
        out.update(kind="game", title=_game_title(system, path) or event.get("name", ""), logo=_url(media("marquees")),
                   fanart=_url(media("fanart") or media("screenshots")), manual=_url(media("manuals")),
                   hasCheats=bool(_cheat_file(path)), playing=ev == "game-start")
    return out


class NowPlaying(QObject):
    changed = Signal()
    selection = Signal()

    def __init__(self, gamescope, steamui):
        super().__init__()
        self._event, self._steam, self._proc = {}, "", None
        self._ui_focus, self._ui_app, self._hold, self._esde = False, (0, ""), 0.0, False
        self._pinned = False
        self._shortcut = False   # a non-Steam shortcut (ES-DE itself, or an emulator it started) is in front
        steamui.selected.connect(self._ui_selected)
        self._state, self._mtime, self._key, self._path = describe({}), 0, "", ""
        gamescope.focusChanged.connect(self._focus)
        self._focus(gamescope.state["focus"])  # the first reading happened before we were listening
        timer = QTimer(self)
        timer.timeout.connect(self._poll)
        timer.start(400)
        procs = QTimer(self)
        procs.timeout.connect(self._scan)
        procs.start(2000)  # reading /proc is cheap but not worth doing every 400 ms
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

    def _scan(self):
        game, esde = running_game(), esde_running()
        if game != self._proc or esde != self._esde:
            self._proc, self._esde = game, esde
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
        self._steam = app if app.isdigit() and 0 < int(app) < 2**31 and describe_steam(app) else ""
        self._update()

    def pin(self, event=None, ui=None):
        """Hold one state fixed, whatever the system does afterwards (for screenshots and tests)."""
        self._pinned = False
        self._proc, self._steam, self._esde = None, "", True
        self._ui_focus, self._ui_app = bool(ui), tuple(ui) if ui else (0, "")
        self._event = event or {}
        self._update()
        self._pinned = True

    def _update(self):
        """What the bottom screen shows follows what is in front: Steam's UI, a Steam game, or ES-DE and its emulators."""
        if self._pinned:
            return
        ui = describe_steam_ui(*self._ui_app) if self._ui_app[0] else None
        if self._ui_focus:                  # browsing Steam: the highlighted app, whatever runs in the background
            self._path, state, key = "", ui or describe({}), None
        elif self._steam:                   # a Steam game is in front
            self._path, state, key = "", describe_steam(self._steam), self._steam
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
        self.changed.emit()
        if key is not None and key != self._key:  # browsing Steam's library must not throw the user back to the first page
            self._key = key
            self.selection.emit()
