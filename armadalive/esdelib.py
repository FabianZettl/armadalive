"""ES-DE's systems and games, read from its own files, and the launch command ES-DE itself would build for a game.

ES-DE cannot start one game from the command line, so the command is rebuilt here from its system definitions (the bundled
ones inside the AppImage, replaced by the user's `custom_systems`) and its find rules."""
import glob, os, re, shlex, shutil, subprocess, tempfile
import xml.etree.ElementTree as ET

from .nowplaying import ES, GAMELISTS, MEDIA, _rom_dir

APPIMAGE = os.path.expanduser("~/Applications/ES-DE.AppImage")
CACHE = os.path.expanduser("~/.cache/armadalive/esde")
INSIDE = "usr/share/es-de/resources/systems/linux"
DROP = ("%INJECT%", "%ENABLESHORTCUTS%", "%RUNINBACKGROUND%", "%HIDEWINDOW%")   # flags for ES-DE itself, not part of the command
COVERS = ("covers", "3dboxes", "miximages", "screenshots")


def _bundled():
    """The definition files of the installed ES-DE, unpacked once per AppImage version into the cache."""
    try:
        stamp = str(os.stat(APPIMAGE).st_mtime_ns)
    except OSError:
        return CACHE if os.path.exists(CACHE + "/es_systems.xml") else ""
    try:
        fresh = os.path.exists(CACHE + "/es_systems.xml") and open(CACHE + "/stamp").read() == stamp
    except OSError:
        fresh = False
    if not fresh:
        tmp = tempfile.mkdtemp(prefix="armadalive-esde-")
        try:
            subprocess.run([APPIMAGE, "--appimage-extract", INSIDE + "/*"], cwd=tmp, timeout=120, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.makedirs(CACHE, exist_ok=True)
            for f in ("es_systems.xml", "es_find_rules.xml"):
                shutil.copy(f"{tmp}/squashfs-root/{INSIDE}/{f}", f"{CACHE}/{f}")
            open(CACHE + "/stamp", "w").write(stamp)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return CACHE if os.path.exists(CACHE + "/es_systems.xml") else ""


def _parse(path):
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return ET.Element("none")


def systems():
    """{name: {fullname, extensions, commands: [(label, template)]}}; the user's custom_systems replace bundled ones by name."""
    out, base = {}, _bundled()
    for root in (_parse(base + "/es_systems.xml"), _parse(ES + "/custom_systems/es_systems.xml")):
        for s in root.iter("system"):
            name = s.findtext("name")
            if name:
                out[name] = dict(fullname=s.findtext("fullname") or name, extensions=set((s.findtext("extension") or "").lower().split()),
                                 commands=[(c.get("label") or "", (c.text or "").strip()) for c in s.findall("command")])
    return out


def _rules():
    out = {}
    for root in (_parse(_bundled() + "/es_find_rules.xml"), _parse(ES + "/custom_systems/es_find_rules.xml")):
        for tag in ("emulator", "core"):
            for e in root.iter(tag):
                out[(tag, e.get("name"))] = [(r.get("type"), [(x.text or "").strip() for x in r.findall("entry")]) for r in e.findall("rule")]
    return out


def _find(rules, tag, name, member=""):
    for kind, entries in rules.get((tag, name), []):
        for entry in entries:
            if kind == "systempath" and tag == "emulator":
                hit = shutil.which(entry)
            elif kind in ("staticpath", "corepath"):
                hits = [h for h in sorted(glob.glob(os.path.expanduser(entry))) if not member or os.path.exists(os.path.join(h, member))]
                hit = hits[0] if hits else None
            else:
                hit = None
            if hit:
                return hit
    return None


def command(system, rom, defs=None, rules=None, label=""):
    """The command words for this ROM as ES-DE would run it (the chosen alternative emulator, else the system's first command);
    None if it needs something this cannot place, or an emulator that is not installed."""
    defs = defs or systems()
    rules = rules or _rules()
    s = defs.get(system)
    if not s or not s["commands"]:
        return None
    label = label or _alternative(system, rom)
    template = next((t for lab, t in s["commands"] if lab == label), s["commands"][0][1])
    base, parent = os.path.basename(rom), os.path.dirname(rom)
    subs = {"%ROM%": rom, "%ROMRAW%": rom, "%FILENAME%": base, "%BASENAME%": os.path.splitext(base)[0], "%GAMEDIR%": parent,
            "%GAMEDIRRAW%": parent, "%ROMPATH%": _rom_dir()}
    words = []
    try:
        pieces = shlex.split(template)
    except ValueError:
        return None
    for w in pieces:
        if w in DROP:
            continue
        for key, value in subs.items():
            w = w.replace(key, value)
        for core in re.findall(r"%CORE_([A-Z0-9_-]+)%/?([^\s%]*)", w):
            where = _find(rules, "core", core[0], core[1])
            w = w.replace(f"%CORE_{core[0]}%", where or "%MISSING%")
        for emu in re.findall(r"%EMULATOR_([A-Z0-9_-]+)%", w):
            where = _find(rules, "emulator", emu)
            w = w.replace(f"%EMULATOR_{emu}%", where or "%MISSING%")
        words.append(w)
    return None if any("%" in w and re.search(r"%[A-Z_0-9-]+%", w) for w in words) else words


def _alternative(system, rom):
    """The emulator ES-DE was told to use: for this game in its gamelist, else for the whole system."""
    root = _parse(f"{GAMELISTS}/{system}/gamelist.xml")
    for g in root.iter("game"):
        if os.path.basename(g.findtext("path") or "") == os.path.basename(rom) and g.findtext("altemulator"):
            return g.findtext("altemulator")
    return root.findtext("alternativeEmulator/label") or ""


def _cover(system, path):
    base = glob.escape(os.path.splitext(os.path.basename(path))[0])
    for kind in COVERS:
        hit = sorted(glob.glob(f"{glob.escape(MEDIA)}/{glob.escape(system)}/{kind}/{base}.*"))
        if hit:
            return hit[0]
    return ""


def games():
    """{system: [{id: "esde:<system>/<path under the system folder>", name, cover (file path), rom}]} for systems that have games."""
    root, out = _rom_dir(), {}
    for name, s in systems().items():
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        titles, hidden = {}, set()
        for g in _parse(f"{GAMELISTS}/{name}/gamelist.xml").iter("game"):
            key = os.path.basename(g.findtext("path") or "")
            titles[key] = g.findtext("name") or ""
            if (g.findtext("hidden") or "").lower() == "true":
                hidden.add(key)
        found = []
        for here, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("media", "images", "videos", "manuals")]
            for f in files:
                if f.startswith(".") or os.path.splitext(f)[1].lower() not in s["extensions"] or f in hidden:
                    continue
                path = os.path.join(here, f)
                found.append(dict(id=f"esde:{name}/{os.path.relpath(path, folder)}", name=titles.get(f) or os.path.splitext(f)[0],
                                  cover=_cover(name, path), rom=path))
        if found:
            out[name] = sorted(found, key=lambda g: g["name"].lower())
    return out
