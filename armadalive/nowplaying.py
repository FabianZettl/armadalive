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


def _rom_configuration():
    from . import esdelib

    return _rom_dir(), esdelib.cached_systems(ES)


def _system_folder(system, root, definition):
    from .esdelib import system_folder

    return os.path.abspath(system_folder(system, root, definition))


def _rom_folder(system):
    root, definitions = _rom_configuration()
    return _system_folder(system, root, definitions.get(system))


def _relative_below(path, folder):
    prefix = folder.rstrip("/") + "/"
    return path[len(prefix):] if path.startswith(prefix) else ""


def _same_file(path, candidate):
    try:
        return os.path.samefile(path, candidate)
    except OSError:
        return False


def rom_relative(system, path, folder=None):
    """Normalize a ROM path under its system folder, or return empty if unknown."""
    expanded = os.path.expanduser(path)
    path = os.path.normpath(expanded)
    if not os.path.isabs(expanded):
        return path if path not in (".", "..") and not path.startswith("../") else ""
    folder = folder if folder is not None else _rom_folder(system)
    relative = _relative_below(path, folder) if ".." not in expanded.split("/") else ""
    if relative:
        return relative
    physical = os.path.realpath(expanded)
    if relative := _relative_below(physical, os.path.realpath(folder)):
        return relative
    # Bind mounts need an inode check once the other spelling supplies a candidate.
    alternate = physical.partition(f"/roms/{system}/")[2]
    if alternate and _same_file(expanded, os.path.join(folder, alternate)):
        return alternate
    return ""


def rom_key(system, relative):
    return f"esde:{system}/{relative}" if relative else ""


def legacy_key_parts(key):
    system, sep, stem = key.partition("/")
    if (sep and stem and "/" not in stem and re.fullmatch(r"[\w.-]+", system)
            and system not in (".", "..", "steam", "ludo")):
        return system, stem
    return None


def _raise_walk_error(error):
    raise error


def _legacy_roms(folder, extensions, entries, basenames, stems):
    """Map old basename stems to their ROM path only when one candidate exists."""
    from .esdelib import rom_files

    ambiguous = {os.path.splitext(base)[0] for base, relative in basenames.items() if not relative}
    stems = stems - ambiguous
    if not stems:
        return {}
    matches = {}
    try:
        for relative in rom_files(folder, extensions or None, onerror=_raise_walk_error, stems=stems):
            stem = os.path.splitext(os.path.basename(relative))[0]
            matches[stem] = relative if stem not in matches else ""
    except OSError:
        return {}
    for relative in entries:
        stem = os.path.splitext(os.path.basename(relative))[0]
        if stem in matches and matches[stem] != relative:
            matches[stem] = ""
    return {stem: relative for stem, relative in matches.items() if relative}


def _gamelist(system, folder, gamelists=None):
    f = f"{gamelists or GAMELISTS}/{system}/gamelist.xml"
    try:
        info = os.stat(f)
        # Absolute gamelist paths can normalize differently if a mounted or
        # symlinked collection changes behind the same configured path.
        try:
            root = os.stat(folder)
            location = root.st_dev, root.st_ino
        except OSError:
            location = None
        stamp = (folder, location, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
        indexed = _gamelists.get(f)
        if indexed is None or indexed[0] != stamp:
            entries, basenames = {}, {}
            for game in ET.parse(f).getroot().iter("game"):
                raw = game.findtext("path") or ""
                path = rom_relative(system, raw, folder)
                if path:
                    entries[path] = game
                elif os.path.isabs(os.path.expanduser(raw)):
                    # A record outside the active root is evidence against
                    # assigning its legacy basename to a different collection.
                    basenames[os.path.basename(raw)] = ""
            for path in entries:
                base = os.path.basename(path)
                basenames[base] = "" if base in basenames else path
            indexed = _gamelists[f] = stamp, entries, basenames
        return indexed[1:]
    except (OSError, ET.ParseError):
        return {}, {}


def _gamelist_path(system, path, folder, basenames):
    relative = rom_relative(system, path, folder)
    if not relative and os.path.isabs(os.path.expanduser(path)):
        return basenames.get(os.path.basename(path), "")
    return relative


def _game_title(system, path, folder=None, index=None):
    """The name ES-DE's gamelist gives a game (empty if it has no entry)."""
    folder = folder if folder is not None else _rom_folder(system)
    entries, basenames = index if index is not None else _gamelist(system, folder)
    entry = entries.get(_gamelist_path(system, path, folder, basenames))
    return (entry.findtext("name") or "") if entry is not None else ""


def resolve_legacy_keys(keys, gamelists):
    """Return verified legacy identities and their canonical key and absolute path."""
    by_system = {}
    for key in keys:
        if parts := legacy_key_parts(key):
            system, stem = parts
            by_system.setdefault(system, set()).add(stem)
    if not by_system:
        return {}
    root, definitions = _rom_configuration()
    aliases = {}
    for system, stems in by_system.items():
        definition = definitions.get(system) or {}
        folder = _system_folder(system, root, definition)
        entries, basenames = _gamelist(system, folder, gamelists)
        for stem, relative in _legacy_roms(folder, definition.get("extensions"), entries, basenames, stems).items():
            aliases[f"{system}/{stem}"] = rom_key(system, relative), os.path.join(folder, relative)
    return aliases


def _rule_lookup(keys):
    return (keys, resolve_legacy_keys(keys, GAMELISTS)) if keys else None


def _legacy_key_for_game(key):
    if not key.startswith("esde:"):
        return ""
    system, _, relative = key.removeprefix("esde:").partition("/")
    return f"{system}/{os.path.splitext(os.path.basename(relative))[0]}"


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


def _custom_folders(root, definitions):
    return sorted(((_system_folder(system, root, definition), system) for system, definition in definitions.items()
                   if definition.get("path")), key=lambda pair: len(pair[0]), reverse=True)


def _split_rom_path(path):
    system, sep, game = path.partition("/")
    if sep and game and re.fullmatch(r"[\w.-]+", system) and system not in (".", ".."):
        return system, game
    return "", ""


def _rom_path(path, root, custom=()):
    """Resolve emulator paths against the active collection, including physical spellings."""
    if not os.path.isabs(path):
        path = path.partition("=")[2] if path.startswith("-") else ""
        if not os.path.isabs(path):
            return "", ""
    root = os.path.abspath(root or "/")
    configured = {system: folder for folder, system in custom}
    if ".." not in path.split("/"):
        lexical = os.path.normpath(path)
        for folder, system in custom:
            if relative := _relative_below(lexical, folder):
                return system, relative
        system, relative = _split_rom_path(_relative_below(lexical, root))
        if system and system not in configured:
            return system, relative
    physical = os.path.realpath(path)
    for folder, system in custom:
        if relative := _relative_below(physical, os.path.realpath(folder)):
            return system, relative
    system, relative = _split_rom_path(_relative_below(physical, os.path.realpath(root)))
    if system and system not in configured:
        return system, relative
    system, relative = _split_rom_path(physical.partition("/roms/")[2])
    if system and _same_file(path, os.path.join(configured.get(system, os.path.join(root, system)), relative)):
        return system, relative
    return "", ""


def running_game():
    """The ES-DE style event of an emulator that is running right now, found by the ROM it was started with."""
    rom_dir, definitions = _rom_configuration()
    custom, best = _custom_folders(rom_dir, definitions), None
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
            system, game = _rom_path(text, rom_dir, custom)
            if game and (best is None or int(pid) > best[0]):  # the newest process wins
                best = (int(pid), system, game)
    if not best:
        return None
    _, system, game = best
    folder = _system_folder(system, rom_dir, definitions.get(system))
    return dict(event="game-start", system=system, path=os.path.join(folder, game), name=os.path.splitext(os.path.basename(game))[0], pid=best[0])


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


def _ludo_selection(appid, name):
    rom_id = int(appid.split(":")[1])
    return dict(kind="game", title=name or str(rom_id), logo="", fanart="", manual="", hasCheats=False,
                playing=False, key=f"ludo/{rom_id}", system="steam", path="")


def _ludo_art(appid, screenshot):
    """Prefer the local ROM's ES-DE artwork, otherwise use the server's screenshot."""
    rom_id = int(appid.split(":")[1])
    server, games = _ludo_library()
    path = (games.get(rom_id) or {}).get("local_path", "")
    art = dict(logo="", fanart="", manual="")
    if path:
        root, definitions = _rom_configuration()
        system, relative = _rom_path(path, root, _custom_folders(root, definitions))
        if not system:  # Remote paths can still hint at local artwork, without identifying a ROM.
            system, relative = _split_rom_path(path.partition("/roms/")[2])
        system = system or os.path.basename(os.path.dirname(path))
        if re.fullmatch(r"[\w.-]+", system) and system not in (".", ".."):
            art = _game_art(system, os.path.splitext(relative or os.path.basename(path))[0])
    if not art["fanart"] and server and screenshot:
        art["fanart"] = server + screenshot
    return art


def describe_ludo(appid, name, screenshot):
    return dict(_ludo_selection(appid, name), **_ludo_art(appid, screenshot))


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


def _esde_selection(event):
    """Foreground identity and play state, available before title or artwork lookups."""
    ev, system, path = event.get("event", "idle"), event.get("system", ""), event.get("path", "")
    out = dict(kind="idle", title="ArmadaLive", logo="", fanart="", manual="", hasCheats=False, playing=False, key="", system="", path="")
    request = None
    if not re.fullmatch(r"[\w.-]+", system) or system in (".", ".."):
        return out, request
    if ev == "system-select":
        out.update(kind="system", system=system, title=event.get("systemName") or system)
        request = ("system", system, event.get("t", 0))
    elif path and ev not in ("quit", "startup"):
        root, definitions = _rom_configuration()
        definition = definitions.get(system) or {}
        folder = _system_folder(system, root, definition)
        rom = rom_relative(system, path, folder)
        out.update(kind="game", system=system, path=path, playing=ev == "game-start",
                   title=event.get("name") or os.path.splitext(os.path.basename(path))[0],
                   key=rom_key(system, rom), legacyKey="", romPath=os.path.join(folder, rom) if rom else "")
        request = ("game", system, path, folder, frozenset(definition.get("extensions", ())), rom)
    return out, request


def _game_art(system, relative):
    def media(kind):
        folder = glob.escape(f"{MEDIA}/{system}/{kind}/")
        return _first(folder + glob.escape(relative) + ".*") or _first(folder + glob.escape(os.path.basename(relative)) + ".*")

    return dict(logo=_url(media("marquees")), fanart=_url(media("fanart") or media("screenshots")), manual=_url(media("manuals")))


def _esde_game_metadata(system, path, folder, extensions, rom):
    entries, basenames = _gamelist(system, folder)
    relative = _gamelist_path(system, path, folder, basenames) or os.path.basename(path)
    fields = _game_art(system, os.path.splitext(relative)[0])
    title = _game_title(system, path, folder, index=(entries, basenames))
    if title:
        fields["title"] = title
    stem = os.path.splitext(os.path.basename(path))[0]
    legacy = f"{system}/{stem}" if rom and _legacy_roms(folder, extensions, entries, basenames, {stem}).get(stem) == rom else ""
    return dict(fields, hasCheats=bool(_cheat_file(path)), legacyKey=legacy)


def _read_metadata(request):
    if request is None:
        return None
    kind, *args = request
    if kind == "game":
        fields = _esde_game_metadata(*args)
    elif kind == "ludo":
        fields = _ludo_art(*args)
    else:
        system, seed = args
        fan = sorted(glob.glob(glob.escape(f"{MEDIA}/{system}/fanart") + "/*"))
        fields = dict(logo=_url(_system_logo(system)), fanart=_url(random.Random(seed).choice(fan) if fan else ""))
    return request, fields


def describe(event):
    """Synchronous snapshot for callers that explicitly want a complete description."""
    out, request = _esde_selection(event)
    if request is not None:
        out.update(_read_metadata(request)[1])
    return out


class NowPlaying(QObject):
    changed = Signal()
    selection = Signal()
    legacyRulesChanged = Signal()

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
        # The worker reads one immutable request and returns pure presentation
        # fields. It never owns or changes foreground selection or play state.
        request = self._metadata_request = [None]
        self._metadata = Poller(self, lambda: _read_metadata(request[0]), self._metadata_ready, 2000, now=False)
        rule_request = self._legacy_rule_request = [frozenset()]
        self._legacy_rule_proofs = {}
        self._legacy_rules = Poller(self, lambda: _rule_lookup(rule_request[0]), self._legacy_rules_ready, 15000, now=False)
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

    def watch_legacy_rules(self, keys):
        """Resolve older saved rule identities eagerly, independently of presentation."""
        wanted = frozenset(key for key in keys if legacy_key_parts(key))
        if wanted != self._legacy_rule_request[0]:
            self._legacy_rule_request[0] = wanted
            self._legacy_rule_proofs = {key: value for key, value in self._legacy_rule_proofs.items() if key in wanted}
            self._legacy_rules.refresh()
            self._republish_rule_status()
            self.legacyRulesChanged.emit()

    def legacy_rule_identity(self, key):
        """The canonical target, empty when unresolved, or None while proof is pending."""
        return self._legacy_rule_proofs.get(key) if key in self._legacy_rule_request[0] else ""

    def esde_launch_state(self, system, path, title):
        """Identity and rule readiness for an ArmadaLive-owned launch."""
        state, _ = _esde_selection(dict(event="game-select", system=system, path=path, name=title))
        self._legacy_rule_fields(state)
        return state

    def _legacy_rules_ready(self, result):
        keys, aliases = result
        if keys != self._legacy_rule_request[0]:
            return
        proofs = {key: aliases.get(key, ("",))[0] for key in keys}
        if self._legacy_rule_proofs != proofs:
            self._legacy_rule_proofs = proofs
            self._republish_rule_status()
            self.legacyRulesChanged.emit()

    def _legacy_rule_fields(self, state):
        key = _legacy_key_for_game(state["key"])
        state["legacyPending"] = False
        if key in self._legacy_rule_request[0]:
            proof = self.legacy_rule_identity(key)
            state["legacyPending"] = proof is None
            state["legacyKey"] = key if proof == state["key"] else ""

    def _republish_rule_status(self):
        if self._base_state["key"].startswith("esde:"):
            self._publish_state()

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
        self._update(synchronous=True)
        self._pinned = True

    def _selected_ui(self):
        appid, name = self._ui_app
        if not appid:
            return describe({}), None
        if isinstance(appid, str):
            return _ludo_selection(appid, name), ("ludo", appid, getattr(self._steamui, "screenshot", ""))
        return describe_steam_ui(appid, name), None

    def _update(self, synchronous=False):
        """What the bottom screen shows follows what is in front: Steam's UI, a Steam game, or ES-DE and its emulators."""
        if self._pinned:
            return
        request = None
        if self._ui_focus:                  # browsing Steam: the highlighted app, whatever runs in the background
            state, request = self._selected_ui()
            self._path, key = "", None
        elif self._steam:                   # a Steam game is in front
            self._path, state, key = "", dict(self._steam), self._steam["key"].partition("/")[2]
        elif self._sgame and not self._proc:   # a shortcut that is a game itself, and no emulator of ES-DE's behind it
            self._path, state, key = "", dict(self._sgame), "sgame|" + self._sgame["key"]
        elif self._ui_app[0] and time.monotonic() < self._hold and not self._shortcut:  # that game is still starting
            state, request = self._selected_ui()
            self._path, key = "", None
        else:                               # ES-DE's own world
            # while ES-DE is browsing, what it announces wins over an emulator that may still be running behind it
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
        if key is not None and key != self._key:  # browsing Steam's library must not throw the user back to the first page
            self._key = key
            self.selection.emit()

    def _publish_state(self):
        self._state = dict(self._base_state, **(self._metadata_fields or {}))
        self._state["metadataPending"] = self._metadata_request[0] is not None and self._metadata_fields is None
        self._legacy_rule_fields(self._state)
        self._state["playtime"] = self.history.total_for(self._state["key"]) if self.history else 0
        self.changed.emit()

    def _metadata_ready(self, result):
        request, fields = result
        if request == self._metadata_request[0] and not self._pinned and self._metadata_fields != fields:
            self._metadata_fields = fields
            self._publish_state()
