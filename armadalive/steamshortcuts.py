"""One tap puts the game in front into Steam's library as a shortcut, with its ES-DE artwork.

The launch command is the one ES-DE logged when it started that game, so the shortcut runs exactly what ES-DE would.
That means the game has to have been started from ES-DE once."""
import base64, glob, json, os, re, shlex
from PySide6.QtCore import Property, QBuffer, QIODevice, QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QImage

from .nowplaying import ES, MEDIA
from .steamui import eval_js

LOG = ES + "/logs/es_log.txt"
SHORTCUTS = os.path.expanduser("~/.local/share/Steam/userdata/*/config/shortcuts.vdf")
WRAP = "/usr/libexec/armada/armada-game-launch"   # Armada's own game wrapper, as on the other emulator shortcuts
MARK = "Expanded emulator launch command:"
ADD_JS = """((a) => (async () => {
  const A = SteamClient.Apps;
  const id = await A.AddShortcut(a.name, a.exe, a.start, a.launch);
  A.SetShortcutName(id, a.name); A.SetShortcutExe(id, a.exe); A.SetShortcutStartDir(id, a.start); A.SetShortcutLaunchOptions(id, a.launch);
  for (const [type, data, ext] of a.art) await A.SetCustomArtworkForApp(id, data, ext, type);
  return id;
})())(%s)"""


def launch_command(log, path):
    """The newest launch command in ES-DE's log that starts this ROM, split into words; None if there is none."""
    lines = log.splitlines()
    for i in range(len(lines) - 1, 0, -1):
        if lines[i - 1].endswith(MARK):
            try:
                words = shlex.split(lines[i].partition("Info:")[2])
            except ValueError:
                continue
            if path in words:
                return words
    return None


def shortcut_launches():
    """The launch options of every shortcut Steam knows (its binary shortcuts file is only searched, not parsed)."""
    found = []
    for f in glob.glob(SHORTCUTS):
        try:
            data = open(f, "rb").read()
        except OSError:
            continue
        found += [x.decode(errors="replace") for x in re.findall(rb"\x01LaunchOptions\x00([^\x00]*)\x00", data)]
    return found


def options_for(words):
    return f"{WRAP} %command% {shlex.join(words[1:])}"


def _encode(path, width, height, fmt):
    image = QImage(path)
    if image.isNull():
        return None
    if image.width() > width or image.height() > height:
        image = image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, fmt, 88)
    return base64.b64encode(bytes(buf.data())).decode()


def artwork(system, path):
    """[type, base64, extension] for what ES-DE has: 0 portrait cover, 1 hero, 2 logo, 3 wide image (Steam's asset types)."""
    base = glob.escape(os.path.splitext(os.path.basename(path))[0])
    first = lambda kind: next(iter(sorted(glob.glob(f"{glob.escape(MEDIA)}/{glob.escape(system)}/{kind}/{base}.*"))), "")
    art = []
    for kind, steam_type, size, fmt, ext in (("covers", 0, (600, 900), "JPG", "jpg"), ("fanart", 1, (1920, 1080), "JPG", "jpg"),
                                             ("marquees", 2, (1024, 512), "PNG", "png")):
        f = first(kind) or (first("screenshots") if kind == "fanart" else "")
        data = f and _encode(f, *size, fmt)
        if data:
            art.append([steam_type, data, ext])
            if steam_type == 1:
                art.append([3, _encode(f, 920, 430, fmt), ext])
    return art


class SteamShortcuts(QObject):
    changed = Signal()
    notice = Signal(str, str)   # created | exists | unknown | unreachable, and the game's title

    def __init__(self, nowplaying):
        super().__init__()
        self._np, self._s, self._busy, self._log = nowplaying, dict(possible=False, exists=False), False, ("", 0, 0)
        nowplaying.changed.connect(self.refresh)
        timer = QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(15000)   # shortcuts may also come and go outside the app
        self.refresh()

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    def _text(self):
        try:
            st = os.stat(LOG)
            if (st.st_mtime_ns, st.st_size) != self._log[1:]:
                with open(LOG, errors="replace") as f:
                    f.seek(max(0, st.st_size - 2_000_000))    # the newest part is enough
                    self._log = (f.read(), st.st_mtime_ns, st.st_size)
        except OSError:
            self._log = ("", 0, 0)
        return self._log[0]

    def _words(self):
        s = self._np.state
        if s.get("kind") != "game" or not s.get("path") or s.get("system") in ("", "steam"):
            return None
        return launch_command(self._text(), s["path"])

    def refresh(self):
        words = self._words()
        new = dict(possible=words is not None, exists=words is not None and any(
            lo.endswith(shlex.join(words[1:])) for lo in shortcut_launches()))
        if new != self._s:
            self._s = new
            self.changed.emit()

    @Slot()
    def add(self):
        state, words = self._np.state, self._words()
        title = state.get("title", "")
        if self._busy:
            return
        if not words:
            self.notice.emit("unknown", title)
            return
        self.refresh()
        if self._s["exists"]:
            self.notice.emit("exists", title)
            return
        self._busy = True
        payload = dict(name=title or os.path.basename(state["path"]), exe=f'"{words[0]}"', start=os.path.dirname(words[0]) + "/",
                       launch=options_for(words), art=artwork(state["system"], state["path"]))
        eval_js(ADD_JS % json.dumps(payload), lambda value: self._finished(title, value))

    def _finished(self, title, value):
        self._busy = False
        self.notice.emit("unreachable" if value is None else "created", title)
        QTimer.singleShot(2000, self.refresh)   # Steam writes its shortcuts file a moment later
