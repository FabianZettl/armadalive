"""Lupe: a part of the main screen, live and enlarged on the bottom screen (a minimap, a HUD corner).

gamescope offers the main screen as a PipeWire video source named "gamescope". gst-launch-1.0 reads it (pipewiresrc),
crops, scales and writes raw frames to its stdout; this class cuts them into QImages that QML shows as image://lupe/<n>.
The capture only runs while the Lupe page is open.

shortcut: pipewiresrc comes from the package pipewire-gstreamer, which Armada's image does not ship. A copy of
libgstpipewire.so in <app folder>/gst-plugins is used too (see install.sh). Without it `available` is false and the page
says what is missing."""
import json, os, re, subprocess, threading
from PySide6.QtCore import Property, QObject, QProcess, QProcessEnvironment, QRect, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = os.path.join(HERE, "gst-plugins")
CONFIG = os.path.expanduser("~/.config/armadalive/lupe.json")
PICK_W, PICK_FPS, ZOOM_FPS, MAX_SIDE = 640, 8, 30, 1280
MAIN_SIZE = (1920, 1080)   # shortcut: the Thor's main screen; gamescope sends no caps while the picture stands still


def gst_env():
    env = QProcessEnvironment.systemEnvironment()
    env.insert("GST_PLUGIN_PATH", PLUGINS + (":" + env.value("GST_PLUGIN_PATH") if env.contains("GST_PLUGIN_PATH") else ""))
    return env


def video_sources(text):
    """The node ids under Video > Sources in `wpctl status`."""
    ids, video, section = [], False, ""
    for line in text.splitlines():
        if line and line[0] not in " \t":
            video, section = line.strip().startswith("Video"), ""
            continue
        m = re.search(r"[├└]─ (\w+):", line)
        if m:
            section = m.group(1)
        elif video and section == "Sources":
            m = re.match(r"[\s│├└─]*\*?\s*(\d+)\.", line)
            if m:
                ids.append(int(m.group(1)))
    return ids


def inspected(text, key):
    """The value of `key = "value"` in the output of `wpctl inspect`, or '' ."""
    m = re.search(r'\b' + re.escape(key) + r' = "([^"]*)"', text)
    return m.group(1) if m else ""


def crop(region, size):
    """Pixels to cut off each side (left, top, right, bottom) for a region (x, y, w, h as fractions) of a (w, h) picture."""
    sw, sh = size
    x, y, w, h = (min(1.0, max(0.0, float(v))) for v in region)
    w, h = min(w, 1.0 - x), min(h, 1.0 - y)
    left, top = round(x * sw), round(y * sh)
    return left, top, max(0, sw - round((x + w) * sw)), max(0, sh - round((y + h) * sh))


def fit(aspect, box_w, box_h):
    """The largest even width and height of the given aspect that fit the box, at most MAX_SIDE a side."""
    w = min(box_w, MAX_SIDE, box_h * aspect)
    h = w / aspect
    return max(2, int(w) // 2 * 2), max(2, int(h) // 2 * 2)


def pipeline(node, size, region, out, fps):
    """gst-launch arguments: source -> frame limit -> crop -> scale -> raw BGRx on stdout."""
    left, top, right, bottom = crop(region, size)
    return ["-q", "pipewiresrc", f"path={node}", "do-timestamp=true", "!", "videorate", "drop-only=true", f"max-rate={fps}",
            "!", "videoconvert", "!", "video/x-raw,format=BGRx", "!",
            "videocrop", f"left={left}", f"top={top}", f"right={right}", f"bottom={bottom}", "!",
            "videoscale", "!", f"video/x-raw,width={out[0]},height={out[1]}", "!", "fdsink", "fd=1", "sync=false"]


class Frames:
    """Cuts a byte stream into whole frames of a fixed size."""
    def __init__(self, size):
        self.size, self.buf = size, bytearray()

    def feed(self, data):
        self.buf += data
        out = []
        while len(self.buf) >= self.size:
            out.append(bytes(self.buf[:self.size]))
            del self.buf[:self.size]
        return out


class Provider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.image = QImage(2, 2, QImage.Format.Format_RGB32)
        self.image.fill(0)

    def requestImage(self, name, size, requested):
        return self.image


class Lupe(QObject):
    changed = Signal()
    frame = Signal()

    def __init__(self):
        super().__init__()
        self.provider = Provider()
        self._proc, self._frames, self._dim = None, None, (0, 0)
        self._ok, self._why, self._node, self._src = None, "checking", 0, (1920, 1080)
        self._mode, self._tick, self._full, self._live = "off", 0, None, False
        try:
            with open(CONFIG) as f:
                saved = json.load(f)["region"]
            self._region = [float(v) for v in saved] if len(saved) == 4 else [0.0, 0.0, 1.0, 1.0]
        except (OSError, ValueError, KeyError, TypeError):
            self._region = None
        self._lock = threading.Lock()
        threading.Thread(target=self._check, daemon=True).start()

    # --- what is there
    def _check(self):
        try:
            r = subprocess.run(["gst-inspect-1.0", "pipewiresrc"], capture_output=True, timeout=10,
                               env={**os.environ, "GST_PLUGIN_PATH": PLUGINS + os.pathsep + os.environ.get("GST_PLUGIN_PATH", "")})
            ok, why = r.returncode == 0, "" if r.returncode == 0 else "plugin"
        except (OSError, subprocess.TimeoutExpired):
            ok, why = False, "gstreamer"
        if ok:
            self._node, self._src = self._find_node()
            why = "" if self._node else "source"
        self._ok, self._why = ok, why
        self.changed.emit()

    def _find_node(self):
        """The main screen's PipeWire node: of the gamescope video sources the one whose process is not the bottom screen's."""
        def inspect(obj, key):
            out = subprocess.run(["wpctl", "inspect", str(obj)], capture_output=True, text=True, timeout=5).stdout
            return inspected(out, key)
        try:
            status = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=5).stdout
            for node in video_sources(status):
                pid = inspect(inspect(node, "client.id"), "application.process.id")
                with open(f"/proc/{pid}/cgroup") as f:
                    if "bottom" not in f.read():
                        return node, MAIN_SIZE
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        return 0, MAIN_SIZE

    @Property(bool, notify=changed)
    def available(self):
        return bool(self._ok)

    @Property(str, notify=changed)
    def problem(self):
        return self._why

    @Property(str, notify=changed)
    def mode(self):
        return self._mode

    @Property(bool, notify=changed)
    def running(self):
        return self._mode != "off"

    @Property("QVariant", notify=changed)
    def region(self):
        return self._region or []

    @Property(bool, notify=changed)
    def live(self):
        """A frame of the running capture has arrived (gamescope sends one only when the picture changes)."""
        return self._live

    @Property(int, notify=frame)
    def tick(self):
        return self._tick

    # --- capture
    def _stop(self):
        proc, self._proc = self._proc, None
        if proc:
            proc.readyReadStandardOutput.disconnect()
            proc.kill()
            proc.waitForFinished(1000)

    def _launch(self, region, out, fps):
        self._stop()
        if not self._node:
            self._node, self._src = self._find_node()   # blocks for a moment: only after the source went away
        if not self._node:
            self._why = "source"
            self._mode = "off"
            self.changed.emit()
            return
        self._dim, self._live = out, False
        self._frames = Frames(out[0] * out[1] * 4)
        proc = QProcess(self)
        proc.setProcessEnvironment(gst_env())
        proc.readyReadStandardOutput.connect(self._read)
        proc.finished.connect(lambda code, _status, p=proc: self._ended(p, code))
        proc.start("gst-launch-1.0", pipeline(self._node, self._src, region, out, fps))
        self._proc = proc

    def _ended(self, proc, code):
        """The capture stopped on its own (the main screen's session restarted): look for the source again next time."""
        if proc is self._proc and self._mode != "off":
            self._proc, self._node, self._mode, self._why = None, 0, "off", "source"
            self.changed.emit()

    def _read(self):
        proc = self._proc
        if proc is None:
            return
        got = False
        for raw in self._frames.feed(bytes(proc.readAllStandardOutput())):
            w, h = self._dim
            self.provider.image, got = QImage(raw, w, h, w * 4, QImage.Format.Format_RGB32).copy(), True
            if self._mode == "pick":
                self._full = self.provider.image
        if got:
            self._tick += 1
            self.frame.emit()
            if not self._live:
                self._live = True
                self.changed.emit()

    @Slot(int, int)
    def show(self, box_w, box_h):
        """Open the Lupe in a box of that size (pixels): the area picker when none is chosen yet, else the zoomed area."""
        if not self._ok:
            return
        if not self._region:
            self.pick()
            return
        self._mode = "zoom"
        aspect = (self._region[2] * self._src[0]) / max(1.0, self._region[3] * self._src[1])
        out = fit(aspect, max(64, box_w), max(64, box_h))
        self._launch(self._region, out, ZOOM_FPS)
        self._preview(out)
        self.changed.emit()

    def _preview(self, out):
        """gamescope sends a frame only when the picture changes: until one arrives, show the chosen area cut from the picker's picture."""
        full = self._full
        if full is None:
            return
        x, y, w, h = self._region
        part = full.copy(QRect(round(x * full.width()), round(y * full.height()),
                               max(1, round(w * full.width())), max(1, round(h * full.height()))))
        self.provider.image = part.scaled(out[0], out[1], Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._tick += 1
        self.frame.emit()

    @Slot()
    def pick(self):
        """The whole main screen, small, to drag a rectangle on."""
        if not self._ok:
            return
        self._mode = "pick"
        aspect = self._src[0] / self._src[1]
        self._launch([0.0, 0.0, 1.0, 1.0], (PICK_W, int(PICK_W / aspect) // 2 * 2), PICK_FPS)
        self.changed.emit()

    @Slot(float, float, float, float, int, int)
    def select(self, x, y, w, h, box_w, box_h):
        """Keep the area (fractions of the main screen) and zoom into it."""
        if w < 0.03 or h < 0.03:
            return
        self._region = [min(1.0, max(0.0, v)) for v in (x, y, w, h)]
        try:
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
            with open(CONFIG, "w") as f:
                json.dump({"region": self._region}, f)
        except OSError:
            pass
        self.show(box_w, box_h)

    @Slot()
    def stop(self):
        self._stop()
        self._mode = "off"
        self.changed.emit()
