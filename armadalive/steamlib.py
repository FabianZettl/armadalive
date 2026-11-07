"""Steam's installed games and non-Steam shortcuts, read from its files, with the cover Steam already cached for each."""
import glob, hashlib, os, re, struct
from PySide6.QtCore import QRectF, QUrl, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath

STEAM = next((p for p in (os.path.expanduser("~/.local/share/Steam"), os.path.expanduser("~/.steam/steam")) if os.path.isdir(p)), "")
SKIP = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common|SteamVR)", re.I)


def _vdf_map(data, pos=0):
    """Binary VDF (shortcuts.vdf): {key: str | int | dict}, and the position after the map's end byte."""
    out = {}
    while pos < len(data):
        kind = data[pos]
        pos += 1
        if kind == 8:
            return out, pos
        end = data.index(b"\0", pos)
        key = data[pos:end].decode("utf-8", "replace")
        pos = end + 1
        if kind == 0:
            out[key], pos = _vdf_map(data, pos)
        elif kind == 1:
            end = data.index(b"\0", pos)
            out[key], pos = data[pos:end].decode("utf-8", "replace"), end + 1
        elif kind == 2:
            out[key], pos = struct.unpack_from("<I", data, pos)[0], pos + 4
        else:
            raise ValueError("unknown VDF type")
    return out, pos


CACHE = os.path.expanduser("~/.cache/armadalive/covers")
SIZE, ROUND = 360, 0.1   # a cover is cut to a square with rounded corners once (QML cannot round an Image without shaders); ROUND is also the tile radius


def _url(path):
    """The cover as a rounded square PNG (cached), as a file url; "" without a cover."""
    if not path:
        return ""
    try:
        out = os.path.join(CACHE, hashlib.sha1(f"{path}{os.path.getmtime(path)}".encode()).hexdigest()[:20] + ".png")
        if not os.path.exists(out):
            src = QImage(path)
            if src.isNull():
                return ""
            side = min(src.width(), src.height())
            src = src.copy((src.width() - side) // 2, (src.height() - side) // 2, side, side).scaled(
                SIZE, SIZE, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            img = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(0, 0, SIZE, SIZE), SIZE * ROUND, SIZE * ROUND)
            painter = QPainter(img)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setClipPath(clip)
            painter.drawImage(0, 0, src)
            painter.end()
            os.makedirs(CACHE, exist_ok=True)
            img.save(out)
        return QUrl.fromLocalFile(out).toString()
    except OSError:
        return ""


def _first(patterns):
    for p in patterns:
        hit = sorted(glob.glob(p, recursive=True))
        if hit:
            return hit[0]
    return ""


def _libraries():
    try:
        text = open(os.path.join(STEAM, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    return {os.path.join(STEAM)} | set(re.findall(r'"path"\s+"([^"]+)"', text))


_shortcuts = (None, {})   # shortcuts.vdf mtime, {appid: (name, exe)}


def shortcut(appid):
    """(name, exe) of a non-Steam shortcut by its AppId, None if Steam has no such shortcut."""
    global _shortcuts
    files = glob.glob(os.path.join(STEAM, "userdata", "*", "config", "shortcuts.vdf")) if STEAM else []
    stamp = [(f, os.path.getmtime(f)) for f in files if os.path.exists(f)]
    if _shortcuts[0] != stamp:
        found = {}
        for f, _ in stamp:
            try:
                entries = _vdf_map(open(f, "rb").read())[0].get("shortcuts", {})
            except (OSError, ValueError, struct.error):
                continue
            for e in entries.values():
                if isinstance(e.get("appid"), int):
                    found[e["appid"]] = (e.get("AppName", ""), e.get("Exe", ""))
        _shortcuts = (stamp, found)
    return _shortcuts[1].get(int(appid))


def games():
    """[{id: "steam:<gameid>", name, icon (cover url)}]: installed games, then non-Steam shortcuts; the id's number is what RunGame takes."""
    if not STEAM:
        return []
    found = []
    for lib in _libraries():
        for f in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                text = open(f, encoding="utf-8", errors="replace").read()
                appid, name = re.search(r'"appid"\s+"(\d+)"', text).group(1), re.search(r'"name"\s+"([^"]*)"', text).group(1)
            except (OSError, AttributeError):
                continue
            if not SKIP.match(name):
                cache = os.path.join(STEAM, "appcache", "librarycache", appid)
                found.append(dict(id=f"steam:{appid}", name=name, icon=_url(_first([cache + "/**/library_600x900.jpg", cache + "/**/header.jpg"]))))
    for f in glob.glob(os.path.join(STEAM, "userdata", "*", "config", "shortcuts.vdf")):
        try:
            entries = _vdf_map(open(f, "rb").read())[0].get("shortcuts", {})
        except (OSError, ValueError, struct.error):
            continue
        grid = os.path.join(os.path.dirname(f), "grid")
        for e in entries.values():
            appid = e.get("appid", e.get("AppId"))
            name = e.get("AppName", e.get("appname"))
            if isinstance(appid, int) and name:
                found.append(dict(id=f"steam:{(appid << 32) | 0x02000000}", name=name,
                                  icon=_url(_first([f"{grid}/{appid}p.png", f"{grid}/{appid}p.jpg", f"{grid}/{appid}.png", f"{grid}/{appid}_icon.png"]))))
    return sorted({g["id"]: g for g in found}.values(), key=lambda g: g["name"].lower())
