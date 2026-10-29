"""Watches the game controllers for Start + Select held together. Reads /dev/input directly (the `input` group may), so it
needs no setup: InputPlumber's virtual controller carries the Thor's own buttons."""
import os, re, struct
from PySide6.QtCore import QObject, QSocketNotifier, QTimer, Signal

EVENT = struct.Struct("@llHHi")   # struct input_event on 64-bit: time, type, code, value
EV_KEY, BTN_SELECT, BTN_START = 1, 314, 315
COMBO = {BTN_SELECT, BTN_START}


def devices():
    """Event nodes whose name looks like a controller; the physical pad is grabbed by InputPlumber and cannot be opened anyway."""
    try:
        text = open("/proc/bus/input/devices").read()
    except OSError:
        return []
    found = []
    for block in text.split("\n\n"):
        name, node = re.search(r'Name="([^"]*)"', block), re.search(r"\b(event\d+)\b", block)
        if name and node and re.search(r"x-?box|gamepad|controller", name.group(1), re.I):
            found.append("/dev/input/" + node.group(1))
    return found


class Pad(QObject):
    combo = Signal(bool)   # Start and Select are both down on one controller

    def __init__(self):
        super().__init__()
        self._open, self._held, self._on = {}, {}, False
        timer = QTimer(self)   # a controller that appears later (or after InputPlumber restarts) is picked up here
        timer.timeout.connect(self.scan)
        timer.start(5000)
        self.scan()

    def scan(self):
        for path in devices():
            if path in self._open:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
            notifier.activated.connect(lambda *_, p=path: self._readable(p))
            self._open[path] = (fd, notifier)

    def _readable(self, path):
        try:
            data = os.read(self._open[path][0], EVENT.size * 64)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if data:
            self.feed(path, data)
        else:       # the controller went away
            fd, notifier = self._open.pop(path)
            notifier.setEnabled(False)
            os.close(fd)
            self._held.pop(path, None)
            self._update()

    def feed(self, path, data):
        held = self._held.setdefault(path, set())
        for _, _, kind, code, value in EVENT.iter_unpack(data[:len(data) // EVENT.size * EVENT.size]):
            if kind == EV_KEY and code in COMBO and value != 2:   # 2 is auto-repeat
                held.add(code) if value else held.discard(code)
        self._update()

    def _update(self):
        on = any(COMBO <= h for h in self._held.values())
        if on != self._on:
            self._on = on
            self.combo.emit(on)
